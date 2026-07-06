"""Fixture data loading for the eval-scenario harness.

Points at a scenario directory (eval/scenarios/<name>/) containing
alert.json, deploys.json, and error_samples.json. Selected via the
SCENARIO_DIR env var so the tool functions in agent/core/tools/ can be
swapped for real backends (git, Loki, Prometheus) later without changing
their signatures — only this module's loaders change.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_DEFAULT_SCENARIO = (
    Path(__file__).resolve().parents[2] / "eval" / "scenarios" / "scenario_01"
)


def scenario_path() -> Path:
    override = os.environ.get("SCENARIO_DIR")
    return Path(override) if override else _DEFAULT_SCENARIO


def load_alert() -> dict:
    return json.loads((scenario_path() / "alert.json").read_text())


def load_deploys() -> list[dict]:
    return json.loads((scenario_path() / "deploys.json").read_text())


def load_error_samples() -> list[dict]:
    return json.loads((scenario_path() / "error_samples.json").read_text())
