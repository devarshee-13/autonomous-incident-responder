"""LangGraph state schema shared across all investigation nodes.

See docs/DESIGN.md §3. Fields beyond deploy_candidates/culprit_commit/
ranked_candidates are populated by nodes added in later slices
(search_runbook, estimate_impact, propose_remediation).
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class State(TypedDict):
    incident_id: str
    alert: dict
    deploy_candidates: list[dict]
    recent_deploys: list[dict]
    culprit_commit: dict | None
    ranked_candidates: list[dict]
    suggested_fix: dict | None
    runbook_match: dict | None
    impact: dict | None
    proposed_action: dict | None
    proposed_action_id: str | None
    action_decision: str | None
    execution_result: str | None
    messages: Annotated[list[BaseMessage], add_messages]
