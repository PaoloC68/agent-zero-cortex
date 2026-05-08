from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx


def _make_cfg(
    enabled=True,
    api_key="test-key",
    url="http://cortex.local",
    recall_limit=5,
    recall_threshold=0.02,
    recall_legacy_rank=False,
):
    cfg = MagicMock()
    cfg.enabled = enabled
    cfg.api_key = api_key
    cfg.url = url
    cfg.recall_limit = recall_limit
    cfg.recall_threshold = recall_threshold
    cfg.recall_legacy_rank = recall_legacy_rank
    return cfg


def _make_agent(session_id="sess-abc"):
    agent = MagicMock()
    ctx = MagicMock()
    ctx.get_data.side_effect = lambda key: session_id if key == "cortex_session_id" else None
    agent.context = ctx
    return agent


def _make_loop_data(content="What is the capital of France?", memories=""):
    loop_data = MagicMock()
    msg = MagicMock()
    msg.content = content
    loop_data.messages = [msg]
    loop_data.extras_persistent = {"memories": memories}
    return loop_data


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_ext(agent=None):
    from extensions.python.message_loop_prompts_after._60_cortex_recall import CortexRecall
    if agent is None:
        agent = _make_agent()
    return CortexRecall(agent)


@patch("cortex_plugin.recall.recall_and_format", new_callable=AsyncMock)
@patch("cortex_plugin.config.load_config")
def test_disabled_skips(mock_cfg, mock_recall):
    mock_cfg.return_value = _make_cfg(enabled=False)
    ext = _make_ext()
    loop_data = _make_loop_data()
    _run(ext.execute(loop_data=loop_data))
    mock_recall.assert_not_called()
    assert loop_data.extras_persistent["memories"] == ""


@patch("cortex_plugin.recall.recall_and_format", new_callable=AsyncMock)
@patch("cortex_plugin.config.load_config")
def test_no_api_key_skips(mock_cfg, mock_recall):
    mock_cfg.return_value = _make_cfg(api_key="")
    ext = _make_ext()
    loop_data = _make_loop_data()
    _run(ext.execute(loop_data=loop_data))
    mock_recall.assert_not_called()
    assert loop_data.extras_persistent["memories"] == ""


@patch("cortex_plugin.recall.recall_and_format", new_callable=AsyncMock)
@patch("cortex_plugin.config.load_config")
def test_missing_session_id_skips(mock_cfg, mock_recall):
    mock_cfg.return_value = _make_cfg()
    agent = _make_agent(session_id=None)
    ext = _make_ext(agent)
    loop_data = _make_loop_data()
    _run(ext.execute(loop_data=loop_data))
    mock_recall.assert_not_called()
    assert loop_data.extras_persistent["memories"] == ""


@patch("cortex_plugin.recall.recall_and_format", new_callable=AsyncMock)
@patch("cortex_plugin.config.load_config")
def test_short_query_skips(mock_cfg, mock_recall):
    mock_cfg.return_value = _make_cfg()
    ext = _make_ext()
    loop_data = _make_loop_data(content="ab", memories="EXISTING")
    _run(ext.execute(loop_data=loop_data))
    mock_recall.assert_not_called()
    assert loop_data.extras_persistent["memories"] == "EXISTING"


@patch("cortex_plugin.recall.recall_and_format", new_callable=AsyncMock)
@patch("helpers.projects.get_context_project_name", return_value=None)
@patch("cortex_plugin.config.load_config")
def test_query_extraction_truncated(mock_cfg, mock_proj, mock_recall):
    mock_cfg.return_value = _make_cfg()
    mock_recall.return_value = ""
    long_content = "x" * 600
    ext = _make_ext()
    loop_data = _make_loop_data(content=long_content)
    _run(ext.execute(loop_data=loop_data))
    mock_recall.assert_called_once()
    actual_query = mock_recall.call_args[0][0]
    assert len(actual_query) == 500
    assert actual_query == "x" * 500


