"""Cortex HTTP client wrapper for agent-zero-cortex plugin."""
from __future__ import annotations

import os
from typing import Any

import httpx


class CortexClient:
    """Thin httpx wrapper with bearer auth and retry logic."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST to Cortex API. Returns parsed JSON or raises on error."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}{path}",
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]

    async def get(self, path: str) -> dict[str, Any] | list[Any]:
        """GET from Cortex API. Returns parsed JSON or raises on error."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}{path}",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]


def get_client_from_env() -> CortexClient:
    """Create CortexClient from environment variables."""
    url = os.environ.get("CORTEX_URL", "http://192.168.1.12:8001")
    key = os.environ.get("CORTEX_API_KEY", "")
    return CortexClient(base_url=url, api_key=key)
