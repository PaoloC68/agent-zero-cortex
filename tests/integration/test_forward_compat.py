"""Integration tests — forward-compatibility with Cortex v1.1+ (legacy_rank, threshold, Reflector tolerance).

Run with:
    CORTEX_URL=http://192.168.1.12:8001 CORTEX_API_KEY=<key> \
        pytest -m integration tests/integration/test_forward_compat.py -v

Skipped automatically when CORTEX_URL or CORTEX_API_KEY is absent.
All memory content uses the [TEST-T19.5-FWDCOMPAT] prefix to avoid polluting production data.
"""
from __future__ import annotations

import os
import uuid
from typing import Any

import httpx
import pytest

from cortex_plugin.http import cortex_post
from cortex_plugin.recall import recall_and_format

CONTENT_PREFIX = "[TEST-T19.5-FWDCOMPAT]"

_created_memory_ids: list[str] = []


def _creds() -> tuple[str, str]:
    url = os.environ.get("CORTEX_URL", "")
    key = os.environ.get("CORTEX_API_KEY", "")
    if not url or not key:
        pytest.skip("CORTEX_URL and CORTEX_API_KEY must be set to run integration tests")
    return url.rstrip("/"), key


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _new_session_id() -> str:
    return f"test-fwdcompat-{uuid.uuid4()}"


