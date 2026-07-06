"""Run a fixture scenario through the investigation graph and check the
result against the scenario's ground truth.

Usage:
    export ANTHROPIC_API_KEY=...
    SCENARIO_DIR=eval/scenarios/scenario_01 python -m eval.run_scenario
"""

from __future__ import annotations

import json

from agent.core.fixtures import load_alert, scenario_path
from agent.core.graph import build_graph


def main() -> None:
    alert = load_alert()
    expected = json.loads((scenario_path() / "expected.json").read_text())

    graph = build_graph()
    result = graph.invoke(
        {
            "incident_id": f"eval-{scenario_path().name}",
            "alert": alert,
            "messages": [],
        }
    )

    culprit = result["culprit_commit"]
    print(f"Predicted culprit: {culprit['commit_sha']} (confidence={culprit['confidence']})")
    print(f"Reasoning: {culprit['reasoning']}\n")
    print("Ranked candidates:")
    for c in result["ranked_candidates"]:
        print(f"  {c['rank']}. {c['commit_sha']} — {c['reasoning']}")

    expected_sha = expected["culprit_commit_sha"]
    passed = culprit["commit_sha"] == expected_sha
    print(f"\n{'PASS' if passed else 'FAIL'}: expected {expected_sha}")


if __name__ == "__main__":
    main()
