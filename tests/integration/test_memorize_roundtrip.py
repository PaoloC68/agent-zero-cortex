"""Integration tests — memorize roundtrip (extraction → POST → readback).

Run with:
    CORTEX_URL=http://192.168.1.12:8001 CORTEX_API_KEY=<key> \
        pytest -m integration tests/integration/test_memorize_roundtrip.py -v

Skipped automatically when CORTEX_URL or CORTEX_API_KEY is absent.
All memories use the ``[TEST-T18-MEMORIZE]`` prefix to isolate test data.
"""
from __future__ import annotations

import hashlib
import os
import uuid

import httpx
import pytest

_created_ids: list[str] = []


def _creds() -> tuple[str, str]:
    """Return (base_url, api_key) or skip the calling test."""
    url = os.environ.get("CORTEX_URL", "")
    key = os.environ.get("CORTEX_API_KEY", "")
    if not url or not key:
        pytest.skip("CORTEX_URL and CORTEX_API_KEY must be set to run integration tests")
    return url.rstrip("/"), key


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _idempotency_key(session_id: str, area: str, content: str) -> str:
    message = f"{session_id}|{area}|{content}"
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


async def _post_memory(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    *,
    session_id: str,
    content: str,
    kind: str,
    area: str,
    importance: float,
) -> str:
    """POST a single memory and return its id."""
    idem_key = _idempotency_key(session_id, area, content)
    resp = await client.post(
        f"{base_url}/v1/memories",
        json={
            "content": content,
            "kind": kind,
            "area": area,
            "source_session_id": session_id,
            "importance": importance,
        },
        headers={**_headers(api_key), "Idempotency-Key": idem_key},
    )
    assert resp.status_code in (200, 201), (
        f"Memory POST failed: {resp.status_code} {resp.text}"
    )
    data = resp.json()
    assert "id" in data, f"Response missing 'id': {data}"
    return data["id"]


async def _recall(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    *,
    query: str,
    threshold: float = 0.0,
    limit: int = 100,
) -> list[dict]:
    resp = await client.post(
        f"{base_url}/v1/recall",
        json={"query": query, "threshold": threshold, "limit": limit},
        headers=_headers(api_key),
    )
    assert resp.status_code == 200, f"Recall failed: {resp.status_code} {resp.text}"
    return resp.json()


@pytest.fixture(scope="module", autouse=True)
async def cleanup_t18_memories():
    """Forget all tracked memories and verify zero residue after tests complete."""
    yield  # all tests run first; finalizer runs regardless of pass/fail

    base_url = os.environ.get("CORTEX_URL", "").rstrip("/")
    api_key = os.environ.get("CORTEX_API_KEY", "")
    if not base_url or not api_key or not _created_ids:
        return

    async with httpx.AsyncClient(timeout=15) as client:
        headers = _headers(api_key)
        for mem_id in _created_ids:
            try:
                await client.post(
                    f"{base_url}/v1/memories",
                    json={"action": "forget", "memory_id": mem_id},
                    headers=headers,
                )
            except Exception:
                pass  # best-effort: already-forgotten memory returns 404

        resp = await client.post(
            f"{base_url}/v1/recall",
            json={"query": "[TEST-T18-MEMORIZE]", "threshold": 0.0, "limit": 100},
            headers=headers,
        )
        if resp.status_code == 200:
            results = resp.json()
            residue = [
                r for r in results
                if "[TEST-T18-MEMORIZE]" in r.get("content", "")
            ]
            assert len(residue) == 0, (
                f"Cleanup incomplete: {len(residue)} T18 memories remain: "
                + str([r.get("id") for r in residue])
            )


