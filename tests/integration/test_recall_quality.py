"""Integration tests — recall quality with fence + cross-project boost.

Run with:
    CORTEX_URL=http://192.168.1.12:8001 CORTEX_API_KEY=<key> \
        pytest -m integration tests/integration/test_recall_quality.py -v

Skipped automatically when CORTEX_URL or CORTEX_API_KEY is absent.
All memory content uses the [TEST-T19-RECALL] prefix to avoid polluting production data.
"""
from __future__ import annotations

import os
import uuid
from typing import Any

import httpx
import pytest

from cortex_plugin.http import cortex_post
from cortex_plugin.recall import fence_rerank, recall_and_format

_created_memory_ids: list[str] = []

CONTENT_PREFIX = "[TEST-T19-RECALL]"
PROJECT_PRIMARY = "test-cortex-primary"
PROJECT_OTHER = "test-cortex-other"


def _creds() -> tuple[str, str]:
    url = os.environ.get("CORTEX_URL", "")
    key = os.environ.get("CORTEX_API_KEY", "")
    if not url or not key:
        pytest.skip("CORTEX_URL and CORTEX_API_KEY must be set to run integration tests")
    return url.rstrip("/"), key


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _new_ext_id() -> str:
    return f"test-{uuid.uuid4()}"


async def _create_session(client: httpx.AsyncClient, url: str, api_key: str) -> str:
    body = {
        "external_session_id": _new_ext_id(),
        "source": "az",
        "initial_topic_slug": "cortex-test",
    }
    resp = await client.post(f"{url}/v1/sessions", json=body, headers=_headers(api_key))
    assert resp.status_code in (200, 201), (
        f"Session create failed: {resp.status_code} {resp.text}"
    )
    return resp.json()["id"]


async def _post_memory(
    client: httpx.AsyncClient,
    url: str,
    api_key: str,
    session_id: str,
    content: str,
    source_project: str | None = None,
    area: str = "fragments",
    importance: float = 0.5,
) -> str:
    body: dict[str, Any] = {
        "content": content,
        "kind": "fragment",
        "area": area,
        "source_session_id": session_id,
        "importance": importance,
    }
    if source_project is not None:
        body["source_project"] = source_project

    resp = await client.post(f"{url}/v1/memories", json=body, headers=_headers(api_key))
    assert resp.status_code in (200, 201), (
        f"Memory create failed: {resp.status_code} {resp.text}"
    )
    memory_id = resp.json()["id"]
    _created_memory_ids.append(memory_id)
    return memory_id


async def _setup_6_memories(
    client: httpx.AsyncClient,
    url: str,
    api_key: str,
) -> tuple[str, list[str], list[str], str]:
    """Per-test setup: session + 6 memories tagged with a unique run_tag for isolation."""
    run_tag = f"T19RUN{uuid.uuid4().hex[:8].upper()}"
    session_id = await _create_session(client, url, api_key)

    primary_ids: list[str] = []
    for i in range(1, 4):
        mid = await _post_memory(
            client,
            url,
            api_key,
            session_id,
            content=f"{CONTENT_PREFIX} {run_tag} primary memory {i} quantum computing neural networks",
            source_project=PROJECT_PRIMARY,
        )
        primary_ids.append(mid)

    other_ids: list[str] = []
    for i in range(1, 4):
        mid = await _post_memory(
            client,
            url,
            api_key,
            session_id,
            content=f"{CONTENT_PREFIX} {run_tag} other-project memory {i} quantum computing neural networks",
            source_project=PROJECT_OTHER,
        )
        other_ids.append(mid)

    return session_id, primary_ids, other_ids, run_tag


async def _recall_candidates(
    client: httpx.AsyncClient,
    url: str,
    api_key: str,
    query: str,
    limit: int = 30,
    threshold: float = 0.0,
) -> list[dict[str, Any]]:
    resp = await client.post(
        f"{url}/v1/recall",
        json={"query": query, "limit": limit, "threshold": threshold},
        headers=_headers(api_key),
    )
    assert resp.status_code == 200, f"Recall failed: {resp.status_code} {resp.text}"
    return resp.json()


def _forget_memory(client: httpx.Client, url: str, headers: dict[str, str], memory_id: str) -> None:
    try:
        client.post(
            f"{url}/v1/memories",
            json={"action": "forget", "memory_id": memory_id},
            headers=headers,
            timeout=10,
        )
    except Exception:
        pass


