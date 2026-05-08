"""Integration tests — session lifecycle (init, topic-lock, project-less).

Run with:
    CORTEX_URL=http://192.168.1.12:8001 CORTEX_API_KEY=<key> pytest -m integration tests/integration/test_session_lifecycle.py -v

Skipped automatically when CORTEX_URL or CORTEX_API_KEY is absent.
All session IDs use the ``test-{uuid4}`` prefix to avoid polluting production data.
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest


def _creds() -> tuple[str, str]:
    """Return (base_url, api_key) or skip the calling test."""
    url = os.environ.get("CORTEX_URL", "")
    key = os.environ.get("CORTEX_API_KEY", "")
    if not url or not key:
        pytest.skip("CORTEX_URL and CORTEX_API_KEY must be set to run integration tests")
    return url.rstrip("/"), key


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _new_ext_id() -> str:
    return f"test-{uuid.uuid4()}"


@pytest.mark.integration
async def test_session_create_happy_path():
    """POST /v1/sessions → 200/201 with valid string id."""
    url, key = _creds()
    body = {
        "external_session_id": _new_ext_id(),
        "source": "az",
        "initial_topic_slug": "cortex-test",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{url}/v1/sessions", json=body, headers=_headers(key))

    assert resp.status_code in (200, 201), (
        f"Expected 200/201, got {resp.status_code}: {resp.text}"
    )
    data = resp.json()
    assert "id" in data, f"Response missing 'id': {data}"
    assert isinstance(data["id"], str) and len(data["id"]) > 0


@pytest.mark.integration
async def test_session_idempotent_recreate():
    """Posting same external_session_id+source twice returns the same Cortex id (ON CONFLICT)."""
    url, key = _creds()
    ext_id = _new_ext_id()
    body = {
        "external_session_id": ext_id,
        "source": "az",
        "initial_topic_slug": "cortex-test",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r1 = await client.post(f"{url}/v1/sessions", json=body, headers=_headers(key))
        r2 = await client.post(f"{url}/v1/sessions", json=body, headers=_headers(key))

    assert r1.status_code in (200, 201), f"First call: {r1.status_code} {r1.text}"
    assert r2.status_code in (200, 201), f"Second call: {r2.status_code} {r2.text}"
    id1 = r1.json()["id"]
    id2 = r2.json()["id"]
    assert id1 == id2, f"Idempotency violated: first={id1!r}, second={id2!r}"


@pytest.mark.integration
async def test_topic_lock():
    """POST /v1/sessions/{id}/topic with lock=true, create_if_missing=true → 200."""
    url, key = _creds()
    body = {
        "external_session_id": _new_ext_id(),
        "source": "az",
        "initial_topic_slug": "cortex-test",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        sess_resp = await client.post(f"{url}/v1/sessions", json=body, headers=_headers(key))
        assert sess_resp.status_code in (200, 201), (
            f"Session create failed: {sess_resp.status_code} {sess_resp.text}"
        )
        session_id = sess_resp.json()["id"]

        topic_resp = await client.post(
            f"{url}/v1/sessions/{session_id}/topic",
            json={"topic": "cortex-test", "lock": True, "create_if_missing": True},
            headers=_headers(key),
        )

    assert topic_resp.status_code == 200, (
        f"Topic-lock failed: {topic_resp.status_code} {topic_resp.text}"
    )


@pytest.mark.integration
async def test_session_project_less():
    """POST /v1/sessions without initial_topic_slug → session created (no bound topic)."""
    url, key = _creds()
    body = {
        "external_session_id": _new_ext_id(),
        "source": "az",
        # deliberately omit initial_topic_slug
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{url}/v1/sessions", json=body, headers=_headers(key))

    assert resp.status_code in (200, 201), (
        f"Expected 200/201, got {resp.status_code}: {resp.text}"
    )
    data = resp.json()
    assert "id" in data, f"Response missing 'id': {data}"
    assert isinstance(data["id"], str) and len(data["id"]) > 0