@pytest.mark.integration
async def test_memorize_roundtrip():
    """Create session, POST 2 fragments + 1 solution (3 POSTs), verify recall readback."""
    base_url, api_key = _creds()
    session_id = f"test-{uuid.uuid4()}"

    frag1 = "[TEST-T18-MEMORIZE] fragment: httpx supports async context managers"
    frag2 = "[TEST-T18-MEMORIZE] fragment: pytest asyncio_mode auto removes mark requirement"
    sol = "[TEST-T18-MEMORIZE] solution: use idempotency keys to prevent duplicate memories"

    async with httpx.AsyncClient(timeout=15) as client:
        id1 = await _post_memory(
            client, base_url, api_key,
            session_id=session_id, content=frag1, kind="fragment",
            area="fragments", importance=0.5,
        )
        _created_ids.append(id1)

        id2 = await _post_memory(
            client, base_url, api_key,
            session_id=session_id, content=frag2, kind="fragment",
            area="fragments", importance=0.5,
        )
        _created_ids.append(id2)

        id3 = await _post_memory(
            client, base_url, api_key,
            session_id=session_id, content=sol, kind="solution-step",
            area="solutions", importance=0.7,
        )
        _created_ids.append(id3)

        results = await _recall(client, base_url, api_key, query="[TEST-T18-MEMORIZE]")

    t18 = [r for r in results if "[TEST-T18-MEMORIZE]" in r.get("content", "")]
    assert len(t18) >= 1, (
        f"Expected >=1 recalled memory after 3 POSTs; got 0. All results: {results[:3]}"
    )
    returned_ids = {r["id"] for r in t18}
    assert id1 in returned_ids or id2 in returned_ids or id3 in returned_ids, (
        f"None of the 3 posted IDs appeared in recall. Posted: {[id1, id2, id3]}, "
        f"Recalled: {list(returned_ids)}"
    )


@pytest.mark.integration
async def test_memorize_idempotent():
    """Same idempotency key -> server returns the same memory id; count unchanged."""
    base_url, api_key = _creds()
    session_id = f"test-{uuid.uuid4()}"
    content = "[TEST-T18-MEMORIZE] idempotency check: this content must never be stored twice"

    async with httpx.AsyncClient(timeout=15) as client:
        id1 = await _post_memory(
            client, base_url, api_key,
            session_id=session_id, content=content, kind="fragment",
            area="fragments", importance=0.5,
        )
        _created_ids.append(id1)

        id2 = await _post_memory(
            client, base_url, api_key,
            session_id=session_id, content=content, kind="fragment",
            area="fragments", importance=0.5,
        )

    assert id1 == id2, f"Idempotency violated: first={id1!r}, second={id2!r}"


@pytest.mark.integration
async def test_forget_removes_memory():
    """POST forget action removes memory from subsequent recall results."""
    base_url, api_key = _creds()
    session_id = f"test-{uuid.uuid4()}"
    content = "[TEST-T18-MEMORIZE] forget-target: this memory must be gone after forget"

    async with httpx.AsyncClient(timeout=15) as client:
        mem_id = await _post_memory(
            client, base_url, api_key,
            session_id=session_id, content=content, kind="fragment",
            area="fragments", importance=0.5,
        )
        _created_ids.append(mem_id)

        forget_resp = await client.post(
            f"{base_url}/v1/memories",
            json={"action": "forget", "memory_id": mem_id},
            headers=_headers(api_key),
        )
        assert forget_resp.status_code in (200, 201, 204), (
            f"Forget action failed: {forget_resp.status_code} {forget_resp.text}"
        )

        results = await _recall(client, base_url, api_key, query=content)

    active_ids = {r["id"] for r in results}
    assert mem_id not in active_ids, (
        f"Memory {mem_id} still appears in recall after forget action"
    )


@pytest.mark.integration
async def test_timeout_propagates():
    """POST with 0.1 s timeout raises httpx.TimeoutException (embeddings take > 0.1 s)."""
    base_url, api_key = _creds()
    session_id = f"test-{uuid.uuid4()}"
    probe_content = "[TEST-T18-MEMORIZE] timeout-probe: expect no response"

    with pytest.raises(httpx.TimeoutException):
        async with httpx.AsyncClient(timeout=0.1) as client:
            await client.post(
                f"{base_url}/v1/memories",
                json={
                    "content": probe_content,
                    "kind": "fragment",
                    "area": "fragments",
                    "source_session_id": session_id,
                    "importance": 0.5,
                },
                headers={
                    **_headers(api_key),
                    "Idempotency-Key": _idempotency_key(session_id, "fragments", probe_content),
                },
            )

    async with httpx.AsyncClient(timeout=15) as client:
        results = await _recall(client, base_url, api_key, query=probe_content)
    for r in results:
        if r.get("content") == probe_content and r.get("id") not in _created_ids:
            _created_ids.append(r["id"])
