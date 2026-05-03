from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["CORTEX_URL"] = "http://localhost:8001"
os.environ["CORTEX_API_KEY"] = "testtoken"
os.environ["CORTEX_ENABLED"] = "true"


class FakeContext:
    def __init__(self):
        self.id = "az-session-123"
        self.current_project = "homelab"
        self._data = {"cortex_session_id": "cortex-session-abc"}

    def get_data(self, key):
        return self._data.get(key)


class FakeLoopData:
    def __init__(self, fragments=None, solutions=None):
        self.fragments = fragments or []
        self.solutions = solutions or []
        self.extras_persistent = {}


class FakeAgent:
    def __init__(self):
        self.context = FakeContext()


@pytest.mark.asyncio
async def test_memorize_writes_fragments_and_solutions():
    agent = FakeAgent()
    loop_data = FakeLoopData(
        fragments=["fragment 1", "fragment 2", "fragment 3"],
        solutions=["solution 1", "solution 2"],
    )
    calls = []

    async def mock_post(url, json=None, headers=None):
        calls.append({"url": url, "json": json, "headers": headers})
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"id": "mem-123"})
        return resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=mock_post)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from extensions.python.monologue_end._60_cortex_memorize import execute
        await execute(agent=agent, loop_data=loop_data)

    assert len(calls) == 5
    areas = [c["json"]["area"] for c in calls]
    assert areas.count("fragments") == 3
    assert areas.count("solutions") == 2
    for call in calls:
        assert "Idempotency-Key" in call["headers"]


@pytest.mark.asyncio
async def test_memorize_does_not_raise_on_cortex_error():
    agent = FakeAgent()
    loop_data = FakeLoopData(fragments=["test fragment"])

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("503"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from extensions.python.monologue_end._60_cortex_memorize import execute
        await execute(agent=agent, loop_data=loop_data)
