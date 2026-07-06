"""The demo-target's FastAPI app.

Two kinds of endpoints:
  - /checkout, /metrics — the "public" surface: real work + observability,
    hit by the traffic generator and polled by the SLO watcher.
  - /_deploys, /_commits/{sha}, /_errors — introspection endpoints the
    agent's investigation tools query (in live mode, DEMO_TARGET_URL set).
    These stand in for what would be a real deploy log / log backend / git.

Run with:
    uvicorn demo_target.app:app --port 8100
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from demo_target import checkout as checkout_logic
from demo_target import state

app = FastAPI(title="demo-target: payments-service")


@app.post("/checkout")
def do_checkout(payload: dict):
    """payload: {"subtotal": float, "discount_pct": float}. Records the
    request (and any error) into metrics + the error log, mirroring how a
    real service's instrumentation would."""
    try:
        result = checkout_logic.checkout(
            subtotal=payload["subtotal"], discount_pct=payload["discount_pct"]
        )
        state.record_request(error=False)
        return result
    except Exception as exc:  # noqa: BLE001 — demo target: catch, record, surface
        state.record_request(error=True)
        state.record_error(exc)
        raise HTTPException(status_code=500, detail=type(exc).__name__) from exc


@app.get("/metrics")
def metrics():
    return state.metrics_snapshot()


@app.get("/_deploys")
def get_deploys():
    return state.deploys()


@app.get("/_commits/{commit_sha}")
def get_commit(commit_sha: str):
    for deploy in state.deploys():
        if deploy["commit_sha"] == commit_sha:
            return deploy
    raise HTTPException(status_code=404, detail=f"unknown commit {commit_sha}")


@app.get("/_errors")
def get_errors(limit: int = 20):
    return state.recent_errors(limit=limit)


@app.post("/_inject_bug")
def inject_bug():
    """Admin endpoint: 'deploy' the buggy pricing code. Flips the in-process
    bug toggle AND records a deploy entry carrying the real before/after
    diff, so the investigating agent finds a genuine culprit deploy. Called
    by demo_target/inject_bug.py (which runs as a separate process and so
    can't flip the server's toggle directly)."""
    state.BUGGY = True
    deploy = {
        "service": state.SERVICE,
        "commit_sha": "bad_deploy01",
        "author": "agupta",
        "message": "Support percentage discounts up to 100% in total calculation",
        "deployed_at": state._now_iso(),
        "files_changed": ["payments/pricing.py"],
        "diff": (
            "--- a/payments/pricing.py\n+++ b/payments/pricing.py\n"
            "@@ -38,7 +38,7 @@ def calculate_total(subtotal, discount_pct):\n"
            "-    return subtotal * (1 - discount_pct / 100)\n"
            "+    return subtotal / (1 - discount_pct / 100)\n"
        ),
    }
    state.record_deploy(deploy)
    return {"status": "bug injected", "commit_sha": deploy["commit_sha"]}


@app.post("/_reset")
def reset_bug():
    """Admin endpoint: turn the bug back off (does not remove the deploy
    record). Handy for re-running the demo without restarting the server."""
    state.BUGGY = False
    return {"status": "bug cleared"}
