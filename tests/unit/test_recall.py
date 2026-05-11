"""Tests for cortex_plugin.recall module — fence rerank + ## Memories block formatter.

TDD: These tests are written FIRST (RED phase). They drive the implementation.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock


# ---------------------------------------------------------------------------
# should_skip_query
# ---------------------------------------------------------------------------


def test_should_skip_empty_query():
    """Empty string is below RECALL_QUERY_MIN_CHARS → skip."""
    from cortex_plugin.recall import should_skip_query

    assert should_skip_query("") is True


def test_should_skip_whitespace_only():
    """Whitespace-only string strips to zero chars → skip."""
    from cortex_plugin.recall import should_skip_query

    assert should_skip_query("   ") is True


def test_should_skip_two_chars():
    """Two-character query (stripped) is below threshold → skip."""
    from cortex_plugin.recall import should_skip_query

    assert should_skip_query("ok") is True


def test_should_not_skip_exactly_min_chars():
    """Exactly RECALL_QUERY_MIN_CHARS (3) → do NOT skip."""
    from cortex_plugin.recall import should_skip_query

    assert should_skip_query("abc") is False


def test_should_not_skip_long_query():
    """Normal query → do NOT skip."""
    from cortex_plugin.recall import should_skip_query

    assert should_skip_query("how do I deploy to Proxmox") is False


# ---------------------------------------------------------------------------
# compute_candidate_count
# ---------------------------------------------------------------------------


def test_compute_candidate_count_small_limit_uses_floor():
    """limit=5 → 5*5=25, but floor=30 → returns 30."""
    from cortex_plugin.recall import compute_candidate_count

    assert compute_candidate_count(5) == 30


def test_compute_candidate_count_large_limit_uses_multiplier():
    """limit=10 → 10*5=50 > floor=30 → returns 50."""
    from cortex_plugin.recall import compute_candidate_count

    assert compute_candidate_count(10) == 50


def test_compute_candidate_count_mid_limit():
    """limit=7 → 7*5=35 > floor=30 → returns 35."""
    from cortex_plugin.recall import compute_candidate_count

    assert compute_candidate_count(7) == 35


# ---------------------------------------------------------------------------
# fence_rerank
# ---------------------------------------------------------------------------


def _make_result(content: str, score: float, project: str | None) -> dict:
    return {"id": f"id-{content}", "content": content, "score": score, "source_project": project, "matched_via": "vector"}


def test_fence_rerank_same_project_first():
    """3 same-project + 5 cross-project, limit=5 → 3 same first, then top-2 cross."""
    from cortex_plugin.recall import fence_rerank

    same = [
        _make_result("s1", 0.04, "homelab"),
        _make_result("s2", 0.03, "homelab"),
        _make_result("s3", 0.02, "homelab"),
    ]
    cross = [
        _make_result("c1", 0.05, "other"),
        _make_result("c2", 0.045, "other"),
        _make_result("c3", 0.04, "other2"),
        _make_result("c4", 0.03, "other2"),
        _make_result("c5", 0.01, "other"),
    ]
    results = same + cross
    ranked = fence_rerank(results, current_project="homelab", recall_limit=5)

    assert len(ranked) == 5
    # First 3 slots: same-project (in score order)
    assert ranked[0]["content"] == "s1"
    assert ranked[1]["content"] == "s2"
    assert ranked[2]["content"] == "s3"
    # Last 2: top cross-project by score
    assert ranked[3]["content"] == "c1"
    assert ranked[4]["content"] == "c2"


def test_fence_rerank_no_project():
    """current_project=None → return top recall_limit in raw score order (no partition)."""
    from cortex_plugin.recall import fence_rerank

    results = [
        _make_result("a", 0.9, "proj-a"),
        _make_result("b", 0.8, "proj-b"),
        _make_result("c", 0.7, "proj-c"),
        _make_result("d", 0.6, "proj-d"),
    ]
    ranked = fence_rerank(results, current_project=None, recall_limit=3)

    assert len(ranked) == 3
    assert ranked[0]["content"] == "a"
    assert ranked[1]["content"] == "b"
    assert ranked[2]["content"] == "c"


def test_fence_dominates_score():
    """Adversarial: same-project score 0.03 BEATS cross-project score 0.10.

    Fence wins regardless of score difference.
    """
    from cortex_plugin.recall import fence_rerank

    results = [
        _make_result("A", 0.10, "other"),
        _make_result("B", 0.03, "homelab"),
    ]
    ranked = fence_rerank(results, current_project="homelab", recall_limit=2)

    assert len(ranked) == 2
    assert ranked[0]["content"] == "B"  # same-project FIRST despite lower score
    assert ranked[1]["content"] == "A"


def test_fence_rerank_rrf_scores():
    """Works correctly with RRF-style scores in 0.01–0.05 range."""
    from cortex_plugin.recall import fence_rerank

    results = [
        _make_result("rrf-same-1", 0.033, "homelab"),
        _make_result("rrf-same-2", 0.016, "homelab"),
        _make_result("rrf-cross-1", 0.049, "other"),
        _make_result("rrf-cross-2", 0.041, "other"),
    ]
    ranked = fence_rerank(results, current_project="homelab", recall_limit=3)

    assert len(ranked) == 3
    # Same-project fills first slots
    assert ranked[0]["content"] == "rrf-same-1"
    assert ranked[1]["content"] == "rrf-same-2"
    # Cross-project fills last slot (top score from cross)
    assert ranked[2]["content"] == "rrf-cross-1"


def test_fence_rerank_composite_scores():
    """Works correctly with composite-style scores in 0.10–0.95 range."""
    from cortex_plugin.recall import fence_rerank

    results = [
        _make_result("comp-same", 0.72, "homelab"),
        _make_result("comp-cross-hi", 0.95, "other"),
        _make_result("comp-cross-lo", 0.85, "other"),
    ]
    ranked = fence_rerank(results, current_project="homelab", recall_limit=3)

    assert ranked[0]["content"] == "comp-same"   # fence: same first
    assert ranked[1]["content"] == "comp-cross-hi"  # then cross in score order
    assert ranked[2]["content"] == "comp-cross-lo"


def test_fence_rerank_with_composite_score_field():
    """When composite_score field is present, use it for sorting instead of score."""
    from cortex_plugin.recall import fence_rerank

    # Results with both score (RRF) and composite_score (v1.1 cognitive)
    results = [
        {
            "id": "id-1",
            "content": "same-low-rrf-high-composite",
            "score": 0.01,  # Low RRF score
            "composite_score": 0.85,  # High composite score
            "source_project": "homelab",
            "matched_via": "vector",
        },
        {
            "id": "id-2",
            "content": "same-high-rrf-low-composite",
            "score": 0.04,  # High RRF score
            "composite_score": 0.30,  # Low composite score
            "source_project": "homelab",
            "matched_via": "vector",
        },
        {
            "id": "id-3",
            "content": "cross-high-composite",
            "score": 0.02,
            "composite_score": 0.90,
            "source_project": "other",
            "matched_via": "vector",
        },
    ]
    ranked = fence_rerank(results, current_project="homelab", recall_limit=3)

    # Same-project results should be sorted by composite_score (not score)
    assert ranked[0]["content"] == "same-low-rrf-high-composite"  # composite 0.85 > 0.30
    assert ranked[1]["content"] == "same-high-rrf-low-composite"
    assert ranked[2]["content"] == "cross-high-composite"


def test_fence_rerank_fallback_to_score_without_composite():
    """When composite_score is missing, fall back to score field."""
    from cortex_plugin.recall import fence_rerank

    # Results without composite_score (MVP or legacy)
    results = [
        {
            "id": "id-1",
            "content": "same-high-score",
            "score": 0.04,
            "source_project": "homelab",
            "matched_via": "vector",
        },
        {
            "id": "id-2",
            "content": "same-low-score",
            "score": 0.01,
            "source_project": "homelab",
            "matched_via": "vector",
        },
        {
            "id": "id-3",
            "content": "cross-high-score",
            "score": 0.05,
            "source_project": "other",
            "matched_via": "vector",
        },
    ]
    ranked = fence_rerank(results, current_project="homelab", recall_limit=3)

    # Same-project sorted by score (no composite_score available)
    assert ranked[0]["content"] == "same-high-score"  # 0.04 > 0.01
    assert ranked[1]["content"] == "same-low-score"
    assert ranked[2]["content"] == "cross-high-score"


def test_fence_rerank_empty_same_project():
    """No same-project results → return top recall_limit cross-project in score order."""
    from cortex_plugin.recall import fence_rerank

    results = [
        _make_result("c1", 0.9, "other"),
        _make_result("c2", 0.8, "other"),
        _make_result("c3", 0.7, "other"),
    ]
    ranked = fence_rerank(results, current_project="homelab", recall_limit=2)

    assert len(ranked) == 2
    assert ranked[0]["content"] == "c1"
    assert ranked[1]["content"] == "c2"


def test_fence_rerank_empty_cross_project():
    """No cross-project results → return same-project in score order."""
    from cortex_plugin.recall import fence_rerank

    results = [
        _make_result("s1", 0.04, "homelab"),
        _make_result("s2", 0.02, "homelab"),
    ]
    ranked = fence_rerank(results, current_project="homelab", recall_limit=5)

    assert len(ranked) == 2
    assert ranked[0]["content"] == "s1"
    assert ranked[1]["content"] == "s2"


# ---------------------------------------------------------------------------
# format_memories_block
# ---------------------------------------------------------------------------


def test_format_block_exact():
    """Exact byte format: ## Memories\\n\\n<c1>\\n\\n---\\n\\n<c2> (no trailing separator)."""
    from cortex_plugin.recall import format_memories_block

    results = [{"content": "foo"}, {"content": "bar"}]
    output = format_memories_block(results)
    assert output == "## Memories\n\nfoo\n\n---\n\nbar"


