"""Wrapper tests for _60_cortex_memorize.py (TDD — RED → GREEN → REFACTOR)."""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(enabled=True, api_key="test-key", url="http://cortex.local"):
    cfg = MagicMock()
    cfg.enabled = enabled
    cfg.api_key = api_key
    cfg.url = url
    return cfg


def _make_agent(session_id="sess-abc", stored_slug="homelab"):
    """Return a mock agent with context.get_data pre-wired."""
    agent = MagicMock()
    ctx = MagicMock()

    def _get_data(key):
        if key == "cortex_session_id":
            return session_id
        if key == "cortex_project_slug":
            return stored_slug
        return None

    ctx.get_data = MagicMock(side_effect=_get_data)
    agent.context = ctx
    agent.history = MagicMock()
    agent.concat_messages = MagicMock(return_value="messages string")
    agent.call_utility_model = AsyncMock(return_value="[]")
    return agent


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_ext(agent=None):
    """Import + instantiate CortexMemorize using stub Extension base."""
    # Import here so conftest stubs are already registered
    from extensions.python.monologue_end._60_cortex_memorize import CortexMemorize
    if agent is None:
        agent = _make_agent()
    return CortexMemorize(agent)


# ---------------------------------------------------------------------------
# 1. Disabled config → silent return
# ---------------------------------------------------------------------------

@patch("cortex_plugin.config.load_config")
def test_disabled_config_returns_silently(mock_cfg, caplog):
    mock_cfg.return_value = _make_cfg(enabled=False)
    ext = _make_ext()
    with caplog.at_level(logging.WARNING):
        _run(ext.execute())
    assert not caplog.records, "Should log nothing when disabled"


# ---------------------------------------------------------------------------
# 2. No API key → silent return
# ---------------------------------------------------------------------------

@patch("cortex_plugin.config.load_config")
def test_no_api_key_returns_silently(mock_cfg, caplog):
    mock_cfg.return_value = _make_cfg(api_key="")
    ext = _make_ext()
    with caplog.at_level(logging.WARNING):
        _run(ext.execute())
    assert not caplog.records, "Should log nothing when api_key is empty"


# ---------------------------------------------------------------------------
# 3. No session_id → warning + silent return
# ---------------------------------------------------------------------------

@patch("cortex_plugin.config.load_config")
def test_no_session_id_logs_warning_and_returns(mock_cfg, caplog):
    mock_cfg.return_value = _make_cfg()
    agent = _make_agent(session_id=None)
    ext = _make_ext(agent)
    with caplog.at_level(logging.WARNING):
        _run(ext.execute())
    assert any("cortex_session_id" in r.message or "session" in r.message.lower()
                for r in caplog.records), "Should log a warning about missing session_id"


# ---------------------------------------------------------------------------
# 4. Project lookup uses canonical helper
# ---------------------------------------------------------------------------

@patch("cortex_plugin.extraction.write_memories_to_cortex", new_callable=AsyncMock)
@patch("cortex_plugin.extraction.extract_fragments_and_solutions", new_callable=AsyncMock)
@patch("cortex_plugin.prompts.load_solutions_prompt", return_value="sol")
@patch("cortex_plugin.prompts.load_fragments_prompt", return_value="frag")
@patch("helpers.projects.get_context_project_name", return_value="homelab")
@patch("cortex_plugin.config.load_config")
def test_project_lookup_uses_canonical_helper(
    mock_cfg, mock_proj, mock_frag, mock_sol, mock_extract, mock_write
):
    mock_cfg.return_value = _make_cfg()
    mock_extract.return_value = ([], [])
    mock_write.return_value = {"written": 0, "failed": 0, "timed_out": False}
    agent = _make_agent()
    ext = _make_ext(agent)
    _run(ext.execute())
    mock_proj.assert_called_once_with(agent.context)


# ---------------------------------------------------------------------------
# 5. Stale project slug → info log + use new slug
# ---------------------------------------------------------------------------

@patch("cortex_plugin.extraction.write_memories_to_cortex", new_callable=AsyncMock)
@patch("cortex_plugin.extraction.extract_fragments_and_solutions", new_callable=AsyncMock)
@patch("cortex_plugin.prompts.load_solutions_prompt", return_value="sol")
@patch("cortex_plugin.prompts.load_fragments_prompt", return_value="frag")
@patch("helpers.projects.get_context_project_name", return_value="luthien")
@patch("cortex_plugin.config.load_config")
def test_stale_project_rebinds(
    mock_cfg, mock_proj, mock_frag, mock_sol, mock_extract, mock_write, caplog
):
    mock_cfg.return_value = _make_cfg()
    mock_extract.return_value = (["frag1"], [])
    mock_write.return_value = {"written": 1, "failed": 0, "timed_out": False}
    # stored slug is "homelab"; helper returns "luthien" → stale
    agent = _make_agent(stored_slug="homelab")
    ext = _make_ext(agent)
    with caplog.at_level(logging.INFO):
        _run(ext.execute())

    info_msgs = [r.message for r in caplog.records if r.levelno == logging.INFO]
    assert any("project changed mid-session" in m or ("homelab" in m and "luthien" in m)
               for m in info_msgs), f"Expected stale-project info log, got: {info_msgs}"
    # write_memories called with new slug "luthien"
    _, call_kwargs = mock_write.call_args
    args = mock_write.call_args[0]
    assert "luthien" in args, f"Expected 'luthien' slug in write call, got: {args}"


