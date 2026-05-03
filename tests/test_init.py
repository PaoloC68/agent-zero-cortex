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
    def __init__(self, project=None):
        self.id = "az-session-123"
        self.current_project = project
        self._data = {}

    def set_data(self, key, value):
        self._data[key] = value

    def get_data(self, key):
        return self._data.get(key)


class FakeAgent:
    def __init__(self, project=None):
        self.context = FakeContext(project)


@pytest.mark.asyncio
async def test_init_posts_session_with_sanitized_slug():
    agent = FakeAgent(project="homelab")
    captured = {}

    async def mock_post(url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"id": "cortex-session-abc"})
        return resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=mock_post)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from extensions.python.monologue_start._60_cortex_init import execute
        await execute(agent=agent)

    assert captured["json"]["source"] == "az"
    assert captured["json"]["initial_topic_slug"] == "homelab"
    assert agent.context.get_data("cortex_session_id") == "cortex-session-abc"


@pytest.mark.asyncio
async def test_init_sanitizes_special_chars():
    agent = FakeAgent(project="Foo Bar/Baz!")

    async def mock_post(url, json=None, headers=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"id": "cortex-session-xyz"})
        return resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=mock_post)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from extensions.python.monologue_start._60_cortex_init import execute
        await execute(agent=agent)

    assert agent.context.get_data("cortex_session_id") == "cortex-session-xyz"


@pytest.mark.asyncio
async def test_init_does_not_raise_on_503():
    agent = FakeAgent(project="homelab")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("503 Service Unavailable"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from extensions.python.monologue_start._60_cortex_init import execute
        await execute(agent=agent)
