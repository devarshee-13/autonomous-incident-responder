"""Backend data loading for the agent's investigation tools.

Two modes, selected by env var — the tool functions in agent/core/tools/
call these loaders and never know which is active, so their signatures stay
stable (this is the decoupling docs/DESIGN.md §2 calls for):

  - Fixture mode (default): read static scenario JSON from
    eval/scenarios/<name>/, chosen via SCENARIO_DIR. Used by the eval set.
  - Live mode (DEMO_TARGET_URL set): HTTP-query the running demo-target's
    introspection endpoints (see demo_target/app.py). Used when responding
    to a genuinely fired alert.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

_DEFAULT_SCENARIO = (
    Path(__file__).resolve().parents[2] / "eval" / "scenarios" / "scenario_01"
)


def _demo_target_url() -> str | None:
    return os.environ.get("DEMO_TARGET_URL")


def _http_get_json(path: str):
    with urllib.request.urlopen(f"{_demo_target_url()}{path}") as resp:
        return json.loads(resp.read())


def scenario_path() -> Path:
    override = os.environ.get("SCENARIO_DIR")
    return Path(override) if override else _DEFAULT_SCENARIO


def load_alert() -> dict:
    # Only the eval scripts call this; the live path gets its alert from the
    # webhook payload, not from here.
    return json.loads((scenario_path() / "alert.json").read_text())


def load_deploys() -> list[dict]:
    if _demo_target_url():
        return _http_get_json("/_deploys")
    return json.loads((scenario_path() / "deploys.json").read_text())


def load_error_samples() -> list[dict]:
    if _demo_target_url():
        return _http_get_json("/_errors")
    return json.loads((scenario_path() / "error_samples.json").read_text())


def load_metrics() -> dict:
    if _demo_target_url():
        return _live_metrics()
    return json.loads((scenario_path() / "metrics.json").read_text())


def _live_metrics() -> dict:
    """Adapt the demo-target's flat /metrics snapshot into the nested
    baseline/during shape query_metrics expects. The live service doesn't
    retain queryable pre-breach history, so we assume a healthy baseline
    (near-zero errors, steady request rate) and treat the current snapshot
    as the "during" window — good enough for an approximate impact estimate.
    """
    snap = _http_get_json("/metrics")
    rpm = snap["request_rate_per_min"]
    return {
        "service": snap["service"],
        "error_rate": {"baseline": 0.005, "during": snap["error_rate"]},
        "request_rate_per_min": {"baseline": rpm, "during": rpm},
        "p99_latency_ms": {"baseline": 100, "during": 100},
        "observed_duration_minutes": max(round(snap["window_seconds"] / 60), 1),
    }
