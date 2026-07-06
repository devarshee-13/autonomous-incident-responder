"""Inject the pricing bug into the running demo-target.

Thin client that POSTs /_inject_bug on the demo-target (a separate process,
so it can't flip the server's in-memory toggle directly). After this runs,
checkouts with a 100% discount start raising ZeroDivisionError.

Usage:
    python -m demo_target.inject_bug              # inject
    python -m demo_target.inject_bug --reset      # turn the bug back off
"""

from __future__ import annotations

import argparse
import os
import urllib.request

TARGET_URL = os.environ.get("DEMO_TARGET_URL", "http://localhost:8100")


def _post(path: str) -> None:
    req = urllib.request.Request(f"{TARGET_URL}{path}", method="POST", data=b"")
    with urllib.request.urlopen(req) as resp:
        print(resp.read().decode())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    _post("/_reset" if args.reset else "/_inject_bug")


if __name__ == "__main__":
    main()
