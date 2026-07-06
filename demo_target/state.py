"""In-memory state for the demo-target: bug toggle, metrics counters,
error-log ring buffer, and the deploy log.

Deliberately in-process and simple — this is a demo target meant to be run
as a single process alongside a traffic generator, not a production
service. Resets on restart.
"""

from __future__ import annotations

import threading
import time
import traceback
from collections import deque

SERVICE = "payments-service"

# Flipped on by demo_target/inject_bug.py to "deploy" the bad pricing code.
BUGGY = False

_lock = threading.Lock()

# Rolling request/error counts over a short window, for the error-rate metric.
_WINDOW_SECONDS = 60
_requests: deque[float] = deque()          # timestamps of all requests
_errors: deque[float] = deque()            # timestamps of failed requests

# Structured error-log ring buffer (what get_error_samples reads).
_error_log: deque[dict] = deque(maxlen=500)

# Deploy log (what get_recent_deploys / get_commit_diff read). Seeded with a
# few benign deploys so the injected bad deploy has innocent neighbors to be
# distinguished from — same idea as the eval fixtures' decoy commits.
_deploys: list[dict] = [
    {
        "service": SERVICE,
        "commit_sha": "seed_a1b2c3",
        "author": "mchen",
        "message": "Add structured logging around checkout flow",
        "deployed_at": None,  # filled in at import time below
        "files_changed": ["payments/checkout.py"],
        "diff": (
            "--- a/payments/checkout.py\n+++ b/payments/checkout.py\n"
            "@@ -12,6 +12,7 @@ def checkout(cart):\n"
            '+    logger.info("checkout_started", cart_id=cart.id)\n'
            "     total = calculate_total(cart.subtotal, cart.discount_pct)\n"
        ),
    },
    {
        "service": SERVICE,
        "commit_sha": "seed_d4e5f6",
        "author": "jsmith",
        "message": "Bump requests library version",
        "deployed_at": None,
        "files_changed": ["requirements.txt"],
        "diff": (
            "--- a/requirements.txt\n+++ b/requirements.txt\n"
            "@@ -4,1 +4,1 @@\n-requests==2.31.0\n+requests==2.32.3\n"
        ),
    },
]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# Backfill seed deploy timestamps to a bit before startup.
for _i, _deploy in enumerate(_deploys):
    _deploy["deployed_at"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600 * (len(_deploys) - _i))
    )


def _prune(dq: deque[float], now: float) -> None:
    while dq and now - dq[0] > _WINDOW_SECONDS:
        dq.popleft()


def record_request(error: bool) -> None:
    now = time.time()
    with _lock:
        _requests.append(now)
        _prune(_requests, now)
        if error:
            _errors.append(now)
            _prune(_errors, now)


def record_error(exc: BaseException) -> None:
    with _lock:
        _error_log.append(
            {
                "service": SERVICE,
                "timestamp": _now_iso(),
                "fingerprint": f"{type(exc).__name__.lower()}-checkout",
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "stack_trace": "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                ),
            }
        )


def metrics_snapshot() -> dict:
    now = time.time()
    with _lock:
        _prune(_requests, now)
        _prune(_errors, now)
        total = len(_requests)
        errors = len(_errors)
    error_rate = (errors / total) if total else 0.0
    return {
        "service": SERVICE,
        "window_seconds": _WINDOW_SECONDS,
        "request_count": total,
        "error_count": errors,
        "error_rate": round(error_rate, 4),
        "request_rate_per_min": total,  # window is 60s, so count == per-min
    }


def recent_errors(limit: int = 20) -> list[dict]:
    with _lock:
        # Most recent first; collapse to one representative per fingerprint
        # with a count, matching the shape get_error_samples expects.
        by_fp: dict[str, dict] = {}
        for entry in reversed(_error_log):
            fp = entry["fingerprint"]
            if fp not in by_fp:
                by_fp[fp] = {**entry, "count": 0}
            by_fp[fp]["count"] += 1
    return list(by_fp.values())[:limit]


def deploys() -> list[dict]:
    with _lock:
        return list(_deploys)


def record_deploy(deploy: dict) -> None:
    with _lock:
        _deploys.append(deploy)