def test_format_block_empty_list():
    """Empty result list → empty string."""
    from cortex_plugin.recall import format_memories_block

    assert format_memories_block([]) == ""


def test_format_block_skips_empty_content(caplog):
    """Entries with empty or missing content are skipped (logs warning)."""
    import logging
    from cortex_plugin.recall import format_memories_block

    results = [
        {"content": "valid"},
        {"content": ""},          # empty — skip
        {"other": "no content"},  # missing key — skip
        {"content": "  "},        # whitespace-only — skip
        {"content": "also valid"},
    ]
    with caplog.at_level(logging.WARNING):
        output = format_memories_block(results)

    assert output == "## Memories\n\nvalid\n\n---\n\nalso valid"
    assert any("warning" in r.levelname.lower() or "warn" in r.levelname.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# recall_and_format (async — integration of the pipeline)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_and_format_skip_short_query():
    """Short queries (<3 chars) return '' without calling http_post."""
    from cortex_plugin.recall import recall_and_format

    mock_post = AsyncMock()
    kwargs = dict(url="http://x", api_key="k", recall_limit=5, threshold=0.02)

    result_empty = await recall_and_format("", "ses-1", "proj", mock_post, **kwargs)
    assert result_empty == ""
    mock_post.assert_not_called()

    result_short = await recall_and_format("ok", "ses-1", "proj", mock_post, **kwargs)
    assert result_short == ""
    mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_recall_and_format_orchestrates_full_flow():
    """Full pipeline: skip-check → POST /v1/recall → fence rerank → format."""
    from cortex_plugin.recall import recall_and_format

    canned_results = [
        {"id": "1", "content": "memory one", "score": 0.04, "source_project": "homelab", "matched_via": "vector"},
        {"id": "2", "content": "memory two", "score": 0.03, "source_project": "homelab", "matched_via": "bm25"},
        {"id": "3", "content": "cross mem", "score": 0.09, "source_project": "other", "matched_via": "vector"},
    ]
    mock_post = AsyncMock(return_value=canned_results)

    output = await recall_and_format(
        "tell me about homelab",
        "ses-1",
        "homelab",
        mock_post,
        url="http://cortex:8001",
        api_key="test-key",
        recall_limit=5,
        threshold=0.02,
    )

    # http_post must have been called once
    mock_post.assert_called_once()

    # Fence rerank: homelab results first, then cross-project
    # format: ## Memories\n\n<homelab1>\n\n---\n\n<homelab2>\n\n---\n\n<cross>
    assert output.startswith("## Memories")
    assert "memory one" in output
    assert "memory two" in output
    assert "cross mem" in output
    # Same-project ordering (homelab first)
    assert output.index("memory one") < output.index("cross mem")


@pytest.mark.asyncio
async def test_recall_and_format_legacy_rank_true():
    """When legacy_rank=True, http_post receives params={'legacy_rank': 'true'}."""
    from cortex_plugin.recall import recall_and_format

    mock_post = AsyncMock(return_value=[])

    await recall_and_format(
        "what is the setup process",
        "ses-1",
        "homelab",
        mock_post,
        url="http://cortex:8001",
        api_key="test-key",
        recall_limit=5,
        threshold=0.02,
        legacy_rank=True,
    )

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args.kwargs
    assert call_kwargs.get("params") == {"legacy_rank": "true"}


@pytest.mark.asyncio
async def test_recall_and_format_legacy_rank_false():
    """When legacy_rank=False (default), http_post receives params=None."""
    from cortex_plugin.recall import recall_and_format

    mock_post = AsyncMock(return_value=[])

    await recall_and_format(
        "what is the setup process",
        "ses-1",
        "homelab",
        mock_post,
        url="http://cortex:8001",
        api_key="test-key",
        recall_limit=5,
        threshold=0.02,
        legacy_rank=False,
    )

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args.kwargs
    assert call_kwargs.get("params") is None


@pytest.mark.asyncio
async def test_recall_and_format_cortex_error():
    """On http_post exception, returns '' and does NOT propagate."""
    from cortex_plugin.recall import recall_and_format

    mock_post = AsyncMock(side_effect=Exception("connection refused"))

    result = await recall_and_format(
        "some valid query here",
        "ses-1",
        "homelab",
        mock_post,
        url="http://cortex:8001",
        api_key="test-key",
        recall_limit=5,
        threshold=0.02,
    )

    assert result == ""
