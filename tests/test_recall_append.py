from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["CORTEX_URL"] = "http://localhost:8001"
os.environ["CORTEX_API_KEY"] = "testtoken"
os.environ["CORTEX_ENABLED"] = "true"
os.environ["CORTEX_MERGE_STRATEGY"] = "append"


class FakeContext:
    def __init__(self):
        self._data = {"cortex_session_id": "cortex-session-abc"}

    def get_data(self, key):
        return self._data.get(key)


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeLoopData:
    def __init__(self, faiss_memories="FAISS_PROMPT_BLOCK"):
        self.messages = [FakeMessage("test query about homelab")]
        self.extras_persistent = {"memories": faiss_memories, "solutions": "FAISS_SOLUTIONS"}


class FakeAgent:
    def __init__(self):
        self.context = FakeContext()


@pytest.mark.asyncio
async def test_append_preserves_faiss_and_adds_cortex():
    agent = FakeAgent()
    loop_data = FakeLoopData(faiss_memories="FAISS_PROMPT_BLOCK")

    async def mock_post(url, json=None, headers=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=[
            {"content": "Cortex memory item 1", "score": 0.9, "matched_via": ["vector"]},
            {"content": "Cortex memory item 2", "score": 0.8, "matched_via": ["bm25"]},
        ])
        return resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=mock_post)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from extensions.python.message_loop_prompts_after._60_cortex_recall import execute
        await execute(agent=agent, loop_data=loop_data)

    memories = loop_data.extras_persistent["memories"]
    assert memories.startswith("FAISS_PROMPT_BLOCK"), "FAISS content must be preserved"
    assert "## Cortex memories (additional)" in memories
    assert "Cortex memory item 1" in memories
    assert loop_data.extras_persistent["solutions"] == "FAISS_SOLUTIONS"


@pytest.mark.asyncio
async def test_cortex_down_extras_untouched():
    agent = FakeAgent()
    loop_data = FakeLoopData(faiss_memories="FAISS_PROMPT_BLOCK")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("503"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from extensions.python.message_loop_prompts_after._60_cortex_recall import execute
        await execute(agent=agent, loop_data=loop_data)

    assert loop_data.extras_persistent["memories"] == "FAISS_PROMPT_BLOCK"


@pytest.mark.asyncio
async def test_strategy_off_disables_append():
    os.environ["CORTEX_MERGE_STRATEGY"] = "off"
    agent = FakeAgent()
    loop_data = FakeLoopData(faiss_memories="FAISS_PROMPT_BLOCK")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=MagicMock())
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from extensions.python.message_loop_prompts_after._60_cortex_recall import execute
        await execute(agent=agent, loop_data=loop_data)

    assert loop_data.extras_persistent["memories"] == "FAISS_PROMPT_BLOCK"
    os.environ["CORTEX_MERGE_STRATEGY"] = "append"
