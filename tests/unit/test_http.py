"""Tests for cortex_plugin.http — minimal async POST/GET helpers.

TDD (RED → GREEN) for cortex_post and cortex_get.
All httpx network calls are mocked via unittest.mock.patch.
"""
from __future__ import annotations

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from cortex_plugin.http import cortex_get, cortex_post

BASE_URL = "http://cortex.test"
API_KEY = "test-key-abc"
POST_PATH = "/v1/memories"
GET_PATH = "/v1/sessions"


def _mock_response(data: dict[str, object] | None = None) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = data if data is not None else {"ok": True}
    resp.raise_for_status = MagicMock()
    return resp


def _error_response(status_code: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        f"{status_code} Error",
        request=MagicMock(),
        response=resp,
    )
    return resp


def _patch_client(mock_client: AsyncMock):
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
    return patch("cortex_plugin.http.httpx.AsyncClient", mock_cls), mock_cls


async def test_post_returns_json_on_2xx():
    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_response({"id": "mem-1"})
    ctx, _ = _patch_client(mock_client)

    with ctx:
        result = await cortex_post(BASE_URL, POST_PATH, {"content": "hello"}, API_KEY)

    assert result == {"id": "mem-1"}


async def test_post_raises_on_4xx():
    mock_client = AsyncMock()
    mock_client.post.return_value = _error_response(404)
    ctx, _ = _patch_client(mock_client)

    with ctx:
        with pytest.raises(httpx.HTTPStatusError):
            await cortex_post(BASE_URL, POST_PATH, {}, API_KEY)


async def test_post_raises_on_5xx():
    mock_client = AsyncMock()
    mock_client.post.return_value = _error_response(503)
    ctx, _ = _patch_client(mock_client)

    with ctx:
        with pytest.raises(httpx.HTTPStatusError):
            await cortex_post(BASE_URL, POST_PATH, {}, API_KEY)


async def test_bearer_header_added():
    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_response()
    ctx, _ = _patch_client(mock_client)

    with ctx:
        await cortex_post(BASE_URL, POST_PATH, {}, API_KEY)

    headers = mock_client.post.call_args.kwargs["headers"]
    assert headers["Authorization"] == f"Bearer {API_KEY}"


async def test_custom_headers_merged():
    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_response()
    ctx, _ = _patch_client(mock_client)

    with ctx:
        await cortex_post(
            BASE_URL,
            POST_PATH,
            {},
            API_KEY,
            headers={"Idempotency-Key": "idem-abc123"},
        )

    headers = mock_client.post.call_args.kwargs["headers"]
    assert headers["Authorization"] == f"Bearer {API_KEY}"
    assert headers["Idempotency-Key"] == "idem-abc123"


async def test_query_params_appended():
    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_response()
    ctx, _ = _patch_client(mock_client)

    with ctx:
        await cortex_post(
            BASE_URL,
            POST_PATH,
            {},
            API_KEY,
            params={"legacy_rank": "true"},
        )

    params = mock_client.post.call_args.kwargs["params"]
    assert params == {"legacy_rank": "true"}


async def test_post_timeout_honored():
    mock_client = AsyncMock()
    mock_client.post.side_effect = httpx.TimeoutException("timed out")

    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("cortex_plugin.http.httpx.AsyncClient", mock_cls):
        with pytest.raises(httpx.TimeoutException):
            await cortex_post(BASE_URL, POST_PATH, {}, API_KEY, timeout_sec=3)

    mock_cls.assert_called_once_with(timeout=3)


async def test_get_returns_json_on_2xx():
    mock_client = AsyncMock()
    mock_client.get.return_value = _mock_response({"sessions": []})
    ctx, _ = _patch_client(mock_client)

    with ctx:
        result = await cortex_get(BASE_URL, GET_PATH, API_KEY)

    assert result == {"sessions": []}


async def test_get_raises_on_4xx_5xx():
    mock_client = AsyncMock()
    mock_client.get.return_value = _error_response(401)
    ctx, _ = _patch_client(mock_client)

    with ctx:
        with pytest.raises(httpx.HTTPStatusError):
            await cortex_get(BASE_URL, GET_PATH, API_KEY)


async def test_per_call_client():
    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_response()

    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("cortex_plugin.http.httpx.AsyncClient", mock_cls):
        await cortex_post(BASE_URL, POST_PATH, {}, API_KEY)
        await cortex_post(BASE_URL, POST_PATH, {}, API_KEY)

    assert mock_cls.call_count == 2
