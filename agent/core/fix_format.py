"""Shared plain-text formatting for a suggested fix, used by the CLI incident
briefs (eval/run_incident.py and agent/api/main_cli.py)."""

from __future__ import annotations


def format_suggested_fix(suggested_fix: dict | None) -> str | None:
    """Render a suggested_fix state entry as a console block, or None if there
    is no fix to show."""
    if not suggested_fix:
        return None

    v = suggested_fix.get("verification", {})
    if v.get("bug_reproduced") and v.get("fix_verified"):
        status = "verified (test fails on the bug, passes on the fix)"
    elif v.get("fix_verified"):
        status = "fix passes the test (bug reproduction unconfirmed)"
    else:
        status = "could not verify automatically"

    return (
        "\nSuggested fix (advisory — complements the rollback):\n"
        f"  {suggested_fix['explanation']}\n"
        f"  Verification: {status}\n"
        f"  --- corrected code ---\n{_indent(suggested_fix['fixed_code'])}\n"
        f"  --- verifying test ---\n{_indent(suggested_fix['test_code'])}"
    )


def _indent(text: str) -> str:
    return "\n".join(f"    {line}" for line in text.strip().splitlines())
