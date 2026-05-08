# Project Overview — agent-zero-cortex

## Purpose
Agent Zero plugin that mirrors every session's memory into the **Cortex** memory backend, running side-by-side with the existing FAISS plugin. FAISS is never touched — Cortex is additive only.

## Tech Stack
- Python 3.11+
- `httpx>=0.28` (async HTTP client for Cortex API calls)
- `pydantic>=2.9` (runtime dep, not heavily used in current code)
- `pytest` + `pytest-asyncio` (asyncio_mode=auto) for tests
- Build: `hatchling`
- No web framework — this is a plugin, not a server

## Deployment Target
Homelab: Proxmox LXC 500 running Agent Zero in Docker at `/opt/agent-zero/`.
Cortex API at `http://192.168.1.12:8001`.

## Key Constraint
`helpers.extension` (the AZ `Extension` base class) is an Agent Zero runtime module — **not available locally**. This causes 8/9 tests to fail with `ModuleNotFoundError` by design. Only `test_skill_idempotency.py` passes locally.
