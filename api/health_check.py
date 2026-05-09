"""Health check handler for the Cortex plugin.

Runs 5 checks and returns structured results:
  - API reachable
  - DB ready
  - Write memory (and immediately forget)
  - Recall memory
  - Extensions wired (files exist and contain our code)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from helpers.api import ApiHandler, Request
from helpers import plugins

log = logging.getLogger(__name__)

PLUGIN_NAME = "agent-zero-cortex"

EXTENSION_PATHS = [
    "/a0/extensions/python/monologue_start/_60_cortex_init.py",
    "/a0/extensions/python/monologue_end/_60_cortex_memorize.py",
    "/a0/extensions/python/message_loop_prompts_after/_60_cortex_recall.py",
]


class HealthCheck(ApiHandler):

    async def process(self, input: dict, request: Request) -> dict:
        cfg = plugins.get_plugin_config(PLUGIN_NAME) or {}
        cortex_url = cfg.get("cortex_url", "http://192.168.1.12:8001").rstrip("/")
        api_key = cfg.get("cortex_api_key", "")
        headers = {"Authorization": f"Bearer {api_key}"}

        checks: list[dict[str, Any]] = []

        checks.append(await _check_api_reachable(cortex_url, headers))
        checks.append(await _check_db_ready(cortex_url, headers))
        checks.append(await _check_write_memory(cortex_url, headers))
        checks.append(await _check_recall_memory(cortex_url, headers))
        checks.append(_check_extensions_wired())

        all_ok = all(c["ok"] for c in checks)
        return {"ok": all_ok, "checks": checks, "all_ok": all_ok}


async def _check_api_reachable(url: str, headers: dict) -> dict:
    name = "API reachable"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{url}/healthz", headers=headers)
            resp.raise_for_status()
            data = resp.json()
        if data.get("status") == "ok":
            return {"name": name, "ok": True, "detail": "status=ok"}
        return {"name": name, "ok": False, "detail": f"unexpected response: {data}"}
    except Exception as exc:
        return {"name": name, "ok": False, "detail": str(exc)}


async def _check_db_ready(url: str, headers: dict) -> dict:
    name = "DB ready"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{url}/readyz", headers=headers)
            resp.raise_for_status()
            data = resp.json()
        if data.get("ready") is True and data.get("db") == "up":
            return {"name": name, "ok": True, "detail": "ready=true db=up"}
        return {"name": name, "ok": False, "detail": f"unexpected response: {data}"}
    except Exception as exc:
        return {"name": name, "ok": False, "detail": str(exc)}


async def _check_write_memory(url: str, headers: dict) -> dict:
    name = "Write memory"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            write_resp = await client.post(
                f"{url}/v1/memories",
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "content": "[HEALTH-CHECK] cortex plugin health probe",
                    "kind": "fragment",
                    "area": "fragments",
                    "source_session_id": "health-check",
                    "importance": 0.1,
                },
            )
            write_resp.raise_for_status()
            memory_id = write_resp.json().get("id", "")
            short_id = str(memory_id)[:8]

            forget_resp = await client.post(
                f"{url}/v1/memories",
                headers={**headers, "Content-Type": "application/json"},
                json={"action": "forget", "memory_id": str(memory_id)},
            )
            forget_resp.raise_for_status()

        return {
            "name": name,
            "ok": True,
            "detail": f"written id={short_id}... forgotten",
        }
    except Exception as exc:
        return {"name": name, "ok": False, "detail": str(exc)}


async def _check_recall_memory(url: str, headers: dict) -> dict:
    name = "Recall memory"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{url}/v1/recall",
                headers={**headers, "Content-Type": "application/json"},
                json={"query": "cortex plugin health", "limit": 3, "threshold": 0.0},
            )
            resp.raise_for_status()
            results = resp.json()
        count = len(results) if isinstance(results, list) else 0
        return {"name": name, "ok": True, "detail": f"returned {count} results"}
    except Exception as exc:
        return {"name": name, "ok": False, "detail": str(exc)}


def _check_extensions_wired() -> dict:
    name = "Extensions wired"
    missing: list[str] = []
    wrong_code: list[str] = []

    for path_str in EXTENSION_PATHS:
        p = Path(path_str)
        if not p.exists():
            missing.append(p.name)
            continue
        content = p.read_text(errors="replace")
        if "get_plugin_config" not in content:
            wrong_code.append(p.name)

    if missing:
        return {
            "name": name,
            "ok": False,
            "detail": f"missing: {', '.join(missing)}",
        }
    if wrong_code:
        return {
            "name": name,
            "ok": False,
            "detail": f"old env-var code in: {', '.join(wrong_code)}",
        }
    return {"name": name, "ok": True, "detail": "all 3 files present and use get_plugin_config"}
