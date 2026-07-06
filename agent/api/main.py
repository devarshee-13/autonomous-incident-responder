"""FastAPI app: receives alert webhooks and kicks off an incident
investigation, posting the resulting brief to Slack.

Run with:
    uvicorn agent.api.main:app --reload

Test with a fixture-shaped alert (no real alerting stack needed yet):
    curl -X POST http://localhost:8000/webhooks/alertmanager \
        -H "Content-Type: application/json" \
        -d @eval/scenarios/scenario_01/alert.json

Note: this runs the investigation synchronously within the request — fine
for a demo/single-alert-at-a-time project, but a real deployment would move
this to a background task/queue so the webhook returns immediately.
"""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI

from agent.core.checkpointer import get_postgres_checkpointer
from agent.core.graph import build_graph
from agent.core.slack.client import post_incident_brief

load_dotenv()

app = FastAPI()
_checkpointer = get_postgres_checkpointer()
_graph = build_graph(checkpointer=_checkpointer)


@app.post("/webhooks/alertmanager")
def handle_alert(alert: dict):
    """alert must match the shape used across eval/scenarios/*/alert.json:
    {"service", "alert_name", "description", "fired_at", "severity"}."""
    incident_id = f"incident-{alert['service']}-{alert['fired_at']}"
    config = {"configurable": {"thread_id": incident_id}}

    result = _graph.invoke(
        {"incident_id": incident_id, "alert": alert, "messages": []},
        config=config,
    )

    post_incident_brief(
        incident_id=incident_id,
        alert=alert,
        culprit=result["culprit_commit"],
        runbook=result.get("runbook_match"),
        impact=result["impact"],
        proposed_action=result.get("proposed_action"),
    )

    return {"incident_id": incident_id, "status": "posted"}
