# Learnings — cortex-primary-refactor

## Project Overview
Refactoring agent-zero-cortex to make Cortex the PRIMARY memory backend for Agent Zero, with FAISS permanently retired.

## Key Architecture Decisions
- `_60_` prefix preserved (runs AFTER built-in `_memory` plugin's `_50_*` files)
- Pure-function library in `src/cortex_plugin/` — ZERO AZ-runtime imports
- Three Extension wrappers in `extensions/python/**/_60_cortex_*.py`
- Fence-strategy recall (same-project pool first, fill from cross-project)
- Two-tier timeout: 5s extraction phase + 10s posting phase
- `dirtyjson>=1.0.0` is the ONLY new runtime dependency allowed
- No `CortexClient` class — pure async functions in `http.py`
- No retry libraries — literal `for attempt in range(2)`

## Environment Variables (7 total)
1. CORTEX_URL (default: http://192.168.1.12:8001)
2. CORTEX_API_KEY (required)
3. CORTEX_ENABLED (default: true)
4. CORTEX_RECALL_LIMIT (default: 5)
5. CORTEX_RECALL_THRESHOLD (default: 0.02)
6. CORTEX_RECALL_LEGACY_RANK (default: false) — forward-compat escape hatch
7. CORTEX_PROMPT_DIR (default: unset = vendored)

## Hardcoded Constants (NOT env-configurable)
- EXTRACTION_TIMEOUT_SEC = 5
- POSTING_TIMEOUT_SEC = 10
- HTTP_TIMEOUT_SEC = 10
- RECALL_CANDIDATE_MULTIPLIER = 5
- RECALL_CANDIDATE_FLOOR = 30
- FRAGMENT_IMPORTANCE = 0.5
- SOLUTION_IMPORTANCE = 0.7
- RETRY_ATTEMPTS = 2
- RECALL_QUERY_MIN_CHARS = 3
- MAX_HISTORY_CHARS = 80000

## Cortex API Notes
- POST /v1/memories: required fields: content, kind, area; optional: source_session_id, source_project, importance
- POST /v1/recall: returns [{id, content, score, source_project, matched_via}] — NO area field
- RRF max scores ~0.05 (k=60 hardcoded)
- Cortex /v1/recall session_id/topic_ids filters IGNORED in current SQL — recall is global
- Synchronous embeddings on POST /v1/memories (~0.5–2s per memory)

## Test Architecture
- Layer 1 (unit): tests/unit/ — pure functions only, no AZ imports
- Layer 2 (wrapper): tests/wrapper/ — Extension class glue, uses conftest.py stub
- Layer 3 (integration): tests/integration/ — real Cortex, @pytest.mark.integration
- Default run skips integration tests (addopts = "-m 'not integration'")

## Deployment
- LXC 500 at root@192.168.1.5 (pct exec 500)
- AZ container: docker exec agent-zero
- Extensions path: /opt/agent-zero/data/python/extensions/
- Plugin path: /opt/agent-zero/data/usr/plugins/agent-zero-cortex/
- AZ web UI: typically http://192.168.1.12:50080

## Task 5: Dead Code Cleanup
- Deleted: client.py, default_config.yaml (unused, never consumed by code)
- Deleted: tests/test_init.py, tests/test_memorize.py, tests/test_recall_append.py, tests/test_skill_idempotency.py
  - These tested wrong shape (module-level execute() vs Extension class)
  - New test structure in tests/{unit,wrapper,integration} replaces them
- Preserved: tests/__init__.py (layer-package marker from T1)
- Note: Files were never committed to git (local untracked), so no git commit needed
- pytest --collect-only succeeds with 0 tests (expected — new tests in Wave 3)

## Task 7: idempotency_key Implementation (TDD)
- **Module**: `src/cortex_plugin/keys.py` — pure function, no AZ imports
- **Format**: `sha256(session_id|area|content)` UTF-8 encoded → hexdigest (64 chars)
- **Tests**: 8 cases in `tests/unit/test_keys.py` (all PASSED)
  - 64-char hex validation
  - Determinism (same inputs → same key)
  - Sensitivity to content, area, session_id changes
  - Empty content handling
  - Unicode (€, 日本語) via UTF-8 encoding
  - Format verification against manual SHA256
- **Commit**: `feat(lib): keys module with deterministic idempotency_key`
- **Key insight**: Matches Cortex's server-side `dedup_key` format exactly — safe for idempotent memory writes

## Task 9: Prompts Module (TDD)
- **Module**: `src/cortex_plugin/prompts.py` — loads vendored .md files with override hook
- **Tests**: 7 cases in `tests/unit/test_prompts.py` (all PASSED)
  - `load_fragments_prompt()` returns string starting with "# Assistant's job"
  - `load_solutions_prompt()` returns string mentioning "successful technical solutions"
  - Both functions cache results by (CORTEX_PROMPT_DIR, filename) tuple
  - Override via CORTEX_PROMPT_DIR env var works correctly
  - Falls back to vendored when override missing or invalid
  - Cache is cleared via `_clear_cache_for_tests()` helper
- **Implementation details**:
  - Manual dict cache keyed by (override_dir, filename) — no lru_cache
  - Lazy loading: prompts loaded on first call, not at module import
  - Vendored path: `Path(__file__).parent.parent.parent / "prompts" / filename`
  - Graceful fallback: catches FileNotFoundError, IsADirectoryError, PermissionError, OSError
  - Logs warning when override fails, then falls back silently
- **Constants**:
  - `_FRAGMENT_PROMPT_FILE = "memory.memories_sum.sys.md"`
  - `_SOLUTION_PROMPT_FILE = "memory.solutions_sum.sys.md"`
- **Commit**: `feat(lib): prompts module loads vendored .md files with override hook`
- **Key insight**: Prompts are plain markdown text files, not YAML or JSON — read as-is with no parsing

## Task 19: Recall Quality Integration Tests

- **Cortex forget API**: `POST /v1/memories` with `{"action": "forget", "memory_id": "<id>"}` — NOT `DELETE /v1/memories/{id}` (no DELETE endpoint exists)
- **Test isolation via run_tag**: embed a unique `T19RUN{uuid8}` token in each test's memory content; use that token as the query. BM25 exact-match ensures only current-run memories dominate recall results
- **threshold=0.0 returns everything**: even completely unrelated queries return vector-similar results at ~0.015 RRF score; use threshold=0.02 for "no match" assertions
- **Cleanup sweep**: recall with threshold=0.0 limit=200, forget each result, repeat until empty — typically 2-3 sweeps needed due to Cortex recall index update latency
- **fence_rerank tested via real data**: call POST /v1/recall with large limit, filter by ID set from current test, then apply fence_rerank locally — avoids parsing markdown output
