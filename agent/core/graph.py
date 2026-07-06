"""Investigation graph: LangGraph StateGraph wiring the culprit-ranking nodes.

This is the first slice: gather_context + rank_commits only. Later slices
add search_runbook, estimate_impact, propose_remediation, and the
human-in-the-loop interrupt before execute_action. See docs/DESIGN.md §3.
"""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from agent.core.ranking import rank_candidates
from agent.core.state import State
from agent.core.tools.commits import get_commit_diff
from agent.core.tools.deploys import get_recent_deploys
from agent.core.tools.logs import get_error_samples
from agent.core.tools.metrics import query_metrics
from agent.core.tools.runbooks import search_runbooks

MODEL = "claude-opus-4-8"


class RankedCandidate(BaseModel):
    commit_sha: str
    rank: int
    reasoning: str


class CulpritVerdict(BaseModel):
    commit_sha: str | None = Field(
        default=None,
        description=(
            "The commit most likely responsible for the alert, or null if none "
            "of the candidates plausibly explain the observed error."
        ),
    )
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    ranked_candidates: list[RankedCandidate]


def gather_context(state: State) -> dict:
    """Deterministic context pull: recent deploys + error samples, narrowed
    by the heuristic pre-filter in ranking.py before the model ever sees
    them. No model call here — this node is plain Python."""
    alert = state["alert"]
    deploys = get_recent_deploys.invoke(
        {"service": alert["service"], "before": alert["fired_at"], "lookback_minutes": 180}
    )
    error_samples = get_error_samples.invoke(
        {"service": alert["service"], "start": alert["fired_at"], "end": alert["fired_at"]}
    )
    candidates = rank_candidates(deploys, error_samples, alert["fired_at"])

    samples_text = "\n\n".join(
        f"[{s['exception_type']}] {s['message']} (x{s['count']})\n{s['stack_trace']}"
        for s in error_samples
    )
    candidates_text = "\n".join(
        f"- {c['commit_sha']} (heuristic_score={c['heuristic_score']}): {c['message']} "
        f"[files: {', '.join(c['files_changed'])}]"
        for c in candidates
    )

    prompt = (
        f"An alert fired for service={alert['service']} at {alert['fired_at']}: "
        f"{alert['description']}\n\n"
        f"Recent error samples:\n{samples_text}\n\n"
        f"Candidate deploys (heuristically pre-ranked, highest score first). "
        f"Use get_commit_diff to inspect any commit's contents before deciding:\n"
        f"{candidates_text}\n\n"
        "Determine which commit most likely caused this alert. If, after "
        "reading the diffs, none of the candidates plausibly explain the "
        "observed error (e.g. the error looks like an external/downstream "
        "failure, or none of the changed code paths relate to the stack "
        "trace), say so explicitly and give a low confidence score rather "
        "than confidently blaming an innocent commit."
    )

    return {
        "deploy_candidates": candidates,
        "messages": [HumanMessage(content=prompt)],
    }


def rank_commits(state: State) -> dict:
    """Model-driven step: reason over diffs (via get_commit_diff) and emit a
    structured culprit verdict."""
    model = ChatAnthropic(model=MODEL).bind_tools([get_commit_diff])
    history = list(state["messages"])
    new_messages: list = []

    # Tool-calling loop: keep going while the model asks for get_commit_diff.
    # Only new_messages is returned to the graph state (see the note below on
    # why we don't re-return `history`).
    while True:
        response = model.invoke(history + new_messages)
        new_messages.append(response)
        if not response.tool_calls:
            break
        for call in response.tool_calls:
            result = get_commit_diff.invoke(call["args"])
            new_messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

    # A second, separately-configured call extracts the structured verdict
    # from the finished conversation — cleaner than parsing JSON out of the
    # free-text response by hand. The tool-calling loop above ends on the
    # model's own assistant-role message, and Claude 4.6+/Opus 4.8 reject any
    # request whose conversation ends in an assistant turn (no prefill) — so
    # we append one more user turn asking for the verdict before this call.
    extraction_prompt = HumanMessage(
        content=(
            "Based on the investigation above, provide your final verdict: "
            "the most likely culprit commit, your confidence, your reasoning, "
            "and a full ranking of all candidates considered."
        )
    )
    new_messages.append(extraction_prompt)

    verdict_model = ChatAnthropic(model=MODEL).with_structured_output(CulpritVerdict)
    verdict: CulpritVerdict = verdict_model.invoke(history + new_messages)

    return {
        # `messages` uses the add_messages reducer, which appends whatever is
        # returned here onto state["messages"] — returning `history` again
        # would duplicate it, so only the messages generated in this node go
        # back.
        "messages": new_messages,
        "culprit_commit": {
            "commit_sha": verdict.commit_sha,
            "confidence": verdict.confidence,
            "reasoning": verdict.reasoning,
        },
        "ranked_candidates": [c.model_dump() for c in verdict.ranked_candidates],
    }


def search_runbook(state: State) -> dict:
    """Deterministic retrieval: find the best-matching runbook using the
    alert description plus the culprit reasoning as the query. Plain
    Python — no model call needed for this lookup (see docs/DESIGN.md)."""
    alert = state["alert"]
    culprit = state["culprit_commit"]
    query = f"{alert['description']} {culprit['reasoning']}"
    matches = search_runbooks.invoke({"query": query, "top_k": 1})
    return {"runbook_match": matches[0] if matches else None}


def estimate_impact(state: State) -> dict:
    """Deterministic impact estimate: pull error-rate/request-rate metrics
    and derive an approximate affected-request count. Plain Python — this
    is arithmetic, not reasoning, so no model call here either."""
    alert = state["alert"]
    error = query_metrics.invoke(
        {
            "service": alert["service"],
            "metric": "error_rate",
            "start": alert["fired_at"],
            "end": alert["fired_at"],
        }
    )
    requests = query_metrics.invoke(
        {
            "service": alert["service"],
            "metric": "request_rate",
            "start": alert["fired_at"],
            "end": alert["fired_at"],
        }
    )

    duration_min = error["observed_duration_minutes"]
    delta = max(error["during"] - error["baseline"], 0.0)
    affected_requests = round(delta * requests["during"] * duration_min)

    summary = (
        f"Error rate rose from {error['baseline']:.1%} to {error['during']:.1%} "
        f"over ~{duration_min} min, at ~{requests['during']:.0f} req/min — "
        f"an estimated {affected_requests} requests affected."
    )

    return {
        "impact": {
            "error_rate_baseline": error["baseline"],
            "error_rate_during": error["during"],
            "estimated_affected_requests": affected_requests,
            "duration_minutes": duration_min,
            "summary": summary,
        }
    }


def build_graph():
    graph = StateGraph(State)
    graph.add_node("gather_context", gather_context)
    graph.add_node("rank_commits", rank_commits)
    graph.add_node("search_runbook", search_runbook)
    graph.add_node("estimate_impact", estimate_impact)
    graph.add_edge(START, "gather_context")
    graph.add_edge("gather_context", "rank_commits")
    graph.add_edge("rank_commits", "search_runbook")
    graph.add_edge("search_runbook", "estimate_impact")
    graph.add_edge("estimate_impact", END)
    return graph.compile()
