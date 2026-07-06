"""Slack Socket Mode listener: handles Approve/Reject button clicks by
resuming the paused investigation graph.

Runs as its own long-lived process, separate from the FastAPI alert
webhook (agent/api/main.py) — the two share state only through Postgres
(the checkpointer), not through memory. Socket Mode establishes an
outbound connection to Slack, so no public URL/ngrok is needed for local
development, unlike the classic HTTP-webhook interactivity mode.

Usage:
    python -m agent.slack_listener
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langgraph.types import Command
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from agent.core.checkpointer import get_postgres_checkpointer
from agent.core.graph import build_graph
from agent.core.slack.blocks import decision_result_blocks

load_dotenv()

app = App(token=os.environ["SLACK_BOT_TOKEN"])
_checkpointer = get_postgres_checkpointer()
_graph = build_graph(checkpointer=_checkpointer)


def _handle_decision(decision: str, body: dict, client) -> None:
    incident_id = body["actions"][0]["value"]
    channel = body["channel"]["id"]
    ts = body["message"]["ts"]
    decided_by = body["user"]["id"]

    config = {"configurable": {"thread_id": incident_id}}
    final = _graph.invoke(Command(resume=decision), config=config)

    client.chat_update(
        channel=channel,
        ts=ts,
        text=f"Decision: {decision}",
        blocks=decision_result_blocks(
            decision=decision,
            execution_result=final["execution_result"],
            decided_by=decided_by,
        ),
    )


@app.action("approve_action")
def handle_approve(ack, body, client):
    ack()
    _handle_decision("approved", body, client)


@app.action("reject_action")
def handle_reject(ack, body, client):
    ack()
    _handle_decision("rejected", body, client)


def main() -> None:
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    print("Slack listener running (Socket Mode) — waiting for button clicks...")
    handler.start()


if __name__ == "__main__":
    main()
