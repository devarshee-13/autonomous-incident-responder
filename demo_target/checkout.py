"""The demo-target's actual business logic: a tiny checkout/pricing service.

This is the code that gets a bug "deployed" into it. The bug is a real
divide-by-zero in the discount math (mirroring eval scenario_01) — toggled
by state.BUGGY rather than by editing this file at runtime, but the deploy
record written by inject_bug.py carries the genuine before/after diff of
these two code paths so the agent has a real diff to reason over.
"""

from __future__ import annotations

from demo_target import state


def calculate_total(subtotal: float, discount_pct: float) -> float:
    """Apply a percentage discount to a subtotal.

    Correct form multiplies by the remaining fraction. The buggy form
    (shipped by the injected deploy) divides by it, which blows up at a
    100% discount: (1 - 100/100) == 0.
    """
    if state.BUGGY:
        return subtotal / (1 - discount_pct / 100)  # ZeroDivisionError at 100%
    return subtotal * (1 - discount_pct / 100)


def checkout(subtotal: float, discount_pct: float) -> dict:
    """Run a checkout. Returns the computed total; raises on the injected
    bug so the caller (the FastAPI layer) records it as an error."""
    total = calculate_total(subtotal, discount_pct)
    return {"total": round(total, 2)}
