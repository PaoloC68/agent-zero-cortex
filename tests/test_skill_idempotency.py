from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_skill_idempotency_fixture():
    call_count = 0
    seen_keys: set[str] = set()

    async def mock_post(url, json=None, headers=None):
        nonlocal call_count
        idem_key = (headers or {}).get("Idempotency-Key")
        if idem_key and idem_key in seen_keys:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json = MagicMock(return_value={"id": "existing-mem", "dedup_key": "abc"})
            return resp
        if idem_key:
            seen_keys.add(idem_key)
        call_count += 1
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"id": f"mem-{call_count}", "dedup_key": "abc"})
        return resp

    docs = [{"id": f"doc-{i}", "content": f"content {i}", "area": "main"} for i in range(5)]

    import hashlib
    import httpx

    project_slug = "fixture_proj"

    async def run_migration():
        async with httpx.AsyncClient(timeout=30.0) as client:
            for doc in docs:
                idem_key = hashlib.sha256(f"{project_slug}|{doc['id']}".encode()).hexdigest()
                await client.post(
                    "http://localhost:8001/v1/memories",
                    json={
                        "content": doc["content"],
                        "kind": "main",
                        "area": "main",
                        "source_project": project_slug,
                        "importance": 0.5,
                    },
                    headers={"Authorization": "Bearer testtoken", "Idempotency-Key": idem_key},
                )

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=mock_post)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await run_migration()
        count_after_run1 = call_count

        await run_migration()
        count_after_run2 = call_count

    assert count_after_run1 == 5, f"Expected 5 new memories after run 1, got {count_after_run1}"
    assert count_after_run2 == 5, f"Expected same count after run 2 (idempotent), got {count_after_run2}"
