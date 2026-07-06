"""Heuristic pre-filter for culprit-commit candidates.

Narrows get_recent_deploys' output to the top candidates before handing them
to the model for causal reasoning over diffs (the rank_commits graph node) —
keeps that step grounded in real signals and cheap. See docs/DESIGN.md §3.

Score = weighted(recency, file/stack-trace overlap). Overlap is weighted
higher than recency on purpose: the most recent deploy is a weak signal on
its own (most deploys aren't bad), but a deploy that touches a file appearing
in the actual error stack trace is strong evidence.
"""

from __future__ import annotations

from datetime import datetime


def rank_candidates(
    deploy_candidates: list[dict],
    error_samples: list[dict],
    alert_fired_at: str,
    top_k: int = 5,
    recency_weight: float = 0.3,
    overlap_weight: float = 0.7,
) -> list[dict]:
    """Score and sort deploy candidates; return the top_k with scores attached."""
    trace_files = _stack_trace_files(error_samples)

    scored = []
    for deploy in deploy_candidates:
        minutes_ago = _minutes_before(deploy["deployed_at"], alert_fired_at)
        recency = _recency_score(minutes_ago)
        overlap = _file_overlap_score(deploy["files_changed"], trace_files)
        score = recency_weight * recency + overlap_weight * overlap
        scored.append({**deploy, "heuristic_score": round(score, 4)})

    scored.sort(key=lambda d: d["heuristic_score"], reverse=True)
    return scored[:top_k]


def _minutes_before(deployed_at: str, alert_fired_at: str) -> float:
    deployed = datetime.fromisoformat(deployed_at.replace("Z", "+00:00"))
    fired = datetime.fromisoformat(alert_fired_at.replace("Z", "+00:00"))
    return (fired - deployed).total_seconds() / 60


def _recency_score(minutes_ago: float) -> float:
    # decays toward 0 as the deploy gets further from alert onset
    return 1 / (1 + minutes_ago / 60)


def _file_overlap_score(files_changed: list[str], stack_trace_files: set[str]) -> float:
    return 1.0 if any(f in stack_trace_files for f in files_changed) else 0.0


def _stack_trace_files(error_samples: list[dict]) -> set[str]:
    files: set[str] = set()
    for sample in error_samples:
        for line in sample.get("stack_trace", "").splitlines():
            line = line.strip()
            if line.startswith('File "'):
                # e.g. File "payments/pricing.py", line 39, in calculate_total
                files.add(line.split('"')[1])
    return files
