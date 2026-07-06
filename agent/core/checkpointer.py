"""Postgres checkpointer for the investigation graph.

Needed once the agent runs as multiple long-lived processes (the FastAPI
alert webhook + the Slack Socket Mode listener) instead of a single CLI
script — the approval interrupt has to survive being resumed from a
different process than the one that created it, sometimes minutes later.
MemorySaver (used by the eval/fixture scripts) can't do that across
processes; this can. See docs/DESIGN.md §3.
"""

from __future__ import annotations

import os

from langgraph.checkpoint.postgres import PostgresSaver


def get_postgres_checkpointer() -> PostgresSaver:
    database_url = os.environ["DATABASE_URL"]
    checkpointer = PostgresSaver.from_conn_string(database_url)
    checkpointer.setup()
    return checkpointer
