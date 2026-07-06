"""Metrics tool: queries a Prometheus-style metric for a service.

Backed by static fixture JSON during the fixture-harness phase — returns a
canned baseline/during comparison regardless of the exact start/end window,
since the fixtures don't model a full time series yet. Swapped for real
Prometheus queries once the demo-target system exists.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.tools import tool

from agent.core.fixtures import load_metrics

_METRIC_KEYS = {
    "error_rate": "error_rate",
    "request_rate": "request_rate_per_min",
    "p99_latency": "p99_latency_ms",
}


@tool
def query_metrics(
    service: str,
    metric: Literal["error_rate", "request_rate", "p99_latency"],
    start: str,
    end: str,
    step_seconds: int = 30,
) -> dict:
    """Query a Prometheus metric for a service over a time window, including
    a baseline comparison from before the window."""
    metrics = load_metrics()
    if metrics["service"] != service:
        raise ValueError(f"No metrics fixture for service {service!r}")

    values = metrics.get(_METRIC_KEYS[metric])
    if values is None:
        raise ValueError(f"No fixture data for metric {metric!r}")

    return {
        "service": service,
        "metric": metric,
        "baseline": values["baseline"],
        "during": values["during"],
        "observed_duration_minutes": metrics["observed_duration_minutes"],
    }
