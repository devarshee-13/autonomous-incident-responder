"""propose_action tool: lets the model propose a remediation from the fixed
action registry. Does NOT execute anything — validates the args against the
registry and returns a proposal for human approval. See docs/DESIGN.md §3.
"""

from __future__ import annotations

import uuid
from typing import Literal

from langchain_core.tools import tool

from agent.core.actions.registry import validate_action


@tool
def propose_action(
    action_type: Literal["rollback_to_previous_deploy", "restart_service", "scale_service"],
    target_service: str,
    action_args: dict,
    rationale: str,
) -> dict:
    """Propose a remediation action. This does NOT execute anything — it
    creates a pending approval request that a human must approve before it
    runs. action_args is action-specific, e.g. {"target_commit_sha": "..."}
    for rollback_to_previous_deploy or {"replicas": 3} for scale_service."""
    validated = validate_action(action_type, target_service, action_args)
    return {
        "proposed_action_id": str(uuid.uuid4()),
        "action_type": action_type,
        "target_service": target_service,
        "action_args": action_args,
        "rationale": rationale,
        "validated_action": validated.model_dump(),
    }