@patch("cortex_plugin.recall.recall_and_format", new_callable=AsyncMock)
@patch("helpers.projects.get_context_project_name", return_value="My Project!")
@patch("cortex_plugin.config.load_config")
def test_project_lookup_called(mock_cfg, mock_proj, mock_recall):
    mock_cfg.return_value = _make_cfg()
    mock_recall.return_value = ""
    agent = _make_agent()
    ext = _make_ext(agent)
    loop_data = _make_loop_data()
    _run(ext.execute(loop_data=loop_data))
    mock_proj.assert_called_once_with(agent.context)
    actual_project = mock_recall.call_args[0][2]
    assert actual_project == "my_project_"


@patch("cortex_plugin.recall.recall_and_format", new_callable=AsyncMock)
@patch("helpers.projects.get_context_project_name", return_value=None)
@patch("cortex_plugin.config.load_config")
def test_recall_called_with_config(mock_cfg, mock_proj, mock_recall):
    mock_cfg.return_value = _make_cfg(
        recall_threshold=0.15,
        recall_legacy_rank=False,
        recall_limit=3,
    )
    mock_recall.return_value = ""
    ext = _make_ext()
    loop_data = _make_loop_data()
    _run(ext.execute(loop_data=loop_data))
    mock_recall.assert_called_once()
    _, kwargs = mock_recall.call_args
    assert kwargs["threshold"] == 0.15
    assert kwargs["legacy_rank"] is False
    assert kwargs["recall_limit"] == 3


@patch("cortex_plugin.recall.recall_and_format", new_callable=AsyncMock)
@patch("helpers.projects.get_context_project_name", return_value=None)
@patch("cortex_plugin.config.load_config")
def test_legacy_rank_toggle(mock_cfg, mock_proj, mock_recall):
    mock_cfg.return_value = _make_cfg(recall_legacy_rank=True)
    mock_recall.return_value = ""
    ext = _make_ext()
    _run(ext.execute(loop_data=_make_loop_data()))
    _, kwargs = mock_recall.call_args
    assert kwargs["legacy_rank"] is True


@patch("cortex_plugin.recall.recall_and_format", new_callable=AsyncMock)
@patch("helpers.projects.get_context_project_name", return_value=None)
@patch("cortex_plugin.config.load_config")
def test_replaces_extras(mock_cfg, mock_proj, mock_recall):
    mock_cfg.return_value = _make_cfg()
    mock_recall.return_value = "## Memories\n\nNEW"
    ext = _make_ext()
    loop_data = _make_loop_data(memories="OLD_FAISS_CONTENT")
    _run(ext.execute(loop_data=loop_data))
    assert loop_data.extras_persistent["memories"] == "## Memories\n\nNEW"
    assert "OLD_FAISS_CONTENT" not in loop_data.extras_persistent["memories"]


@patch("cortex_plugin.recall.recall_and_format", new_callable=AsyncMock)
@patch("helpers.projects.get_context_project_name", return_value=None)
@patch("cortex_plugin.config.load_config")
def test_failure_no_clobber(mock_cfg, mock_proj, mock_recall, caplog):
    mock_cfg.return_value = _make_cfg()
    req = httpx.Request("POST", "http://cortex.local/v1/recall")
    mock_recall.side_effect = httpx.RequestError("timed out", request=req)
    ext = _make_ext()
    loop_data = _make_loop_data(memories="PREVIOUS_VALUE")
    with caplog.at_level(logging.WARNING):
        _run(ext.execute(loop_data=loop_data))
    assert loop_data.extras_persistent["memories"] == "PREVIOUS_VALUE"
    assert any(r.levelno == logging.WARNING for r in caplog.records)


@patch("cortex_plugin.recall.recall_and_format", new_callable=AsyncMock)
@patch("helpers.projects.get_context_project_name", return_value=None)
@patch("cortex_plugin.config.load_config")
def test_empty_clears_stale(mock_cfg, mock_proj, mock_recall):
    mock_cfg.return_value = _make_cfg()
    mock_recall.return_value = ""
    ext = _make_ext()
    loop_data = _make_loop_data(memories="STALE_FAISS")
    _run(ext.execute(loop_data=loop_data))
    assert loop_data.extras_persistent["memories"] == ""
