"""Wrapper tests for _60_cortex_init.py (TDD — RED → GREEN → REFACTOR)."""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SESSION_RESP = {"id": "cortex-session-xyz"}


def _make_cfg(enabled=True, api_key="test-key", url="http://cortex.local"):
    cfg = MagicMock()
    cfg.enabled = enabled
    cfg.api_key = api_key
    cfg.url = url
    return cfg


def _make_agent(project_name="homelab"):
    agent = MagicMock()
    ctx = MagicMock()
    ctx.id = "az-session-abc"
    ctx.get_data.side_effect = lambda key: project_name if key == "project" else None
    ctx.current_project = project_name
    agent.context = ctx
    return agent


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_ext(agent=None):
    """Import + instantiate CortexInit using stub Extension base."""
    from extensions.python.monologue_start._60_cortex_init import CortexInit
    if agent is None:
        agent = _make_agent()
    return CortexInit(agent)


# ---------------------------------------------------------------------------
# 1. execute() calls config.load_config()
# ---------------------------------------------------------------------------

@patch("cortex_plugin.http.cortex_post", new_callable=AsyncMock)
@patch("cortex_plugin.slugs.project_resolve", return_value=("homelab", "homelab"))
@patch("helpers.projects.get_context_project_name", return_value="homelab")
@patch("cortex_plugin.config.load_config")
def test_calls_load_config(mock_cfg, mock_proj, mock_resolve, mock_post):
    mock_cfg.return_value = _make_cfg()
    mock_post.return_value = SESSION_RESP
    _run(_make_ext().execute())
    mock_cfg.assert_called_once()


# ---------------------------------------------------------------------------
# 2. Project lookup uses canonical AZ helper
# ---------------------------------------------------------------------------

@patch("cortex_plugin.http.cortex_post", new_callable=AsyncMock)
@patch("cortex_plugin.slugs.project_resolve", return_value=("homelab", "homelab"))
@patch("helpers.projects.get_context_project_name", return_value="homelab")
@patch("cortex_plugin.config.load_config")
def test_project_lookup_via_helper(mock_cfg, mock_proj, mock_resolve, mock_post):
    mock_cfg.return_value = _make_cfg()
    mock_post.return_value = SESSION_RESP
    agent = _make_agent(project_name="homelab")
    _run(_make_ext(agent).execute())
    mock_proj.assert_called_once_with(agent.context)


# ---------------------------------------------------------------------------
# 3. Project lookup fallback when helper raises
# ---------------------------------------------------------------------------

@patch("cortex_plugin.http.cortex_post", new_callable=AsyncMock)
@patch("cortex_plugin.slugs.project_resolve")
@patch("helpers.projects.get_context_project_name", side_effect=RuntimeError("boom"))
@patch("cortex_plugin.config.load_config")
def test_project_fallback_when_helper_raises(mock_cfg, mock_proj, mock_resolve, mock_post):
    mock_cfg.return_value = _make_cfg()
    mock_resolve.return_value = ("fallback_proj", "fallback-proj")
    mock_post.return_value = SESSION_RESP
    agent = _make_agent(project_name="fallback-proj")
    _run(_make_ext(agent).execute())
    # Falls back to ctx.current_project = "fallback-proj"
    mock_resolve.assert_called_once_with("fallback-proj")


# ---------------------------------------------------------------------------
# 4. Disabled config → silent return, no HTTP
# ---------------------------------------------------------------------------

@patch("cortex_plugin.http.cortex_post", new_callable=AsyncMock)
@patch("cortex_plugin.config.load_config")
def test_disabled_config_no_http(mock_cfg, mock_post):
    mock_cfg.return_value = _make_cfg(enabled=False)
    _run(_make_ext().execute())
    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# 5. No API key → silent return, no HTTP
# ---------------------------------------------------------------------------

@patch("cortex_plugin.http.cortex_post", new_callable=AsyncMock)
@patch("cortex_plugin.config.load_config")
def test_no_api_key_no_http(mock_cfg, mock_post):
    mock_cfg.return_value = _make_cfg(api_key="")
    _run(_make_ext().execute())
    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Valid config → session POST with correct body
# ---------------------------------------------------------------------------

@patch("cortex_plugin.http.cortex_post", new_callable=AsyncMock)
@patch("cortex_plugin.slugs.project_resolve", return_value=("homelab", "homelab"))
@patch("helpers.projects.get_context_project_name", return_value="homelab")
@patch("cortex_plugin.config.load_config")
def test_session_post_body(mock_cfg, mock_proj, mock_resolve, mock_post):
    mock_cfg.return_value = _make_cfg(url="http://cortex.local")
    mock_post.return_value = SESSION_RESP
    agent = _make_agent(project_name="homelab")
    _run(_make_ext(agent).execute())

    # At least one call is for /v1/sessions
    session_calls = [
        c for c in mock_post.call_args_list
        if c[0][1] == "/v1/sessions"
    ]
    assert session_calls, "Expected cortex_post call for /v1/sessions"
    args = session_calls[0][0]  # positional args: (url, path, body, api_key)
    assert args[0] == "http://cortex.local"
    assert args[2] == {
        "external_session_id": "az-session-abc",
        "source": "az",
        "initial_topic_slug": "homelab",
    }


