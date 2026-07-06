"""Error-log tool: fetches recent error samples/stack traces for a service.

Backed by static fixture JSON during the fixture-harness phase; swapped for a
real log backend (Loki, CloudWatch, etc.) later.
"""

from __future__ import annotations

from langchain_core.tools import tool

from agent.core.fixtures import load_error_samples


@tool
def get_error_samples(service: str, start: str, end: str, limit: int = 20) -> list[dict]:
    """Fetch recent error log samples/stack traces for a service in a time
    window, grouped by fingerprint with counts."""
    samples = [s for s in load_error_samples() if s["service"] == service]
    return samples[:limit]
