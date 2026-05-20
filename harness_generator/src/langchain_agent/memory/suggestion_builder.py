"""Build structured suggestions from GBrain query results."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Parse a value to float, returning default on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


@dataclass
class MemoryHit:
    slug: str
    title: str
    score: float
    snippet: str
    page_type: str = ""


@dataclass
class Suggestion:
    node: str  # plan | crash-triage | crash-analysis | coverage-analysis
    summary: str
    hits: list[MemoryHit] = field(default_factory=list)
    relevance: float = 0.0  # 0.0 - 1.0

    def is_actionable(self, threshold: float = 0.5) -> bool:
        return self.relevance >= threshold and len(self.hits) > 0


def build_suggestion(
    node: str,
    _query: str,
    raw_results: list[dict[str, Any]] | None,
    _context: dict[str, Any] | None = None,
) -> Suggestion:
    """Convert raw GBrain query results into a structured Suggestion.

    Args:
        node: workflow node name (plan, crash-triage, crash-analysis, coverage-analysis)
        _query: the original query string sent to GBrain (reserved for future use)
        raw_results: list of result dicts from GBrain search/query MCP tool
        _context: node-specific context dict (reserved for future use)
    """
    if not raw_results:
        return Suggestion(node=node, summary="", hits=[], relevance=0.0)

    hits: list[MemoryHit] = []
    for r in raw_results[:5]:
        hits.append(MemoryHit(
            slug=r.get("slug", ""),
            title=r.get("title", r.get("slug", "")),
            score=_safe_float(r.get("score"), 0.0),
            snippet=str(r.get("snippet", r.get("chunk_text", "")))[:300],
            page_type=r.get("type", ""),
        ))

    if hits:
        top_score = hits[0].score
        hit_count_factor = min(len(hits) / 3.0, 1.0)
        relevance = round(min(top_score * 0.7 + hit_count_factor * 0.3, 1.0), 2)
    else:
        relevance = 0.0

    summary = _build_summary(node, hits)
    return Suggestion(node=node, summary=summary, hits=hits, relevance=relevance)


def _build_summary(node: str, hits: list[MemoryHit]) -> str:
    if not hits:
        return f"[{node}] GBrain 中未找到相关历史经验。"

    lines = [f"[{node}] GBrain 找到 {len(hits)} 条相关记录："]
    for i, h in enumerate(hits, 1):
        lines.append(f"  {i}. {h.title} (score: {h.score:.2f}) — {h.snippet[:120]}")
    return "\n".join(lines)