# ---------------------------------------------------------------------------
# 7. On 200 → set_data called for all three keys
# ---------------------------------------------------------------------------

@patch("cortex_plugin.http.cortex_post", new_callable=AsyncMock)
@patch("cortex_plugin.slugs.project_resolve", return_value=("homelab", "homelab"))
@patch("helpers.projects.get_context_project_name", return_value="homelab")
@patch("cortex_plugin.config.load_config")
def test_sets_context_data(mock_cfg, mock_proj, mock_resolve, mock_post):
    mock_cfg.return_value = _make_cfg()
    mock_post.return_value = SESSION_RESP
    agent = _make_agent(project_name="homelab")
    _run(_make_ext(agent).execute())

    agent.context.set_data.assert_any_call("cortex_session_id", "cortex-session-xyz")
    agent.context.set_data.assert_any_call("cortex_project_slug", "homelab")
    agent.context.set_data.assert_any_call("cortex_project_name", "homelab")


# ---------------------------------------------------------------------------
# 8. Topic-lock POST after session POST for project sessions
# ---------------------------------------------------------------------------

@patch("cortex_plugin.http.cortex_post", new_callable=AsyncMock)
@patch("cortex_plugin.slugs.project_resolve", return_value=("homelab", "homelab"))
@patch("helpers.projects.get_context_project_name", return_value="homelab")
@patch("cortex_plugin.config.load_config")
def test_topic_lock_for_project(mock_cfg, mock_proj, mock_resolve, mock_post):
    mock_cfg.return_value = _make_cfg()
    mock_post.side_effect = [{"id": "cortex-session-xyz"}, {}]
    agent = _make_agent(project_name="homelab")
    _run(_make_ext(agent).execute())

    assert mock_post.call_count == 2, (
        f"Expected 2 cortex_post calls (session + topic lock), got {mock_post.call_count}"
    )
    topic_args = mock_post.call_args_list[1][0]
    assert topic_args[1] == "/v1/sessions/cortex-session-xyz/topic"
    assert topic_args[2] == {"topic": "homelab", "lock": True, "create_if_missing": True}


# ---------------------------------------------------------------------------
# 9. Project-less: no topic-lock POST; cortex_project_slug=None
# ---------------------------------------------------------------------------

@patch("cortex_plugin.http.cortex_post", new_callable=AsyncMock)
@patch("cortex_plugin.slugs.project_resolve", return_value=(None, None))
@patch("helpers.projects.get_context_project_name", return_value=None)
@patch("cortex_plugin.config.load_config")
def test_no_topic_lock_projectless(mock_cfg, mock_proj, mock_resolve, mock_post):
    mock_cfg.return_value = _make_cfg()
    mock_post.return_value = SESSION_RESP
    agent = _make_agent(project_name=None)
    _run(_make_ext(agent).execute())

    assert mock_post.call_count == 1, (
        f"Expected only 1 cortex_post call (no topic lock), got {mock_post.call_count}"
    )
    agent.context.set_data.assert_any_call("cortex_project_slug", None)


# ---------------------------------------------------------------------------
# 10. HTTP exception → no escape; logs warning
# ---------------------------------------------------------------------------

@patch("cortex_plugin.http.cortex_post", new_callable=AsyncMock)
@patch("cortex_plugin.slugs.project_resolve", return_value=("homelab", "homelab"))
@patch("helpers.projects.get_context_project_name", return_value="homelab")
@patch("cortex_plugin.config.load_config")
def test_http_exception_no_escape(mock_cfg, mock_proj, mock_resolve, mock_post, caplog):
    mock_cfg.return_value = _make_cfg()
    mock_post.side_effect = Exception("network error")
    with caplog.at_level(logging.WARNING):
        _run(_make_ext().execute())  # must not raise
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warns, "Should log a warning on HTTP exception"


# ---------------------------------------------------------------------------
# 11. Logs INFO once per successful session: session= project=
# ---------------------------------------------------------------------------

@patch("cortex_plugin.http.cortex_post", new_callable=AsyncMock)
@patch("cortex_plugin.slugs.project_resolve", return_value=("homelab", "homelab"))
@patch("helpers.projects.get_context_project_name", return_value="homelab")
@patch("cortex_plugin.config.load_config")
def test_logs_info_on_success(mock_cfg, mock_proj, mock_resolve, mock_post, caplog):
    mock_cfg.return_value = _make_cfg()
    mock_post.return_value = SESSION_RESP
    with caplog.at_level(logging.WARNING):
        _run(_make_ext().execute())

    info_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("session=cortex-session-xyz" in m for m in info_msgs), (
        f"Expected INFO log with session=cortex-session-xyz, got: {info_msgs}"
    )
    assert any("project=homelab" in m for m in info_msgs), (
        f"Expected INFO log with project=homelab, got: {info_msgs}"
    )
