"""Run fixture scenario(s) through the investigation graph and check the
results against ground truth.

Usage:
    # ANTHROPIC_API_KEY is loaded from a .env file in the project root (see
    # .env.example) — no need to `export` it by hand.

    # run every scenario under eval/scenarios/
    python -m eval.run_scenario

    # run just one
    SCENARIO_DIR=eval/scenarios/scenario_01 python -m eval.run_scenario
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from eval.harness import discover_scenarios, run_scenario

load_dotenv()

# This eval measures culprit ranking, not fix generation — skip the (slower,
# costlier) suggest_fix node so the ranking eval stays fast. run_incident.py
# exercises the fix path instead.
os.environ.setdefault("SKIP_FIX_SUGGESTION", "1")


def main() -> None:
    override = os.environ.get("SCENARIO_DIR")
    scenario_dirs = [Path(override)] if override else discover_scenarios()

    results = [run_scenario(d) for d in scenario_dirs]

    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] {r.name}: {r.detail}")
        print(f"       reasoning: {r.reasoning}")
        if r.runbook_match:
            print(
                f"       runbook: {r.runbook_match['runbook_id']} "
                f"(score={r.runbook_match['score']})"
            )
        if r.impact:
            print(f"       impact: {r.impact['summary']}")
        if r.proposed_action:
            print(
                f"       proposed action: {r.proposed_action['action_type']} "
                f"on {r.proposed_action['target_service']} (pending approval — "
                f"see eval/run_incident.py to exercise the approval flow)"
            )
        print()

    passed = sum(r.passed for r in results)
    print(f"{passed}/{len(results)} scenarios passed")


if __name__ == "__main__":
    main()
