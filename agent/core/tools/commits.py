"""Commit-diff tool: fetches the diff for a specific commit.

Backed by the same fixture JSON as tools/deploys.py during the fixture-harness
phase; swapped for real `git show` against the target repo later.
"""

from __future__ import annotations

from langchain_core.tools import tool

from agent.core.fixtures import load_deploys


@tool
def get_commit_diff(service: str, commit_sha: str) -> dict:
    """Get the diff and changed files for a specific commit, so its contents
    can be compared against error stack traces."""
    for deploy in load_deploys():
        if deploy["service"] == service and deploy["commit_sha"] == commit_sha:
            return {
                "commit_sha": commit_sha,
                "message": deploy["message"],
                "files_changed": deploy["files_changed"],
                "diff": deploy["diff"],
            }
    raise ValueError(f"Unknown commit_sha {commit_sha!r} for service {service!r}")
