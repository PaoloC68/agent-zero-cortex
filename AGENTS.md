# AGENTS.md — agent-zero-cortex

Agent Zero plugin that makes **Cortex** the primary memory backend. FAISS is permanently disabled — Cortex handles all memory extraction, storage, and recall.

---

## Repo layout

```
src/cortex_plugin/      # pure-function library — zero AZ-runtime imports
  http.py               # async HTTP helpers (post_memory, post_recall, post_session)
  keys.py               # idempotency_key: sha256(session_id|area|content)
  prompts.py            # load_fragments_prompt / load_solutions_prompt (vendored + override)
  recall.py             # fence_rerank: same-project pool first, fill from cross-project
  slug.py               # sanitize_slug: project name → [a-z0-9_-]
extensions/python/
  monologue_start/_60_cortex_init.py       # hook: session start → POST /v1/sessions
  monologue_end/_60_cortex_memorize.py     # hook: session end → extract + POST /v1/memories
  message_loop_prompts_after/_60_cortex_recall.py  # hook: recall → replace memories block
prompts/
  memory.memories_sum.sys.md   # vendored fragment extraction prompt
  memory.solutions_sum.sys.md  # vendored solution extraction prompt
scripts/
  calibrate-recall-threshold.sh  # score distribution helper for threshold tuning
plugin.yaml        # AZ plugin manifest
tests/
  unit/            # pure-function tests — no AZ imports, no live Cortex
  wrapper/         # Extension class glue tests — uses conftest.py helpers.extension stub
  integration/     # real Cortex tests — skipped by default (@pytest.mark.integration)
```

The `_60_` prefix is load-order critical: built-in `_memory` plugin uses `_50_*`, so Cortex always runs after it. The built-in FAISS plugin is disabled — its hooks still fire but produce no output.

---

## Dev setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -e ".[dev]"
```

Runtime deps (`httpx>=0.28`, `pydantic>=2.9`, `dirtyjson`) are in `requirements.txt`. Dev extras (`pytest`, `pytest-asyncio`, `pyyaml`) are in `pyproject.toml [project.optional-dependencies].dev`. The live container installs runtime deps automatically via `helpers/dependencies.py` on first extension load — no manual step needed there.

---

## Running tests

Tests are organized in three layers:

```bash
pytest tests/unit/ tests/wrapper/ -v   # unit + wrapper (default, no live Cortex needed)
pytest tests/unit/                     # pure-function tests only
pytest tests/wrapper/                  # Extension class glue tests only
pytest -m integration                  # real Cortex tests (requires live Cortex API)
```

**Three-layer pyramid:**
- `tests/unit/` — pure-function tests for `src/cortex_plugin/` modules; no AZ imports, no live Cortex
- `tests/wrapper/` — Extension class glue tests; `helpers.extension.Extension` stub vendored in `tests/wrapper/conftest.py`
- `tests/integration/` — real Cortex API tests; marked `@pytest.mark.integration`; skipped by default (`addopts = "-m 'not integration'"` in `pyproject.toml`)

`asyncio_mode = "auto"` is set in `pyproject.toml` — no `@pytest.mark.asyncio` needed on new tests.

---

## Extension contract

Each extension file must define an `execute` function (or a class inheriting `helpers.extension.Extension` with an `execute` method). AZ calls `execute(agent=..., loop_data=...)` — keyword args only.

- `agent.context.get_data("cortex_session_id")` / `set_data(...)` — how session ID is passed between extensions
- `loop_data.fragments`, `loop_data.solutions` — what memorize reads
- `loop_data.extras_persistent["memories"]` — where recall writes (full replacement with `## Cortex memories` block)

All extensions must be **non-fatal**: catch all exceptions, log a warning, and return without raising. AZ must continue with FAISS-only if Cortex is unreachable.

---

## Idempotency

Memory writes use `Idempotency-Key: sha256(session_id|area|content)`. Safe to replay. The FAISS migration in `SKILL.md` uses `sha256(project_slug|doc_id)`.

---

## Configuration (env vars, read on every call — no restart needed)

| Var | Default |
|-----|---------|
| `CORTEX_URL` | `http://192.168.1.12:8001` |
| `CORTEX_API_KEY` | *(required)* |
| `CORTEX_ENABLED` | `true` |
| `CORTEX_RECALL_LIMIT` | `5` |
| `CORTEX_RECALL_THRESHOLD` | `0.02` |
| `CORTEX_RECALL_LEGACY_RANK` | `false` |
| `CORTEX_PROMPT_DIR` | *(unset = vendored)* |

### Cortex Version Compatibility

Cortex's scoring algorithm changed at v1.1. The default threshold of `0.02` is calibrated for MVP (RRF) scoring. After upgrading Cortex, run `bash scripts/calibrate-recall-threshold.sh` and update `CORTEX_RECALL_THRESHOLD`. See `MIGRATION.md` for the full version compatibility matrix and threshold recommendations.

---

## Deployment (homelab — Proxmox LXC 500)

Extensions must be **copied** to AZ's runtime extension dirs — the plugin directory alone is not enough:

```
/opt/agent-zero/data/extensions/python/monologue_start/_60_cortex_init.py
/opt/agent-zero/data/extensions/python/monologue_end/_60_cortex_memorize.py
/opt/agent-zero/data/extensions/python/message_loop_prompts_after/_60_cortex_recall.py
```

Plugin toggle sentinel: `/opt/agent-zero/data/usr/plugins/agent-zero-cortex/.toggle-1` (must exist).

AZ restart is only needed when adding new env vars. Extension file updates and `CORTEX_ENABLED` changes take effect immediately (no restart).

---

## Coding conventions

- Python 3.11+, `from __future__ import annotations` in all files
- Use `logging` (not `print`) — logger name is `__name__`
- No classes unless genuinely needed (see `client.py` — `CortexClient` has state; extensions use the AZ `Extension` base class because AZ requires it)
- Functions over abstractions; keep extensions self-contained
- Tests use `unittest.mock` (AsyncMock/MagicMock) — no pytest fixtures, no factory libraries
