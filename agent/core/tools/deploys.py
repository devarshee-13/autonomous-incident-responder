"""Deploy-log tool: lists commits deployed to a service before a given time.

Backed by static fixture JSON during the fixture-harness phase (see
eval/scenarios/). Will be swapped for a real deploy-log service/table once
the demo-target system exists, without changing the tool's signature.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from langchain_core.tools import tool

from agent.core.fixtures import load_deploys


@tool
def get_recent_deploys(service: str, before: str, lookback_minutes: int = 120) -> list[dict]:
    """List deploys (commit + timestamp) for a service within a lookback
    window before a given time. Use this to find candidate commits that
    could have caused an alert."""
    before_dt = datetime.fromisoformat(before.replace("Z", "+00:00"))
    window_start = before_dt - timedelta(minutes=lookback_minutes)

    candidates = []
    for deploy in load_deploys():
        if deploy["service"] != service:
            continue
        deployed_at = datetime.fromisoformat(deploy["deployed_at"].replace("Z", "+00:00"))
        if window_start <= deployed_at <= before_dt:
            candidates.append(
                {
                    "commit_sha": deploy["commit_sha"],
                    "author": deploy["author"],
                    "message": deploy["message"],
                    "deployed_at": deploy["deployed_at"],
                    "files_changed": deploy["files_changed"],
                }
            )
    return candidates