# ---------------------------------------------------------------------------
# 6. Calls agent.concat_messages(agent.history)
# ---------------------------------------------------------------------------

@patch("cortex_plugin.extraction.write_memories_to_cortex", new_callable=AsyncMock)
@patch("cortex_plugin.extraction.extract_fragments_and_solutions", new_callable=AsyncMock)
@patch("cortex_plugin.prompts.load_solutions_prompt", return_value="sol")
@patch("cortex_plugin.prompts.load_fragments_prompt", return_value="frag")
@patch("helpers.projects.get_context_project_name", return_value="homelab")
@patch("cortex_plugin.config.load_config")
def test_calls_concat_messages(
    mock_cfg, mock_proj, mock_frag, mock_sol, mock_extract, mock_write
):
    mock_cfg.return_value = _make_cfg()
    mock_extract.return_value = ([], [])
    mock_write.return_value = {"written": 0, "failed": 0, "timed_out": False}
    agent = _make_agent()
    ext = _make_ext(agent)
    _run(ext.execute())
    agent.concat_messages.assert_called_once_with(agent.history)


# ---------------------------------------------------------------------------
# 7. Calls load_fragments_prompt + load_solutions_prompt
# ---------------------------------------------------------------------------

@patch("cortex_plugin.extraction.write_memories_to_cortex", new_callable=AsyncMock)
@patch("cortex_plugin.extraction.extract_fragments_and_solutions", new_callable=AsyncMock)
@patch("cortex_plugin.prompts.load_solutions_prompt", return_value="sol")
@patch("cortex_plugin.prompts.load_fragments_prompt", return_value="frag")
@patch("helpers.projects.get_context_project_name", return_value="homelab")
@patch("cortex_plugin.config.load_config")
def test_calls_load_prompts(
    mock_cfg, mock_proj, mock_frag, mock_sol, mock_extract, mock_write
):
    mock_cfg.return_value = _make_cfg()
    mock_extract.return_value = ([], [])
    mock_write.return_value = {"written": 0, "failed": 0, "timed_out": False}
    ext = _make_ext()
    _run(ext.execute())
    mock_frag.assert_called_once()
    mock_sol.assert_called_once()


# ---------------------------------------------------------------------------
# 8. Calls extract_fragments_and_solutions with correct args
# ---------------------------------------------------------------------------

@patch("cortex_plugin.extraction.write_memories_to_cortex", new_callable=AsyncMock)
@patch("cortex_plugin.extraction.extract_fragments_and_solutions", new_callable=AsyncMock)
@patch("cortex_plugin.prompts.load_solutions_prompt", return_value="SOL_PROMPT")
@patch("cortex_plugin.prompts.load_fragments_prompt", return_value="FRAG_PROMPT")
@patch("helpers.projects.get_context_project_name", return_value="homelab")
@patch("cortex_plugin.config.load_config")
def test_calls_extract_fragments_and_solutions(
    mock_cfg, mock_proj, mock_frag, mock_sol, mock_extract, mock_write
):
    mock_cfg.return_value = _make_cfg()
    mock_extract.return_value = (["f1"], [])
    mock_write.return_value = {"written": 1, "failed": 0, "timed_out": False}
    agent = _make_agent()
    ext = _make_ext(agent)
    _run(ext.execute())

    mock_extract.assert_called_once()
    args = mock_extract.call_args[0]
    assert args[0] == "messages string", f"Expected messages_str, got: {args[0]}"
    assert args[2] == "FRAG_PROMPT", f"Expected frag prompt, got: {args[2]}"
    assert args[3] == "SOL_PROMPT", f"Expected sol prompt, got: {args[3]}"
    kwargs = mock_extract.call_args[1]
    assert "timeout_sec" in kwargs, "Should pass timeout_sec keyword arg"


# ---------------------------------------------------------------------------
# 9. Calls write_memories_to_cortex once with session_id, slug, fragments, solutions
# ---------------------------------------------------------------------------

