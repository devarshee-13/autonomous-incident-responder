"""Investigation graph: LangGraph StateGraph wiring the culprit-ranking nodes.

This is the first slice: gather_context + rank_commits only. Later slices
add search_runbook, estimate_impact, propose_remediation, and the
human-in-the-loop interrupt before execute_action. See docs/DESIGN.md §3.
"""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field, ValidationError

from agent.core.actions.executors import execute
from agent.core.actions.registry import validate_action
from agent.core.ranking import rank_candidates
from agent.core.state import State
from agent.core.tools.actions import propose_action
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

    # Structured-output extraction is a real LLM call, not a deterministic
    # parse — the model occasionally omits a required field (observed:
    # dropping ranked_candidates). Retry a couple of times before giving up,
    # rather than letting a single flaky response crash the whole graph.
    verdict_model = ChatAnthropic(model=MODEL).with_structured_output(CulpritVerdict)
    verdict: CulpritVerdict | None = None
    last_error: Exception | None = None
    for _ in range(3):
        try:
            verdict = verdict_model.invoke(history + new_messages)
            break
        except ValidationError as e:
            last_error = e
    if verdict is None:
        raise RuntimeError(
            f"Model failed to produce a valid CulpritVerdict after 3 attempts: {last_error}"
        )

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


def propose_remediation(state: State) -> dict:
    """Model-driven step: decide whether a remediation is warranted and, if
    so, propose one from the fixed action registry via propose_action. The
    model may also decide no action is warranted and just respond in text —
    tool_choice is left at "auto", not forced, so it has that option.

    propose_action validates its args against the registry and raises if the
    model gets them wrong (e.g. missing target_commit_sha for a rollback).
    That error is fed back as a tool_result so the model can correct itself
    — the standard tool-error-recovery pattern — rather than crashing the
    graph on one bad call, which matters more here than elsewhere since this
    is the step right before something reaches a human for approval."""
    model = ChatAnthropic(model=MODEL).bind_tools([propose_action])
    culprit = state["culprit_commit"]
    runbook = state["runbook_match"]
    impact = state["impact"]

    prompt = (
        "Investigation summary:\n"
        f"- Probable cause: {culprit['commit_sha']} "
        f"(confidence={culprit['confidence']}) — {culprit['reasoning']}\n"
        f"- Matching runbook: {runbook['title'] if runbook else 'none found'}\n"
        f"- Impact: {impact['summary']}\n\n"
        "Decide whether a remediation action is warranted. If the culprit "
        "commit is identified with reasonable confidence and a rollback is "
        "the appropriate mitigation, call propose_action. If confidence is "
        "low, no code-level cause was found, or no safe automated action "
        "applies, do not call any tool — just briefly explain why no action "
        "is proposed."
    )
    messages: list = [HumanMessage(content=prompt)]

    proposed_result = None
    for _ in range(3):  # bounded so a persistently-wrong model can't loop forever
        response = model.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            return {"proposed_action": None, "proposed_action_id": None}

        call = response.tool_calls[0]
        try:
            proposed_result = propose_action.invoke(call["args"])
        except ValidationError as e:
            messages.append(ToolMessage(content=f"Error: {e}", tool_call_id=call["id"]))
            continue
        break

    if proposed_result is None:
        # Model couldn't produce valid action args after retries — treat as
        # "no safe action to propose" rather than crashing the graph.
        return {"proposed_action": None, "proposed_action_id": None}

    return {
        "proposed_action": proposed_result,
        "proposed_action_id": proposed_result["proposed_action_id"],
    }


def _route_after_proposal(state: State) -> str:
    return "await_approval" if state.get("proposed_action") else END


def await_approval(state: State) -> dict:
    """Pause the graph until a human approves or rejects the proposed
    action (the Slack Approve/Reject click, in the real system — a CLI
    prompt for now, see eval/run_incident.py). This node does nothing else,
    so re-running it on resume (LangGraph restarts an interrupted node from
    the top) never redoes expensive work — see docs/DESIGN.md §3."""
    decision = interrupt(
        {
            "proposed_action": state["proposed_action"],
            "message": "Approve or reject the proposed remediation action.",
        }
    )
    return {"action_decision": decision}


def execute_action(state: State) -> dict:
    """Run the approved action via the registry executor, or record that it
    was skipped if rejected. Executors are fixture-phase stubs (see
    agent/core/actions/executors.py) since no real target system exists yet."""
    decision = state.get("action_decision")
    if decision != "approved":
        return {"execution_result": f"Skipped — action_decision was {decision!r}."}

    proposed = state["proposed_action"]
    validated = validate_action(
        proposed["action_type"], proposed["target_service"], proposed["action_args"]
    )
    return {"execution_result": execute(validated)}


def build_graph(checkpointer=None):
    graph = StateGraph(State)
    graph.add_node("gather_context", gather_context)
    graph.add_node("rank_commits", rank_commits)
    graph.add_node("search_runbook", search_runbook)
    graph.add_node("estimate_impact", estimate_impact)
    graph.add_node("propose_remediation", propose_remediation)
    graph.add_node("await_approval", await_approval)
    graph.add_node("execute_action", execute_action)

    graph.add_edge(START, "gather_context")
    graph.add_edge("gather_context", "rank_commits")
    graph.add_edge("rank_commits", "search_runbook")
    graph.add_edge("search_runbook", "estimate_impact")
    graph.add_edge("estimate_impact", "propose_remediation")
    graph.add_conditional_edges("propose_remediation", _route_after_proposal)
    graph.add_edge("await_approval", "execute_action")
    graph.add_edge("execute_action", END)

    # A checkpointer is required for the interrupt above to persist state
    # across the pause. Callers that need the pause to survive a separate
    # process (the FastAPI webhook + Slack listener split) pass a real
    # checkpointer in (see agent/core/checkpointer.py); eval/fixture scripts
    # get the in-memory default, which is fine within one process.
    return graph.compile(checkpointer=checkpointer or MemorySaver())
