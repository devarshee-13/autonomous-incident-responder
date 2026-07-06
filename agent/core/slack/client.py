"""Slack client wrapper: posts and updates the incident brief message.

Uses a plain slack_bolt App as an API client here (chat_postMessage/
chat_update) — the same App instance is reused by agent/slack_listener.py
to also handle button-click events via Socket Mode.
"""

from __future__ import annotations

import os

from slack_bolt import App

from agent.core.slack.blocks import incident_brief_blocks

_app: App | None = None


def get_app() -> App:
    global _app
    if _app is None:
        _app = App(token=os.environ["SLACK_BOT_TOKEN"])
    return _app


def post_incident_brief(
    *,
    incident_id: str,
    alert: dict,
    culprit: dict,
    runbook: dict | None,
    impact: dict,
    proposed_action: dict | None,
) -> str:
    """Post the incident brief to the configured channel. Returns the
    message timestamp (unused by the caller today, but handy for logging —
    the Slack listener gets its own copy of channel/ts from the interaction
    payload when a button is clicked, see agent/slack_listener.py)."""
    app = get_app()
    channel = os.environ["SLACK_CHANNEL_ID"]
    blocks = incident_brief_blocks(
        alert=alert,
        culprit=culprit,
        runbook=runbook,
        impact=impact,
        proposed_action=proposed_action,
        incident_id=incident_id,
    )
    response = app.client.chat_postMessage(
        channel=channel,
        text=f"Incident: {alert['alert_name']} on {alert['service']}",
        blocks=blocks,
    )
    return response["ts"]
