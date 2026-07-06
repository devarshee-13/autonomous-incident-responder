"""Slack-free variant of the alert webhook: runs the investigation and
prints the incident brief to the server console instead of posting to Slack.

Lets you exercise the full live loop (demo-target → SLO watcher → agent
investigation) with no Slack app and no Postgres — it uses the in-memory
checkpointer, since this path handles each alert synchronously in one
process and never resumes across processes. Use agent/api/main.py (Slack +
Postgres) for the real, approval-gated flow.

Run with:
    DEMO_TARGET_URL=http://localhost:8100 uvicorn agent.api.main_cli:app --port 8000
"""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI

from agent.core.fix_format import format_suggested_fix
from agent.core.graph import build_graph

load_dotenv()

app = FastAPI()
_graph = build_graph()  # in-memory checkpointer (default)


@app.post("/webhooks/alertmanager")
def handle_alert(alert: dict):
    incident_id = f"incident-{alert['service']}-{alert['fired_at']}"
    config = {"configurable": {"thread_id": incident_id}}

    _graph.invoke(
        {"incident_id": incident_id, "alert": alert, "messages": []},
        config=config,
    )
    # Read accumulated state directly — robust whether or not the graph
    # paused at the approval interrupt (it pauses only if an action was
    # proposed).
    snapshot = _graph.get_state(config).values

    culprit = snapshot["culprit_commit"]
    runbook = snapshot.get("runbook_match")
    impact = snapshot["impact"]
    proposed = snapshot.get("proposed_action")

    print("\n" + "=" * 60)
    print(f"INCIDENT BRIEF — {incident_id}")
    print("=" * 60)
    print(f"Probable cause: {culprit['commit_sha']} (confidence={culprit['confidence']})")
    print(f"Reasoning: {culprit['reasoning']}")
    print(f"Runbook: {runbook['runbook_id'] if runbook else 'none found'}")
    print(f"Impact: {impact['summary']}")
    fix_block = format_suggested_fix(snapshot.get("suggested_fix"))
    if fix_block:
        print(fix_block)
    fix = snapshot.get("suggested_fix")
    fix_applyable = bool(fix and fix.get("verification", {}).get("fix_verified"))
    if proposed or fix_applyable:
        if proposed:
            print(f"\nProposed action: {proposed['action_type']} on {proposed['target_service']}")
            print(f"Args: {proposed['action_args']}")
            print(f"Rationale: {proposed['rationale']}")
        if fix_applyable:
            print("\nProposed: open a PR applying the verified fix shown above.")
        print(
            "\n(Pending approval — no approval channel wired in this Slack-free "
            "variant. Use agent/api/main.py + the Slack listener for the "
            "approve/reject flow.)"
        )
    else:
        print("\nNo remediation proposed — investigation complete.")
    print("=" * 60 + "\n")

    return {
        "incident_id": incident_id,
        "culprit_commit": culprit["commit_sha"],
        "confidence": culprit["confidence"],
        "proposed_action": proposed["action_type"] if proposed else None,
    }