async def _post_memory(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    session_id: str,
    content: str,
    idempotency_key: str | None = None,
    area: str = "fragments",
    importance: float = 0.5,
) -> str:
    headers = _headers(api_key)
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    resp = await client.post(
        f"{base_url}/v1/memories",
        json={
            "content": content,
            "kind": "fragment",
            "area": area,
            "source_session_id": session_id,
            "importance": importance,
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), f"Memory POST failed: {resp.status_code} {resp.text}"
    memory_id = resp.json()["id"]
    _created_memory_ids.append(memory_id)
    return memory_id


def _forget_memory_sync(
    client: httpx.Client,
    base_url: str,
    api_key: str,
    memory_id: str,
) -> None:
    try:
        client.post(
            f"{base_url}/v1/memories",
            json={"action": "forget", "memory_id": memory_id},
            headers=_headers(api_key),
            timeout=10,
        )
    except Exception:
        pass


@pytest.fixture(autouse=True, scope="module")
def cleanup_fwdcompat_memories() -> Any:
    """Forget all tracked IDs + sweep prefix stragglers; sync httpx avoids async scope issues."""
    yield
    url = os.environ.get("CORTEX_URL", "").rstrip("/")
    key = os.environ.get("CORTEX_API_KEY", "")
    if not url or not key:
        return
    headers = {"Authorization": f"Bearer {key}"}
    with httpx.Client(timeout=60) as client:
        for mid in list(_created_memory_ids):
            _forget_memory_sync(client, url, key, mid)
        # Sweep for stragglers up to 10 times (Cortex recall index may lag slightly)
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
                    _forget_memory_sync(client, url, key, m["id"])
            except Exception:
                break


@pytest.mark.integration
async def test_legacy_rank_param_sent() -> None:
    """Test 1: legacy_rank=True causes params={'legacy_rank': 'true'} in outgoing HTTP call.

    Cortex MVP ignores the parameter — assertion is on the REQUEST shape, not response content.
    Response is allowed to be either RRF or default-RRF output.
    """
    url, key = _creds()
    session_id = _new_session_id()

    # Seed a memory so recall has something to return (avoids empty-result ambiguity)
    run_tag = f"T195LR{uuid.uuid4().hex[:8].upper()}"
    async with httpx.AsyncClient(timeout=15) as client:
        await _post_memory(
            client, url, key, session_id,
            content=f"{CONTENT_PREFIX} {run_tag} legacy_rank parameter test seed memory",
        )

    captured_params: list[dict[str, str] | None] = []

    async def capturing_post(
        base_url: str,
        path: str,
        body: dict[str, Any],
        api_key: str,
        *,
        params: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Any:
        captured_params.append(params)
        return await cortex_post(base_url, path, body, api_key, params=params, **kwargs)

    result = await recall_and_format(
        query=f"{run_tag} legacy_rank",
        session_id=session_id,
        current_project=None,
        http_post=capturing_post,
        url=url,
        api_key=key,
        recall_limit=5,
        threshold=0.0,
        legacy_rank=True,
    )

    assert len(captured_params) == 1, f"Expected exactly 1 HTTP call, got {len(captured_params)}"
    assert captured_params[0] is not None, (
        "Expected params dict when legacy_rank=True, got None"
    )
    assert captured_params[0].get("legacy_rank") == "true", (
        f"Expected params['legacy_rank'] == 'true', got: {captured_params[0]}"
    )
    # Response tolerance: MVP may return same results as without the param — valid string expected
    assert isinstance(result, str), f"Expected str result, got: {type(result)}"


@pytest.mark.integration
async def test_legacy_rank_false_sends_no_params() -> None:
    """Test 1b: legacy_rank=False means params=None (no query param) in outgoing HTTP call."""
    url, key = _creds()
    session_id = _new_session_id()

    captured_params: list[dict[str, str] | None] = []

    async def capturing_post(
        base_url: str,
        path: str,
        body: dict[str, Any],
        api_key: str,
        *,
        params: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Any:
        captured_params.append(params)
        return await cortex_post(base_url, path, body, api_key, params=params, **kwargs)

    await recall_and_format(
        query=f"{CONTENT_PREFIX} T1b no-legacy-rank probe",
        session_id=session_id,
        current_project=None,
        http_post=capturing_post,
        url=url,
        api_key=key,
        recall_limit=5,
        threshold=0.0,
        legacy_rank=False,
    )

    assert len(captured_params) == 1, f"Expected exactly 1 HTTP call, got {len(captured_params)}"
    assert captured_params[0] is None, (
        f"Expected params=None when legacy_rank=False, got: {captured_params[0]}"
    )


@pytest.mark.integration
async def test_threshold_filters_results() -> None:
    """Test 2: High threshold (0.5) returns zero results; threshold=0.0 returns >=1 for known content.

    RRF k=60 hardcoded — max achievable RRF score ~0.05. Any threshold above that filters everything.
    """
    url, key = _creds()
    session_id = _new_session_id()

    run_tag = f"T195THR{uuid.uuid4().hex[:8].upper()}"
    async with httpx.AsyncClient(timeout=15) as client:
        await _post_memory(
            client, url, key, session_id,
            content=f"{CONTENT_PREFIX} {run_tag} threshold filtering test memory content",
        )

    # threshold=0.5 is far above RRF max (~0.05) — all results filtered out
    result_high = await recall_and_format(
        query=run_tag,
        session_id=session_id,
        current_project=None,
        http_post=cortex_post,
        url=url,
        api_key=key,
        recall_limit=5,
        threshold=0.5,
    )
    assert result_high == "", (
        f"Expected empty string with threshold=0.5 (above RRF max ~0.05), got: {result_high!r}"
    )

    # threshold=0.0 — no filtering; BM25 exact-match on run_tag guarantees >=1 result
    result_low = await recall_and_format(
        query=run_tag,
        session_id=session_id,
        current_project=None,
        http_post=cortex_post,
        url=url,
        api_key=key,
        recall_limit=5,
        threshold=0.0,
    )
    assert isinstance(result_low, str), f"Expected str, got {type(result_low)}"
    assert result_low != "", (
        f"Expected >=1 result with threshold=0.0 for known-content query '{run_tag}', got empty"
    )
    assert run_tag in result_low, (
        f"Expected run_tag '{run_tag}' in result body, got: {result_low[:300]}"
    )


@pytest.mark.integration
async def test_reflector_mutation_tolerance() -> None:
    """Test 3: Two near-duplicate memories recalled without corruption or duplication.

    In Cortex MVP: Reflector runs nightly; both memories returned independently.
    In Cortex v1.1+: Reflector may merge them into a single consolidated entry.
    Both regimes are valid — assertion checks content integrity, not exact count.
    """
    url, key = _creds()
    session_id = _new_session_id()
    run_tag = f"T195REF{uuid.uuid4().hex[:8].upper()}"

    content_1 = f"{CONTENT_PREFIX} {run_tag} User likes coffee"
    content_2 = f"{CONTENT_PREFIX} {run_tag} User prefers coffee"
    k1 = f"fwdcompat-k1-{run_tag}"
    k2 = f"fwdcompat-k2-{run_tag}"

    async with httpx.AsyncClient(timeout=15) as client:
        m1 = await _post_memory(client, url, key, session_id, content_1, idempotency_key=k1)
        m2 = await _post_memory(client, url, key, session_id, content_2, idempotency_key=k2)

    assert m1 != m2, (
        f"Expected distinct memory IDs for K1 vs K2 (different idempotency keys), got same: {m1}"
    )

    result = await recall_and_format(
        query=f"{run_tag} coffee preference",
        session_id=session_id,
        current_project=None,
        http_post=cortex_post,
        url=url,
        api_key=key,
        recall_limit=10,
        threshold=0.0,
    )

    assert isinstance(result, str), f"Expected str, got {type(result)}"

    if result and run_tag in result:
        # run_tag present — proves relevance, not a spurious match
        # Count occurrences of run_tag — MVP: at most 2 (one per memory); v1.1+: 1 (merged)
        # 3+ would indicate a duplication bug on the server
        occurrences = result.count(run_tag)
        assert occurrences <= 2, (
            f"Expected ≤2 occurrences of run_tag (no duplication), "
            f"got {occurrences}: {result[:500]}"
        )
        # Each line in result must be one of: original content_1, original content_2,
        # a merged variant (contains both "likes" or "prefers" in some combination),
        # or empty (separator lines). No garbage content expected.
        lines_with_content = [
            line.strip()
            for line in result.splitlines()
            if line.strip() and not line.strip().startswith("#") and line.strip() != "---"
        ]
        for line in lines_with_content:
            if run_tag in line:
                assert any(kw in line.lower() for kw in ("coffee", "likes", "prefers", "user")), (
                    f"Line with run_tag has unexpected content (not coffee-related): {line!r}"
                )


@pytest.mark.integration
async def test_config_matrix_smoke() -> None:
    """Test 4: Config combos (threshold, legacy_rank) all return valid string shape.

    Configs tested:
      - (threshold=0.02, legacy_rank=False)  — near floor, may return results
      - (threshold=0.30, legacy_rank=True)   — above RRF max, empty expected; legacy_rank ignored by MVP
      - (threshold=0.30, legacy_rank=False)  — above RRF max, empty expected

    All must return str (including empty string) — never raise, never return None.
    """
    url, key = _creds()
    session_id = _new_session_id()
    run_tag = f"T195MAT{uuid.uuid4().hex[:8].upper()}"

    async with httpx.AsyncClient(timeout=15) as client:
        await _post_memory(
            client, url, key, session_id,
            content=f"{CONTENT_PREFIX} {run_tag} config matrix smoke test content",
        )

    configs: list[dict[str, Any]] = [
        {"threshold": 0.02, "legacy_rank": False},
        {"threshold": 0.30, "legacy_rank": True},
        {"threshold": 0.30, "legacy_rank": False},
    ]

    for cfg in configs:
        result = await recall_and_format(
            query=run_tag,
            session_id=session_id,
            current_project=None,
            http_post=cortex_post,
            url=url,
            api_key=key,
            recall_limit=5,
            threshold=cfg["threshold"],
            legacy_rank=cfg["legacy_rank"],
        )
        assert isinstance(result, str), (
            f"Config {cfg}: expected str, got {type(result)}: {result!r}"
        )
        # threshold=0.30 > RRF max, result must be empty
        if cfg["threshold"] >= 0.30:
            assert result == "", (
                f"Config {cfg}: expected empty string (threshold {cfg['threshold']} > RRF max ~0.05), "
                f"got: {result!r}"
            )
