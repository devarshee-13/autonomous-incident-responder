"""Typed action registry for approval-gated remediations.

The model can only propose actions from this fixed set — never free-form
commands. See docs/DESIGN.md §2 (proposed_actions) and §3 (propose_action).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RollbackToPreviousDeploy(BaseModel):
    action_type: Literal["rollback_to_previous_deploy"] = "rollback_to_previous_deploy"
    target_service: str = Field(description="The service to roll back — the alert's service")
    target_commit_sha: str = Field(
        description=(
            "The last-known-good commit to restore, i.e. the deploy "
            "immediately before the culprit — NOT the culprit itself. "
            "Filled in deterministically by the agent (see graph._rollback_target)."
        )
    )


class RestartService(BaseModel):
    action_type: Literal["restart_service"] = "restart_service"
    target_service: str


class ScaleService(BaseModel):
    action_type: Literal["scale_service"] = "scale_service"
    target_service: str
    replicas: int = Field(gt=0)


ACTION_SCHEMAS = {
    "rollback_to_previous_deploy": RollbackToPreviousDeploy,
    "restart_service": RestartService,
    "scale_service": ScaleService,
}


def validate_action(action_type: str, target_service: str, args: dict) -> BaseModel:
    """Validate a proposed action's args against its registered schema."""
    schema = ACTION_SCHEMAS.get(action_type)
    if schema is None:
        raise ValueError(f"Unknown action_type: {action_type!r}")
    return schema(action_type=action_type, target_service=target_service, **args)