@pytest.fixture(autouse=True, scope="module")
def cleanup_all_test_memories() -> Any:
    """Forget all tracked IDs + sweep prefix stragglers; sync httpx avoids async scope issues."""
    yield
    url = os.environ.get("CORTEX_URL", "").rstrip("/")
    key = os.environ.get("CORTEX_API_KEY", "")
    if not url or not key:
        return
    headers = {"Authorization": f"Bearer {key}"}
    with httpx.Client(timeout=60) as client:
        for mid in list(_created_memory_ids):
            _forget_memory(client, url, headers, mid)
        for _ in range(10):
            try:
                resp = client.post(
                    f"{url}/v1/recall",
                    json={"query": CONTENT_PREFIX, "threshold": 0.0, "limit": 200},
                    headers=headers,
                    timeout=30,
                )
                if resp.status_code != 200:
                    break
                stragglers = [m for m in resp.json() if CONTENT_PREFIX in m.get("content", "")]
                if not stragglers:
                    break
                for m in stragglers:
                    _forget_memory(client, url, headers, m["id"])
            except Exception:
                break


@pytest.mark.integration
async def test_fence_dominates() -> None:
    url, key = _creds()
    async with httpx.AsyncClient(timeout=30) as client:
        _session_id, primary_ids, other_ids, run_tag = await _setup_6_memories(client, url, key)
        all_test_ids = set(primary_ids + other_ids)

        all_results = await _recall_candidates(client, url, key, run_tag)
        test_results = [r for r in all_results if r.get("id") in all_test_ids]

        assert len(test_results) == 6, (
            f"Expected all 6 test memories in recall results, got {len(test_results)}. "
            f"Found IDs: {[r['id'] for r in test_results]}"
        )

        fenced = fence_rerank(test_results, current_project=PROJECT_PRIMARY, recall_limit=4)
        assert len(fenced) == 4, f"Expected 4 fenced results, got {len(fenced)}"

        primary_in_top3 = [r for r in fenced[:3] if r.get("source_project") == PROJECT_PRIMARY]
        assert len(primary_in_top3) == 3, (
            f"Expected first 3 results to be primary-project; "
            f"got projects: {[r.get('source_project') for r in fenced[:3]]}"
        )


@pytest.mark.integration
async def test_projectless_by_score() -> None:
    url, key = _creds()
    async with httpx.AsyncClient(timeout=30) as client:
        _session_id, primary_ids, other_ids, run_tag = await _setup_6_memories(client, url, key)
        all_test_ids = set(primary_ids + other_ids)

        all_results = await _recall_candidates(client, url, key, run_tag)
        test_results = [r for r in all_results if r.get("id") in all_test_ids]

        assert len(test_results) == 6, f"Expected 6 test memories, got {len(test_results)}"

        ranked = fence_rerank(test_results, current_project=None, recall_limit=4)
        assert len(ranked) == 4, f"Expected 4 results, got {len(ranked)}"

        scores = [r.get("score", 0.0) for r in ranked]
        assert scores == sorted(scores, reverse=True), (
            f"Expected results in descending score order (no fence), got scores: {scores}"
        )


@pytest.mark.integration
async def test_no_match_returns_empty() -> None:
    url, key = _creds()
    async with httpx.AsyncClient(timeout=15) as client:
        results = await _recall_candidates(
            client,
            url,
            key,
            query="completely_unrelated_xyz123_T19",
            threshold=0.02,
        )
        test_results = [r for r in results if CONTENT_PREFIX in r.get("content", "")]
        assert len(test_results) == 0, (
            f"Expected 0 {CONTENT_PREFIX!r} results above threshold for unrelated query, "
            f"got {len(test_results)}: {[r['content'][:60] for r in test_results]}"
        )


@pytest.mark.integration
async def test_short_query_skips_http() -> None:
    url, key = _creds()
    call_count = 0

    async def counting_post(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        return await cortex_post(*args, **kwargs)

    result = await recall_and_format(
        query="x",
        session_id="test-skip-short-query-T19",
        current_project=None,
        http_post=counting_post,
        url=url,
        api_key=key,
        recall_limit=5,
        threshold=0.0,
    )

    assert result == "", f"Expected empty string for short query, got: {result!r}"
    assert call_count == 0, f"Expected 0 HTTP calls for short query, got: {call_count}"


@pytest.mark.integration
async def test_cross_project_bleed_observed() -> None:
    url, key = _creds()
    async with httpx.AsyncClient(timeout=30) as client:
        _session_id, primary_ids, other_ids, run_tag = await _setup_6_memories(client, url, key)
        all_test_ids = set(primary_ids + other_ids)

        all_results = await _recall_candidates(client, url, key, run_tag)
        test_results = [r for r in all_results if r.get("id") in all_test_ids]

        projects_seen = {r.get("source_project") for r in test_results}
        assert PROJECT_PRIMARY in projects_seen, (
            f"Expected {PROJECT_PRIMARY!r} in recall results, got: {projects_seen}"
        )
        assert PROJECT_OTHER in projects_seen, (
            f"Expected {PROJECT_OTHER!r} in recall results (cross-project bleed confirmed), "
            f"got: {projects_seen}"
        )
