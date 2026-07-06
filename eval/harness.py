"""Shared logic for running a single fixture scenario through the
investigation graph and checking the result against ground truth.

A scenario's expected.json is one of two shapes:
  - {"culprit_commit_sha": "<sha>", ...}          -- must match exactly
  - {"culprit_commit_sha": null,
     "max_expected_confidence_if_null": 0.4, ...} -- no real culprit exists;
     the model should express low confidence rather than confidently blame
     an innocent commit.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from agent.core.fixtures import load_alert
from agent.core.graph import build_graph

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    detail: str
    commit_sha: str | None
    confidence: float
    reasoning: str
    runbook_match: dict | None
    impact: dict | None


def discover_scenarios() -> list[Path]:
    return sorted(p for p in SCENARIOS_DIR.iterdir() if p.is_dir())


def run_scenario(scenario_dir: Path) -> ScenarioResult:
    # Tool functions read SCENARIO_DIR (via agent.core.fixtures) on every
    # call, so switching this per-scenario is enough to swap fixture data —
    # no process restart needed between scenarios.
    os.environ["SCENARIO_DIR"] = str(scenario_dir)

    alert = load_alert()
    expected = json.loads((scenario_dir / "expected.json").read_text())

    graph = build_graph()
    result = graph.invoke(
        {
            "incident_id": f"eval-{scenario_dir.name}",
            "alert": alert,
            "messages": [],
        }
    )
    culprit = result["culprit_commit"]

    expected_sha = expected.get("culprit_commit_sha")
    if expected_sha is not None:
        passed = culprit["commit_sha"] == expected_sha
        detail = f"expected {expected_sha}, got {culprit['commit_sha']}"
    else:
        threshold = expected.get("max_expected_confidence_if_null", 0.4)
        passed = culprit["confidence"] <= threshold
        detail = (
            f"expected no confident culprit (confidence <= {threshold}), "
            f"got {culprit['commit_sha']!r} at confidence={culprit['confidence']}"
        )

    return ScenarioResult(
        name=scenario_dir.name,
        passed=passed,
        detail=detail,
        commit_sha=culprit["commit_sha"],
        confidence=culprit["confidence"],
        reasoning=culprit["reasoning"],
        runbook_match=result.get("runbook_match"),
        impact=result.get("impact"),
    )