@patch("cortex_plugin.extraction.write_memories_to_cortex", new_callable=AsyncMock)
@patch("cortex_plugin.extraction.extract_fragments_and_solutions", new_callable=AsyncMock)
@patch("cortex_plugin.prompts.load_solutions_prompt", return_value="sol")
@patch("cortex_plugin.prompts.load_fragments_prompt", return_value="frag")
@patch("helpers.projects.get_context_project_name", return_value="homelab")
@patch("cortex_plugin.config.load_config")
def test_calls_write_memories_to_cortex(
    mock_cfg, mock_proj, mock_frag, mock_sol, mock_extract, mock_write
):
    mock_cfg.return_value = _make_cfg()
    mock_extract.return_value = (["frag1"], [{"problem": "p", "solution": "s"}])
    mock_write.return_value = {"written": 2, "failed": 0, "timed_out": False}
    agent = _make_agent(session_id="sess-123", stored_slug="homelab")
    ext = _make_ext(agent)
    _run(ext.execute())

    mock_write.assert_called_once()
    args = mock_write.call_args[0]
    assert args[0] == "sess-123", f"Expected session_id, got: {args[0]}"
    assert args[2] == ["frag1"], f"Expected fragments, got: {args[2]}"
    assert args[3] == [{"problem": "p", "solution": "s"}], f"Expected solutions, got: {args[3]}"
    kwargs = mock_write.call_args[1]
    assert "posting_timeout_sec" in kwargs, "Should pass posting_timeout_sec keyword arg"


# ---------------------------------------------------------------------------
# 10. Logs INFO with structured format
# ---------------------------------------------------------------------------

@patch("cortex_plugin.extraction.write_memories_to_cortex", new_callable=AsyncMock)
@patch("cortex_plugin.extraction.extract_fragments_and_solutions", new_callable=AsyncMock)
@patch("cortex_plugin.prompts.load_solutions_prompt", return_value="sol")
@patch("cortex_plugin.prompts.load_fragments_prompt", return_value="frag")
@patch("helpers.projects.get_context_project_name", return_value="homelab")
@patch("cortex_plugin.config.load_config")
def test_logs_info_structured_format(
    mock_cfg, mock_proj, mock_frag, mock_sol, mock_extract, mock_write, caplog
):
    mock_cfg.return_value = _make_cfg()
    mock_extract.return_value = (["f1", "f2"], [])
    mock_write.return_value = {"written": 2, "failed": 1, "timed_out": False}
    ext = _make_ext()
    with caplog.at_level(logging.INFO):
        _run(ext.execute())

    info_msgs = [r.message for r in caplog.records if r.levelno == logging.INFO]
    structured = [m for m in info_msgs if "written=" in m and "failed=" in m and "ms=" in m]
    assert structured, f"Expected structured INFO log, got: {info_msgs}"


# ---------------------------------------------------------------------------
# 11. Unhandled exception → logs warning, returns (non-fatal)
# ---------------------------------------------------------------------------

@patch("cortex_plugin.extraction.write_memories_to_cortex", new_callable=AsyncMock)
@patch("cortex_plugin.extraction.extract_fragments_and_solutions", new_callable=AsyncMock)
@patch("cortex_plugin.prompts.load_solutions_prompt", return_value="sol")
@patch("cortex_plugin.prompts.load_fragments_prompt", side_effect=RuntimeError("boom"))
@patch("helpers.projects.get_context_project_name", return_value="homelab")
@patch("cortex_plugin.config.load_config")
def test_unhandled_exception_non_fatal(
    mock_cfg, mock_proj, mock_frag, mock_sol, mock_extract, mock_write, caplog
):
    mock_cfg.return_value = _make_cfg()
    ext = _make_ext()
    with caplog.at_level(logging.WARNING):
        _run(ext.execute())
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warns, "Should log a warning on unhandled exception"


# ---------------------------------------------------------------------------
# 12. No extras_persistent["memories"] mutation
# ---------------------------------------------------------------------------

@patch("cortex_plugin.extraction.write_memories_to_cortex", new_callable=AsyncMock)
@patch("cortex_plugin.extraction.extract_fragments_and_solutions", new_callable=AsyncMock)
@patch("cortex_plugin.prompts.load_solutions_prompt", return_value="sol")
@patch("cortex_plugin.prompts.load_fragments_prompt", return_value="frag")
@patch("helpers.projects.get_context_project_name", return_value="homelab")
@patch("cortex_plugin.config.load_config")
def test_no_extras_persistent_mutation(
    mock_cfg, mock_proj, mock_frag, mock_sol, mock_extract, mock_write
):
    mock_cfg.return_value = _make_cfg()
    mock_extract.return_value = (["f1"], [])
    mock_write.return_value = {"written": 1, "failed": 0, "timed_out": False}
    loop_data = MagicMock()
    loop_data.extras_persistent = {"memories": "ORIGINAL"}
    ext = _make_ext()
    _run(ext.execute(loop_data=loop_data))
    assert loop_data.extras_persistent["memories"] == "ORIGINAL", \
        "memorize must not mutate extras_persistent['memories']"
