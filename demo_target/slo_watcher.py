"""SLO watcher: the lightweight stand-in for Prometheus + Alertmanager.

Polls the demo-target's /metrics, and when the error rate breaches the SLO
threshold, fires an alert to the agent's webhook — exactly the payload
shape the agent expects (matching eval/scenarios/*/alert.json). Fires once
per breach episode (edge-triggered), not on every poll, so a sustained
outage produces one incident rather than a flood.

Usage (with the agent webhook running on :8000 and the demo-target on :8100):
    python -m demo_target.slo_watcher
"""

from __future__ import annotations

import json
import os
import time
import urllib.request

TARGET_URL = os.environ.get("DEMO_TARGET_URL", "http://localhost:8100")
AGENT_WEBHOOK_URL = os.environ.get(
    "AGENT_WEBHOOK_URL", "http://localhost:8000/webhooks/alertmanager"
)
ERROR_RATE_THRESHOLD = float(os.environ.get("SLO_ERROR_RATE", "0.05"))
POLL_SECONDS = float(os.environ.get("SLO_POLL_SECONDS", "5"))
MIN_REQUESTS = 20  # don't alert on a tiny sample


def _get_metrics() -> dict:
    with urllib.request.urlopen(f"{TARGET_URL}/metrics") as resp:
        return json.loads(resp.read())


def _fire_alert(metrics: dict) -> None:
    alert = {
        "service": metrics["service"],
        "alert_name": "HighErrorRate",
        "description": (
            f"Error rate for {metrics['service']} is "
            f"{metrics['error_rate']:.1%} (threshold {ERROR_RATE_THRESHOLD:.0%})"
        ),
        "fired_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "severity": "critical",
    }
    data = json.dumps(alert).encode()
    req = urllib.request.Request(
        AGENT_WEBHOOK_URL, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        print(f"  -> alert fired, agent responded: {resp.read().decode()}")


def main() -> None:
    print(
        f"Watching {TARGET_URL}/metrics "
        f"(threshold {ERROR_RATE_THRESHOLD:.0%}, poll {POLL_SECONDS}s)..."
    )
    breaching = False  # edge-trigger latch
    while True:
        try:
            metrics = _get_metrics()
        except Exception as exc:  # noqa: BLE001 — demo watcher: log and keep polling
            print(f"  metrics poll failed: {exc}")
            time.sleep(POLL_SECONDS)
            continue

        over = (
            metrics["request_count"] >= MIN_REQUESTS
            and metrics["error_rate"] >= ERROR_RATE_THRESHOLD
        )
        print(
            f"  error_rate={metrics['error_rate']:.1%} "
            f"requests={metrics['request_count']} "
            f"{'BREACH' if over else 'ok'}"
        )

        if over and not breaching:
            breaching = True
            print("SLO breached — firing alert to agent.")
            _fire_alert(metrics)
        elif not over:
            breaching = False

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
