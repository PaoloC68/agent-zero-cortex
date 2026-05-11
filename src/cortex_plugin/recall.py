from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from cortex_plugin.config import (
    RECALL_QUERY_MIN_CHARS,
    RECALL_CANDIDATE_MULTIPLIER,
    RECALL_CANDIDATE_FLOOR,
    HTTP_TIMEOUT_SEC,
)

logger = logging.getLogger(__name__)


def should_skip_query(query: str) -> bool:
    return len(query.strip()) < RECALL_QUERY_MIN_CHARS


def compute_candidate_count(recall_limit: int) -> int:
    return max(recall_limit * RECALL_CANDIDATE_MULTIPLIER, RECALL_CANDIDATE_FLOOR)


def fence_rerank(
    results: list[dict[str, Any]],
    current_project: str | None,
    recall_limit: int,
) -> list[dict[str, Any]]:
    # Use composite_score (v1.1+ cognitive scoring) when available; fall back to RRF score for legacy.
    def key(r: dict[str, Any]) -> float:
        return r.get("composite_score") or r.get("score", 0.0)

    if current_project is None:
        return sorted(results, key=key, reverse=True)[:recall_limit]

    same = sorted(
        [r for r in results if r.get("source_project") == current_project],
        key=key,
        reverse=True,
    )
    cross = sorted(
        [r for r in results if r.get("source_project") != current_project],
        key=key,
        reverse=True,
    )

    slots_same = same[:recall_limit]
    slots_cross = cross[: max(recall_limit - len(slots_same), 0)]
    return slots_same + slots_cross


def format_memories_block(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for entry in results:
        content = entry.get("content", "")
        if not content or not content.strip():
            logger.warning("recall: skipping entry with empty/missing content: %r", entry)
            continue
        parts.append(content)

    if not parts:
        return ""

    return "## Memories\n\n" + "\n\n---\n\n".join(parts)


async def recall_and_format(
    query: str,
    session_id: str,
    current_project: str | None,
    http_post: Callable[..., Awaitable[Any]],
    *,
    url: str,
    api_key: str,
    recall_limit: int,
    threshold: float,
    legacy_rank: bool = False,
) -> str:
    if should_skip_query(query):
        return ""

    candidate_count = compute_candidate_count(recall_limit)
    params = {"legacy_rank": "true"} if legacy_rank else None

    try:
        results = await http_post(
            url,
            "/v1/recall",
            {"query": query, "session_id": session_id, "limit": candidate_count, "threshold": threshold},
            api_key,
            params=params,
            timeout_sec=HTTP_TIMEOUT_SEC,
        )
    except Exception as exc:
        logger.warning("recall: Cortex /v1/recall failed for session %s: %s", session_id, exc)
        return ""

    ranked = fence_rerank(results, current_project=current_project, recall_limit=recall_limit)
    return format_memories_block(ranked)
