from __future__ import annotations

from typing import Any

import httpx


def _build_headers(api_key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {api_key}"}
    if extra:
        headers.update(extra)
    return headers


async def cortex_post(
    url: str,
    path: str,
    body: dict[str, Any],
    api_key: str,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    timeout_sec: int = 10,
) -> dict[str, Any]:
    built_headers = _build_headers(api_key, headers)
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        response = await client.post(
            url + path,
            json=body,
            headers=built_headers,
            params=params,
        )
        response.raise_for_status()
        return response.json()


async def cortex_get(
    url: str,
    path: str,
    api_key: str,
    params: dict[str, str] | None = None,
    timeout_sec: int = 10,
) -> dict[str, Any]:
    built_headers = _build_headers(api_key)
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        response = await client.get(
            url + path,
            headers=built_headers,
            params=params,
        )
        response.raise_for_status()
        return response.json()
