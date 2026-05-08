# Code Style & Conventions — agent-zero-cortex

## Python Version & Imports
- Python 3.11+
- `from __future__ import annotations` at the top of every file
- Standard library imports first, then third-party

## Logging
- Always use `logging`, never `print`
- Logger per module: `logger = logging.getLogger(__name__)`
- Log format: `"cortex_init: session created {id} for project {slug}"` (module prefix in message)

## Classes vs Functions
- Use classes only when genuinely needed (stateful objects or when AZ requires it)
- Extensions inherit `helpers.extension.Extension` because AZ requires it — not by choice
- `CortexClient` in `client.py` is a class because it holds state (base_url, api_key, timeout)
- Helper logic (slug sanitization, idempotency key generation) is plain functions

## Error Handling
- All extensions must be **non-fatal**: wrap entire body in `try/except Exception`, log warning, return
- Never let an exception propagate out of an extension — AZ must continue with FAISS-only

## Type Hints
- Full type hints on all function signatures
- Return types always annotated
- Use `dict[str, Any]` not `Dict[str, Any]` (Python 3.11+ built-in generics)

## Idempotency Keys
- Runtime writes: `sha256(session_id|area|content)`
- SKILL.md migration: `sha256(project_slug|doc_id)`
- Always passed as `Idempotency-Key` HTTP header

## Slug Sanitization
- Project names → `[a-z0-9_-]` only, max 64 chars
- Regex: `re.compile(r"[^a-z0-9_-]")`, replace with `_`, lowercase

## Tests
- Three-layer pyramid:
  - `tests/unit/` — pure-function tests for `src/cortex_plugin/`; no AZ imports, no live Cortex
  - `tests/wrapper/` — Extension class glue tests; `helpers.extension.Extension` stub vendored in `tests/wrapper/conftest.py`
  - `tests/integration/` — real Cortex API tests; marked `@pytest.mark.integration`; skipped by default
- `unittest.mock` only (AsyncMock, MagicMock, patch) — no pytest fixtures, no factory libraries
- Env vars set at module level in test files (before imports)
- `asyncio_mode = "auto"` in pyproject.toml — no `@pytest.mark.asyncio` needed on new tests

## No Linter/Formatter Config
No ruff, black, flake8, or mypy configured. Follow existing style manually.
