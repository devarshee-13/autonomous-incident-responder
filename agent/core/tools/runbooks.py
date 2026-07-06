"""Runbook search tool: retrieval over the runbook corpus.

Uses simple keyword-overlap scoring for now — no embeddings/pgvector yet.
Consistent with keeping supporting features simple while culprit-ranking and
the graph itself get the real depth (see docs/DESIGN.md). Swap for real
vector search once the demo-target system's Postgres/pgvector exists.
"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.tools import tool

RUNBOOKS_DIR = Path(__file__).resolve().parents[3] / "runbooks"

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _load_runbooks() -> list[dict]:
    runbooks = []
    for path in sorted(RUNBOOKS_DIR.glob("*.md")):
        text = path.read_text()
        title = text.splitlines()[0].lstrip("#").strip()
        runbooks.append({"runbook_id": path.stem, "title": title, "content": text})
    return runbooks


@tool
def search_runbooks(query: str, top_k: int = 3) -> list[dict]:
    """Semantic search over the runbook corpus. Use the alert description
    and/or error signature as the query."""
    query_tokens = _tokenize(query)
    scored = [
        {**runbook, "score": len(query_tokens & _tokenize(runbook["content"]))}
        for runbook in _load_runbooks()
    ]
    scored.sort(key=lambda r: r["score"], reverse=True)
    return [
        {"runbook_id": r["runbook_id"], "title": r["title"], "score": r["score"]}
        for r in scored[:top_k]
    ]
