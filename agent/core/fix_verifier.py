"""Verify a suggested code fix by actually running a test against it.

Given the model's reconstructed buggy module, its corrected module, and a
pytest test, this runs the test twice — once against the buggy code (expected
to FAIL, proving the test reproduces the bug) and once against the fixed code
(expected to PASS, proving the fix resolves it). That fail-then-pass pair is
what makes the suggested fix *verified* rather than merely asserted.

⚠️ SECURITY: this executes model-generated code. It is scoped to a throwaway
temp dir and run as a subprocess with a timeout — but it is NOT a hardened
sandbox (no seccomp, no network isolation). This is a deliberate demo-only
boundary; never point this at untrusted input in a real deployment.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

_TIMEOUT_SECONDS = 30


def verify_fix(buggy_code: str, fixed_code: str, test_code: str) -> dict:
    """Run test_code against buggy_code then fixed_code.

    The test is expected to import the subject under test as `from subject
    import ...`, so buggy_code and fixed_code are each written as subject.py
    in turn. Returns:
        {
          "bug_reproduced": bool,   # test failed against the buggy code
          "fix_verified": bool,     # test passed against the fixed code
          "output": str,            # combined pytest output from both runs
        }
    Never raises — a timeout, crash, or import error degrades to
    bug_reproduced/fix_verified = False with the captured output.
    """
    with tempfile.TemporaryDirectory(prefix="fixverify_") as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "test_subject.py").write_text(test_code)

        buggy_rc, buggy_out = _run_pytest(tmp_path, subject_code=buggy_code)
        fixed_rc, fixed_out = _run_pytest(tmp_path, subject_code=fixed_code)

    return {
        # A non-zero return code on the buggy code means the test failed there,
        # i.e. it genuinely catches the bug. rc is None on timeout/crash.
        "bug_reproduced": buggy_rc is not None and buggy_rc != 0,
        "fix_verified": fixed_rc == 0,
        "output": (
            f"--- pytest against BUGGY code (expect failure) ---\n{buggy_out}\n\n"
            f"--- pytest against FIXED code (expect pass) ---\n{fixed_out}"
        ),
    }


def _run_pytest(tmp_path: Path, subject_code: str) -> tuple[int | None, str]:
    """Write subject.py and run pytest in tmp_path. Returns (returncode,
    output); returncode is None if the run timed out or failed to launch."""
    (tmp_path / "subject.py").write_text(subject_code)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "test_subject.py"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
        return proc.returncode, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return None, f"(timed out after {_TIMEOUT_SECONDS}s)"
    except Exception as exc:  # noqa: BLE001 — verification must never crash the graph
        return None, f"(failed to run pytest: {exc})"
