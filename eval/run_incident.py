"""Run one fixture scenario through the FULL investigation + remediation
graph, including the human-in-the-loop approval interrupt (a CLI stand-in
for the eventual Slack Approve/Reject button), then generate a postmortem.

Usage:
    SCENARIO_DIR=eval/scenarios/scenario_01 python -m eval.run_incident
    SCENARIO_DIR=eval/scenarios/scenario_01 python -m eval.run_incident --auto-approve
    SCENARIO_DIR=eval/scenarios/scenario_01 python -m eval.run_incident --auto-reject
"""

from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv
from langgraph.types import Command

from agent.core.fix_format import format_suggested_fix
from agent.core.fixtures import load_alert, scenario_path
from agent.core.graph import build_graph
from agent.core.postmortem import generate_postmortem

load_dotenv()

POSTMORTEMS_DIR = Path(__file__).resolve().parents[1] / "postmortems"


def _write_postmortem(incident_id: str, incident: dict) -> Path:
    POSTMORTEMS_DIR.mkdir(exist_ok=True)
    path = POSTMORTEMS_DIR / f"{incident_id}.md"
    path.write_text(generate_postmortem(incident))
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto-approve", action="store_true")
    parser.add_argument("--auto-reject", action="store_true")
    args = parser.parse_args()

    alert = load_alert()
    incident_id = f"incident-{scenario_path().name}"
    config = {"configurable": {"thread_id": incident_id}}

    graph = build_graph()
    result = graph.invoke(
        {"incident_id": incident_id, "alert": alert, "messages": []},
        config=config,
    )

    print("=== INCIDENT BRIEF ===")
    culprit = result["culprit_commit"]
    runbook = result.get("runbook_match")
    print(f"Culprit: {culprit['commit_sha']} (confidence={culprit['confidence']})")
    print(f"Reasoning: {culprit['reasoning']}")
    print(f"Runbook: {runbook['runbook_id'] if runbook else 'none found'}")
    print(f"Impact: {result['impact']['summary']}")

    fix_block = format_suggested_fix(result.get("suggested_fix"))
    if fix_block:
        print(fix_block)

    proposed = result.get("proposed_action")
    if not proposed:
        print("\nNo remediation proposed — investigation complete, no approval needed.")
        final = result
    else:
        print(f"\nProposed action: {proposed['action_type']} on {proposed['target_service']}")
        print(f"Args: {proposed['action_args']}")
        print(f"Rationale: {proposed['rationale']}")

        if args.auto_approve:
            decision = "approved"
        elif args.auto_reject:
            decision = "rejected"
        else:
            answer = input("\nApprove this action? [y/N] ").strip().lower()
            decision = "approved" if answer == "y" else "rejected"

        final = graph.invoke(Command(resume=decision), config=config)
        print(f"\nDecision: {decision}")
        print(f"Execution result: {final['execution_result']}")

    # Resolution reached (either an action was decided, or none was needed) —
    # generate the postmortem from the full incident record.
    print("\n=== POSTMORTEM ===")
    path = _write_postmortem(incident_id, {"incident_id": incident_id, **final})
    print(f"Written to {path}\n")
    print(path.read_text())


if __name__ == "__main__":
    main()
