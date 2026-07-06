"""Action executors: what actually happens once a proposed action is
approved.

Fixture-phase stubs only — no real target system exists yet, so these just
return a description of what they would do. Swapped for real rollback/
restart/scale calls against the demo-target system once it exists.
"""

from __future__ import annotations

from pydantic import BaseModel


def execute(action: BaseModel) -> str:
    """Execute a validated action. Returns a human-readable result summary."""
    match action.action_type:
        case "rollback_to_previous_deploy":
            return (
                f"[stub] Would roll back {action.target_service} to "
                f"commit {action.target_commit_sha}."
            )
        case "restart_service":
            return f"[stub] Would restart {action.target_service}."
        case "scale_service":
            return (
                f"[stub] Would scale {action.target_service} to "
                f"{action.replicas} replicas."
            )
        case _:
            raise ValueError(f"No executor for action_type: {action.action_type!r}")
