"""Traffic generator for the demo-target.

Continuously POSTs /checkout with a mix of carts. A fraction carry a 100%
discount — harmless while the service is healthy (total just goes to 0),
but the trigger for the injected divide-by-zero bug once it's deployed.
That's what makes the error rate climb organically after injection rather
than needing the generator to know anything about the bug.

Usage:
    python -m demo_target.traffic
    python -m demo_target.traffic --rate 20 --full-discount-frac 0.15
"""

from __future__ import annotations

import argparse
import os
import random
import time
import urllib.error
import urllib.request

TARGET_URL = os.environ.get("DEMO_TARGET_URL", "http://localhost:8100")


def _checkout(subtotal: float, discount_pct: float) -> bool:
    """Returns True on success, False on a 5xx (the injected bug)."""
    import json

    data = json.dumps({"subtotal": subtotal, "discount_pct": discount_pct}).encode()
    req = urllib.request.Request(
        f"{TARGET_URL}/checkout", data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req):
            return True
    except urllib.error.HTTPError:
        return False
    except urllib.error.URLError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rate", type=float, default=15, help="requests per second")
    parser.add_argument(
        "--full-discount-frac",
        type=float,
        default=0.12,
        help="fraction of carts with a 100%% discount",
    )
    args = parser.parse_args()

    interval = 1.0 / args.rate
    print(f"Sending ~{args.rate} req/s to {TARGET_URL} (Ctrl+C to stop)...")
    ok = err = 0
    try:
        while True:
            subtotal = round(random.uniform(10, 500), 2)
            discount = 100.0 if random.random() < args.full_discount_frac else random.choice(
                [0, 10, 20, 25]
            )
            if _checkout(subtotal, discount):
                ok += 1
            else:
                err += 1
            if (ok + err) % 50 == 0:
                print(f"  sent={ok + err} ok={ok} err={err}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\nStopped. total={ok + err} ok={ok} err={err}")


if __name__ == "__main__":
    main()
