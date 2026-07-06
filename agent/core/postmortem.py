"""Postmortem generator.

Turns a resolved incident's accumulated state (the graph's final State —
alert, culprit, runbook, impact, action + decision + result) into a
structured markdown postmortem. A single LLM call, per docs/DESIGN.md's
"kept simple" framing for this piece — the raw material is the investigation
record the graph already produced, so no additional data-gathering here.

Called after resolution (a separate trigger from the investigation itself),
not as a graph node — see eval/run_incident.py for how it's invoked in the
fixture flow.
"""

from __future__ import annotations

import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

MODEL = "claude-opus-4-8"

_SYSTEM = (
    "You are an SRE writing a blameless postmortem after a production "
    "incident has been resolved. Write in clear, factual markdown. Use these "
    "sections exactly: '## Summary', '## Timeline', '## Root Cause', "
    "'## Impact', '## Resolution', '## Action Items'. If the record contains "
    "a suggested_fix, also add a '## Suggested Fix' section (after Resolution) "
    "summarizing the proposed code change, including its verification status "
    "(whether an automated test reproduced the bug and confirmed the fix); "
    "include the corrected code and test in fenced code blocks. Keep it "
    "concise and specific to the data provided; do not invent details that "
    "aren't supported by the incident record. Action Items should be concrete "
    "follow-ups (tests to add, guards to introduce, alerting gaps to close), "
    "framed as preventing recurrence rather than assigning blame."
)


def generate_postmortem(incident: dict) -> str:
    """incident: the final graph State (or the relevant subset). Returns the
    postmortem as a markdown string."""
    record = {
        "incident_id": incident.get("incident_id"),
        "alert": incident.get("alert"),
        "probable_cause": incident.get("culprit_commit"),
        "ranked_candidates": incident.get("ranked_candidates"),
        "runbook": incident.get("runbook_match"),
        "impact": incident.get("impact"),
        "proposed_action": incident.get("proposed_action"),
        "decision": incident.get("action_decision"),
        "execution_result": incident.get("execution_result"),
        "suggested_fix": incident.get("suggested_fix"),
    }

    # langchain-anthropic defaults to max_tokens=1024, which truncates a
    # full postmortem mid-document — set a comfortable ceiling. Well within
    # non-streaming limits, so no need to stream.
    model = ChatAnthropic(model=MODEL, max_tokens=8192)
    prompt = (
        "Write a postmortem for the following resolved incident. The record "
        "is the output of an automated investigation agent:\n\n"
        f"{json.dumps(record, indent=2, default=str)}"
    )
    response = model.invoke(
        [HumanMessage(content=f"{_SYSTEM}\n\n{prompt}")]
    )
    return response.content if isinstance(response.content, str) else str(response.content)
