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
    fix = result.get("suggested_fix")
    fix_applyable = bool(fix and fix.get("verification", {}).get("fix_verified"))

    if not proposed and not fix_applyable:
        print("\nNothing to approve — investigation complete, no approval needed.")
        final = result
    else:
        # Two independently-approvable remediations may be pending: the
        # rollback (immediate mitigation) and applying the verified fix (a PR).
        if proposed:
            print(f"\nProposed action: {proposed['action_type']} on {proposed['target_service']}")
            print(f"Args: {proposed['action_args']}")
            print(f"Rationale: {proposed['rationale']}")
        if fix_applyable:
            print("\nProposed: open a PR applying the verified fix shown above.")

        if args.auto_approve:
            action_dec, fix_dec = "approved", "approved"
        elif args.auto_reject:
            action_dec, fix_dec = "rejected", "rejected"
        else:
            action_dec = fix_dec = None
            if proposed:
                a = input("\nApprove the rollback? [y/N] ").strip().lower()
                action_dec = "approved" if a == "y" else "rejected"
            if fix_applyable:
                f = input("Approve opening a PR with the verified fix? [y/N] ").strip().lower()
                fix_dec = "approved" if f == "y" else "rejected"

        final = graph.invoke(
            Command(resume={"action": action_dec, "fix": fix_dec}), config=config
        )
        if proposed:
            print(f"\nRollback decision: {action_dec} — {final.get('execution_result')}")
        if fix_applyable:
            print(f"Fix decision: {fix_dec} — {final.get('fix_apply_result')}")

    # Resolution reached (either an action was decided, or none was needed) —
    # generate the postmortem from the full incident record.
    print("\n=== POSTMORTEM ===")
    path = _write_postmortem(incident_id, {"incident_id": incident_id, **final})
    print(f"Written to {path}\n")
    print(path.read_text())


if __name__ == "__main__":
    main()
