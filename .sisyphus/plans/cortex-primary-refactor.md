# Cortex Primary Memory Refactor

> **Cortex Compatibility**: Designed to remain functional across Cortex MVP (current), **v1.1 cognitive** (composite rerank, Reflector, supersession), **v2.0 substrate** (PG18, TimescaleDB, MCP), and **v2.1 scale** (DiskANN tuning). Server-side scoring algorithm changes are absorbed via `CORTEX_RECALL_LEGACY_RANK` escape hatch + a threshold-calibration utility (T15.5). Reflector-driven memory mutations (merge/supersede) are tolerated by design — recall surfaces canonical (post-merge) memories.

## TL;DR

> **Quick Summary**: Refactor `agent-zero-cortex` so Cortex (`/Users/paolo/Documents/Projects/cortex-memory`) is the PRIMARY memory backend for Agent Zero, with FAISS permanently retired. Plugin gains independent fragment+solution extraction (own LLM call), three-layer test pyramid (unit/wrapper/integration), pure-function library architecture, fence-based same-project recall priority, and forward-compatibility with Cortex v1.1+ scoring evolution.
>
> **Deliverables**:
> - Pure-function library `src/cortex_plugin/` (slugs, keys, config, prompts, http, extraction, recall)
> - Three Extension wrappers in `extensions/python/**/_60_cortex_*.py` (kept `_60_` prefix to win hook ordering vs built-in `_memory`)
> - Vendored extraction prompts in `prompts/`
> - Three-layer test pyramid: unit (pure functions), wrapper (Extension class glue), integration (real Cortex)
> - **Forward-compat layer**: `CORTEX_RECALL_LEGACY_RANK` env var (escape hatch for v1.1 composite scoring), threshold calibration script (`scripts/calibrate-recall-threshold.sh`), version compatibility integration tests
> - Updated `README.md`, renamed `SKILL.md` → `MIGRATION.md` (with Cortex version compatibility matrix), updated `AGENTS.md` and `.serena` memories
> - Removed dead code: `client.py`, `default_config.yaml`, all 4 existing test files, FAISS coupling code, `CORTEX_MERGE_STRATEGY` and `CORTEX_FAISS_ASSERTION_CHECK` env vars
>
> **Estimated Effort**: Large (24 implementation tasks + 4 final review tasks)
> **Parallel Execution**: YES — 4 waves, max 7 concurrent tasks
> **Critical Path**: T2 (verification spike) → T11 (extraction.py) → T15 (memorize wrapper) → T18 (integration memorize roundtrip) → F1-F4 → user okay

---

## Context

### Original Request
> "I need a serious plan to refactor this plugin and make working cortex-memory (`/Users/paolo/Documents/Projects/cortex-memory`) as primary memory for agent-zero. The system needs to be reliable and efficient. The test complete and exhaustive. The FAISS plugin is disabled, cortex must be reliable."

### Current Broken State
- FAISS plugin disabled since May 3, 2026
- `_60_cortex_memorize.py` reads `loop_data.fragments` and `loop_data.solutions` — these are populated by FAISS plugin's LLM extraction
- With FAISS disabled, those fields are empty → no memories written for ~5 days
- Recall threshold default `0.7` was 14× too high; user already corrected to `0.01` in deployment

### Interview Summary
**Round 1 decisions**: Single combined memorize extension; replace `extras['memories']` cleanly; hybrid project priority (revised to fence below); pure-function design + full mocking + integration suite; retry-once on extraction failure; two memories per solution; vendor prompts + override hook; awaited 15s timeout; TDD strict; topic-lock per project; project-less = no tag/no lock/no filter.

**Round 2 critical revisions** (from Metis + Oracle):
- **Cross-linking IMPOSSIBLE**: Cortex API has no metadata field → DROP cross-link, two independent memories
- **`_50_` prefix unsafe**: alphabetic ordering vs built-in `_memory` plugin would let built-in overwrite our work → KEEP `_60_`
- **1.5× boost mathematically inadequate**: cross-project 0.10 still beats same-project 0.05×1.5=0.075 → use FENCE (split-pool) strategy
- **15s monolithic timeout**: too tight given sync embeddings → split into 5s extraction phase + 10s posting phase
- **Existing tests test wrong shape**: call `execute()` as module function but real AZ instantiates `Cls(agent).execute()` → DELETE all 4 files, rewrite

### Research Findings (high-signal)
- **Cortex `/v1/recall` accepts `session_id`/`topic_ids` filters but IGNORES them in current SQL** — recall is global today; cross-project bleed is real
- **Cortex synchronous embeddings** on `POST /v1/memories` (~0.5–2s per memory)
- **RRF max scores ~0.05** (constant 60 hardcoded in Cortex backend)
- **AZ exposes `agent.call_utility_model(system, message)` and `agent.concat_messages(agent.history)`** — building blocks for independent extraction
- **AZ files load alphabetically by filename**, first-occurrence-wins per filename across plugins
- **`loop_data.extras_persistent`** is the agreed prompt-augmentation channel (survives across iterations)
- **Built-in `_memory` is `always_enabled: true`** — toggle file may not actually disable it; gating likely via `memory_*_enabled` settings (verification spike required)
- **963 migrated FAISS memories** likely have `area="main"` (migration default); must NOT filter `area="main"` out at recall
- **`dirtyjson` library** is the JSON parser used by upstream `_memory` (via AZ's `helpers.dirty_json` wrapper). For our standalone plugin we depend on the upstream `dirtyjson` package directly via `dirtyjson.loads(text)` — same library, no wrapper needed. (The package API is `loads`/`load`, NOT `parse_string`.)
- **Sleep mode** at 3 AM UTC nightly: dedup near-duplicates ≥0.95 cos sim, importance decay ×0.99
- **Server-side dedup**: `sha256(source_session_id|area|content)` BYTEA on `memory_items.dedup_key`

### Metis + Oracle Pre-Plan Review
**Identified gaps** (addressed in plan below):
- Coexistence with `_memory` plugin (added Wave-1 verification spike)
- 15s timeout vs sync-embedding reality (split into two-tier budget)
- Project boost mathematically inadequate (replaced with fence strategy)
- Test layering risk (codified strict non-overlap rule)
- Hot-reload uncertainty (plan documents stop→swap→start)
- Stale-project mid-session (added recompute-and-rebind logic)
- Logging contract (one INFO line per fire, structured key=val)
- Rollback story (pre-refactor commit tag)

---

## Work Objectives

### Core Objective
Make `agent-zero-cortex` self-sufficient as Agent Zero's primary memory backend. Eliminate dependency on FAISS plugin's internal data flow. Provide reliable, observable, locally-testable behavior.

### Concrete Deliverables
- `src/cortex_plugin/` — pure-function library (7 modules)
- `extensions/python/{monologue_start,monologue_end,message_loop_prompts_after}/_60_cortex_*.py` — three thin Extension wrappers (rewritten)
- `prompts/{memory.memories_sum.sys.md,memory.solutions_sum.sys.md}` — vendored extraction prompts (verbatim copy from upstream AZ `_memory` plugin commit `2613fac0`)
- `tests/unit/`, `tests/wrapper/`, `tests/integration/` — three-layer test pyramid
- `tests/wrapper/conftest.py` — vendored `helpers.extension.Extension` stub for wrapper tests
- `MIGRATION.md` (renamed from `SKILL.md`) with rollback procedure
- Updated `README.md` (Cortex-primary architecture, no "side-by-side" framing)
- Updated `AGENTS.md` and `.serena/memories/` to reflect new architecture
- Updated `pyproject.toml` (no new runtime deps; test deps unchanged)

### Definition of Done
- [ ] All unit tests pass: `pytest tests/unit/ -v` exit 0
- [ ] All wrapper tests pass: `pytest tests/wrapper/ -v` exit 0
- [ ] All integration tests pass against real Cortex: `pytest tests/integration/ -v -m integration` exit 0 (with `CORTEX_URL` and `CORTEX_API_KEY` set) — this includes T17, T18, T19, AND T19.5 (forward-compat)
- [ ] **Calibration script runs end-to-end**: `bash scripts/calibrate-recall-threshold.sh` exits 0 with valid JSON output at `.sisyphus/evidence/calibration/threshold-recommendation-*.json`
- [ ] No dead code: `test ! -f client.py && test ! -f default_config.yaml` exits 0
- [ ] `_60_` extensions exist; no `_50_cortex_*.py` files: `ls extensions/python/monologue_end/_60_cortex_memorize.py extensions/python/monologue_start/_60_cortex_init.py extensions/python/message_loop_prompts_after/_60_cortex_recall.py` succeeds
- [ ] Pure-function lib has zero AZ-runtime imports: `! grep -rE "(from helpers|import helpers|from agent|import agent\b)" src/cortex_plugin/`
- [ ] **All 7 env vars** in config: `python -c "from cortex_plugin.config import load_config; c = load_config(); assert hasattr(c, 'recall_legacy_rank')"`
- [ ] **Cortex Version Compatibility documented**: `grep -c "MVP\|v1.1\|v2.0\|v2.1" MIGRATION.md` returns ≥4
- [ ] Live deployment to LXC 500 confirmed: a fresh AZ session writes ≥1 memory verifiable via `POST /v1/recall` body `{"query": "<unique-marker-XYZQ-T22-2026>", "limit": 5, "threshold": 0.0}` returning a result whose `content` contains the unique marker (manual command in MIGRATION.md, executed via SSH from agent). Cortex API has no `GET /v1/memories` endpoint — recall with a high-cardinality marker is the canonical readback path.

### Must Have
- Independent fragment + solution extraction via `agent.call_utility_model` + `agent.concat_messages` + vendored prompts
- Two-tier timeout: 5s extraction phase, 10s posting phase, partial-success acceptance with idempotency-safe replay
- Fence-strategy recall: take from same-project pool first, fill from cross-project pool
- `_60_` extension prefix preserved (run AFTER built-in to win extras race)
- Three-layer test pyramid with strict non-overlap (unit asserts pure logic, wrapper asserts AZ glue, integration asserts wire shape)
- One `INFO` log per extension fire with structured `key=val` format
- Pre-refactor commit tagged `pre-cortex-primary-v1`; rollback procedure in MIGRATION.md

### Must NOT Have (Guardrails — from Metis review)
- ❌ NO new HTTP-wrapper class to replace `client.py` (pure functions inline `httpx.AsyncClient`)
- ❌ NO new env vars beyond the documented **seven** (`CORTEX_URL`, `CORTEX_API_KEY`, `CORTEX_ENABLED`, `CORTEX_RECALL_LIMIT`, `CORTEX_RECALL_THRESHOLD`, `CORTEX_PROMPT_DIR`, `CORTEX_RECALL_LEGACY_RANK`); all other knobs are hardcoded constants in `config.py`. The seventh var (`CORTEX_RECALL_LEGACY_RANK`) is the **forward-compat escape hatch** for Cortex v1.1+ scoring-algorithm changes; without it, threshold mis-calibration could silently degrade recall quality with no rollback path. This is the single guardrail-relaxation justified by Cortex version evolution.
- ❌ NO retry libraries (`tenacity`, `backoff`) — literal `for attempt in range(2)` for the single retry
- ❌ NO structured-logging library, OpenTelemetry, or trace IDs — `logger.info`/`warning` only
- ❌ NO Pydantic for internal data — TypedDict or plain dict; Pydantic only at HTTP boundary if at all (none currently planned)
- ❌ NO module-level globals or singletons (except `functools.lru_cache` for prompt loading)
- ❌ NO yaml parsing in extension files — pure-function lib loads prompts
- ❌ NO improvements to extraction prompts during refactor (vendored byte-identical to AZ commit `2613fac0`; tuning is a separate PR)
- ❌ NO scope creep refactors: pyproject.toml dependency bumps (e.g., raising `httpx>=0.28` to a newer version), httpx version changes, "modernizing" type hints
- ✅ EXCEPTION: `dirtyjson>=1.0.0` is the **only new runtime dependency** explicitly allowed by this refactor (added in T11). It is required for tolerant LLM-output JSON parsing (matching upstream AZ `_memory` behavior). T11's pyproject.toml edit is the only allowed dependency addition; no other new runtime deps may be introduced.
- ❌ NO modifying `cortex-memory` repo (server-side changes are out of scope)
- ❌ NO running FAISS migration during this refactor (`MIGRATION.md` is doc-only)
- ❌ NO patching/forking AZ's `_memory` plugin (if can't be silenced, plan halts and user decides)
- ❌ NO duplicate behavioral assertions across test layers (unit asserts logic, wrapper asserts glue, integration asserts wire — exclusive concerns)
- ❌ NO pytest fixtures, factory libraries, or testcontainers (unittest.mock only)
- ❌ NO premature abstractions or inheritance hierarchies — pure functions over classes (per CLAUDE.md "Stop Writing Classes")
- ❌ NO conftest.py for unit tests (pure functions don't need stub)
- ❌ NO area-aware recall promise (Cortex `/v1/recall` returns no `area` field; document limitation)
- ❌ NO filtering `area="main"` out at recall (would exclude 963 migrated memories)
- ❌ NO cross-link metadata in memory writes (Cortex API has no metadata field)

### Environment Variable Matrix (7 vars total)

| Var | Default | Purpose |
|-----|---------|---------|
| `CORTEX_URL` | `http://192.168.1.12:8001` | API base URL |
| `CORTEX_API_KEY` | required | Bearer token |
| `CORTEX_ENABLED` | `true` | Master kill switch |
| `CORTEX_RECALL_LIMIT` | `5` | Final result count after fence rerank |
| `CORTEX_RECALL_THRESHOLD` | `0.02` | Score floor — **calibration depends on Cortex scoring algorithm** (see compatibility matrix below). Tune via `scripts/calibrate-recall-threshold.sh` (T15.5) after each Cortex version upgrade. |
| `CORTEX_RECALL_LEGACY_RANK` | `false` | **Forward-compat escape hatch.** When `true`, plugin appends `?legacy_rank=true` to `/v1/recall` requests, forcing Cortex v1.1+ to return pre-v1.1 RRF ordering (one-release backward compat per Cortex v1.1 spec line 116). Use as emergency rollback if composite scoring degrades quality unexpectedly post-upgrade. |
| `CORTEX_PROMPT_DIR` | (unset = vendored) | Override directory for extraction prompt files |

**Hardcoded constants in `src/cortex_plugin/config.py`** (NOT env-configurable per "no new env vars" guardrail):
- `EXTRACTION_TIMEOUT_SEC = 5`, `POSTING_TIMEOUT_SEC = 10`, `HTTP_TIMEOUT_SEC = 10`
- `RECALL_CANDIDATE_MULTIPLIER = 5`, `RECALL_CANDIDATE_FLOOR = 30`
- `FRAGMENT_IMPORTANCE = 0.5`, `SOLUTION_IMPORTANCE = 0.7`
- `RETRY_ATTEMPTS = 2`, `RECALL_QUERY_MIN_CHARS = 3`, `MAX_HISTORY_CHARS = 80000`

### Cortex Version Compatibility Matrix

| Cortex Version | Scoring Algorithm | Score Range | Recommended `CORTEX_RECALL_THRESHOLD` | `CORTEX_RECALL_LEGACY_RANK`? |
|----------------|-------------------|-------------|---------------------------------------|------------------------------|
| **MVP** (current) | RRF (k=60) | ~0.01–0.05 | `0.02` | `false` (param ignored by server) |
| **v1.1 cognitive** | Composite: `0.5·semantic + 0.3·recency + 0.2·importance` | ~0.10–0.95 | `0.30`–`0.50` (calibrate via T15.5) | `false` by default. Set `true` only as emergency rollback if quality regresses |
| **v2.0 substrate** | Same as v1.1 (PG18 + TimescaleDB + MCP — no scoring change) | Same as v1.1 | Same as v1.1 | Same as v1.1 |
| **v2.1 scale** | Same as v1.1 (DiskANN tuning is index-internal, not scoring-algorithm) | Same as v1.1 | Same as v1.1 (re-run T15.5 if recall@10 shifts ≥0.02) | Same as v1.1 |

**Calibration procedure**:
1. After every Cortex version upgrade (or scoring-algorithm change), run `scripts/calibrate-recall-threshold.sh` (built in T15.5) against live Cortex.
2. Script measures score distribution on a fixed golden query set (~50 queries spanning relevant + irrelevant intent).
3. Outputs recommended `CORTEX_RECALL_THRESHOLD` value (5th-percentile relevant-match score).
4. Update `CORTEX_RECALL_THRESHOLD` in deployment env (no code change). Restart not required — extensions read env on every call.
5. If quality regresses post-upgrade, set `CORTEX_RECALL_LEGACY_RANK=true` as immediate mitigation; re-calibrate later.

### Reflector Mutation Awareness (Cortex v1.1+)

**Behavior change in v1.1**: The Cortex Reflector (sleep-mode background process) may MERGE near-duplicate memories or SUPERSEDE older versions. Memories we POST may be auto-modified server-side after sleep mode (~3 AM UTC nightly).

**Implications for our plugin**:
- ✅ **Idempotency-key replay still works**: Our `sha256(session_id|area|content)` key, when replayed, returns the existing/merged memory ID. No duplicate writes.
- ✅ **Recall surfaces canonical version**: v1.1 T16 filters `superseded_at IS NOT NULL` results out. Our recall block contains only canonical (post-merge) content.
- ⚠️ **Memory ID discontinuity**: If we cache a memory ID locally (we don't, but if we did), it could become invalid post-merge. Our plugin holds no memory IDs across calls; we're safe.
- ⚠️ **Content drift**: If we POST "User likes coffee" and later POST "User prefers coffee", Reflector may merge into "User likes/prefers coffee". Our recall returns the merged version. **This is intended Cortex behavior**, not a bug. Document in `MIGRATION.md`.

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.
> Acceptance criteria requiring "user manually tests/confirms" are FORBIDDEN.

### Test Decision
- **Infrastructure exists**: YES (pytest + pytest-asyncio with `asyncio_mode=auto`)
- **Automated tests**: YES — TDD strict (RED → GREEN → REFACTOR per task)
- **Framework**: pytest 8.3+, pytest-asyncio 0.24+ (already in `pyproject.toml [project.optional-dependencies] dev`)
- **Layer 1 — Unit** (`tests/unit/`): tests `src/cortex_plugin/*.py` only. Imports only from `cortex_plugin` and stdlib + `unittest.mock`. ZERO imports of `helpers.*`, `agent.*`, or `extensions.*`. Mocks `httpx.AsyncClient` and `utility_call`.
- **Layer 2 — Wrapper** (`tests/wrapper/`): tests `extensions/python/**/_60_*.py`. Instantiates the actual `Extension` subclass via `Cls(agent=fake_agent).execute(loop_data=fake_loop)`. Uses vendored `helpers.extension.Extension` stub from `tests/wrapper/conftest.py`. Asserts ONLY: pure function called with right args, exceptions suppressed, `set_data`/`get_data` happens, `extras_persistent` mutated. Mocks the pure-function module.
- **Layer 3 — Integration** (`tests/integration/`): real `httpx` against live Cortex. Uses pytest marker `@pytest.mark.integration`. Skipped by default (`pyproject.toml [tool.pytest.ini_options] addopts = "-m 'not integration'"`). Run with `pytest -m integration`. ≤5 tests covering happy paths and one critical failure mode.

### QA Policy
Every implementation task MUST include agent-executed QA scenarios using:
- **Bash + bun/python REPL** (this is a Python plugin; no UI)
- **Bash + curl** (for Cortex HTTP integration tests)
- **pytest** (for all test layers)
- **SSH to LXC 500** (for live deployment verification only — final wave)

Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{txt|json}`.

---

## Execution Strategy

### Parallel Execution Waves

> Maximize throughput. Each wave completes before the next begins.

```
Wave 1 (Foundation & Verification — start immediately, max parallel):
├── Task 1:  Pre-refactor commit tag + scaffold dirs           [quick]
├── Task 2:  SPIKE — verify _memory silencing                   [unspecified-high]
├── Task 3:  SPIKE — measure Cortex POST latency baseline       [unspecified-high]
├── Task 4:  Vendor extraction prompts (verbatim from upstream) [quick]
└── Task 5:  Delete dead code + old tests                       [quick]

Wave 2 (Pure-Function Library — TDD, parallel after T1):
├── Task 6:  src/cortex_plugin/slugs.py + tests                 [quick]
├── Task 7:  src/cortex_plugin/keys.py + tests                  [quick]
├── Task 8:  src/cortex_plugin/config.py + tests                [quick]
├── Task 9:  src/cortex_plugin/prompts.py + tests (depends T4)  [quick]
├── Task 10: src/cortex_plugin/http.py + tests                  [unspecified-high]
├── Task 11: src/cortex_plugin/extraction.py + tests (deps T9)  [deep]
└── Task 12: src/cortex_plugin/recall.py + tests (fence)        [deep]

Wave 3 (Extension Wrappers — TDD, parallel after Wave 2):
├── Task 13: tests/wrapper/conftest.py with Extension stub      [quick]
├── Task 14: _60_cortex_init.py rewrite + wrapper test          [unspecified-high]
├── Task 15: _60_cortex_memorize.py rewrite + wrapper test      [deep]
└── Task 16: _60_cortex_recall.py rewrite + wrapper test        [deep]

Wave 4 (Integration, Forward-Compat, & Docs — parallel after Wave 3):
├── Task 15.5: scripts/calibrate-recall-threshold.sh utility     [unspecified-high]  NEW (forward-compat)
├── Task 17:  Integration test — session lifecycle               [unspecified-high]
├── Task 18:  Integration test — memorize roundtrip              [unspecified-high]
├── Task 19:  Integration test — recall quality + fence          [unspecified-high]
├── Task 19.5: Integration test — Cortex v1.1+ forward-compat   [unspecified-high]  NEW (forward-compat)
├── Task 20:  Update README.md (Cortex-primary architecture)     [writing]
├── Task 21:  Rename SKILL.md → MIGRATION.md + rollback + compat [writing]
└── Task 22:  Update plugin.yaml + AGENTS.md + .serena memories  [writing]

Wave FINAL (After ALL tasks — 4 parallel reviews, then user okay):
├── F1: Plan compliance audit         (oracle)
├── F2: Code quality review           (unspecified-high)
├── F3: Real manual QA + live deploy  (unspecified-high)
└── F4: Scope fidelity check          (deep)
→ Present consolidated results → wait for explicit user okay
```

### Dependency Matrix
- **T1**: blocks all other work; T2-T5 can start once T1 completes
- **T2**: BLOCKING SPIKE — if `_memory` cannot be silenced, plan halts and user decides
- **T3**: informational SPIKE — informs whether 5s/10s budget is realistic
- **T4** → T9 (prompts module loads vendored files)
- **T6, T7, T8, T10**: independent within Wave 2
- **T9** → T11 (extraction.py uses `prompts.load`)
- **T6** → T11, T15 (slugs used by extraction context, by memorize wrapper)
- **T7** → T11, T15 (keys used by memorize POST payload)
- **T8** → all of Wave 2 + Wave 3 (config used everywhere)
- **T11** → T15 (memorize wrapper calls extraction)
- **T12** → T16 (recall wrapper calls fence rerank)
- **T10** → T11, T12, T14, T15, T16 (HTTP primitives)
- **T13** → T14, T15, T16 (wrapper tests need stub)
- **T14, T15, T16** → T17, T18, T19, T19.5 (wrappers must exist before integration)
- **T8, T10, T12** → T15.5 (calibration script needs config + http + recall lib)
- **T8, T12, T16** → T19.5 (forward-compat test needs config with new var, recall with legacy_rank, wrapper plumbing)
- **All implementation tasks** → Wave FINAL

### Agent Dispatch Summary
- **Wave 1** (5 tasks): T1, T4, T5 → `quick`; T2, T3 → `unspecified-high` (need real env access)
- **Wave 2** (7 tasks): T6, T7, T8, T9 → `quick`; T10 → `unspecified-high`; T11, T12 → `deep` (complex logic)
- **Wave 3** (4 tasks): T13 → `quick`; T14 → `unspecified-high`; T15, T16 → `deep`
- **Wave 4** (8 tasks): T15.5, T17, T18, T19, T19.5 → `unspecified-high` (real Cortex calls); T20, T21, T22 → `writing`
- **Wave FINAL** (4 tasks): F1 → `oracle`; F2, F3 → `unspecified-high`; F4 → `deep`

---

## TODOs

> Implementation + Test = ONE Task. Never separate.
> EVERY task MUST have: Recommended Agent Profile + Parallelization info + QA Scenarios.
> **A task WITHOUT QA Scenarios is INCOMPLETE. No exceptions.**

- [x] 1. **Pre-refactor commit tag + scaffold directories**

  **What to do**:
  - Tag the current `HEAD` commit as `pre-cortex-primary-v1` via `git tag pre-cortex-primary-v1` (no `-a`, lightweight tag is sufficient for rollback anchor)
  - Create directory tree: `mkdir -p src/cortex_plugin prompts tests/unit tests/wrapper tests/integration .sisyphus/evidence`
  - Create empty `src/cortex_plugin/__init__.py`, `tests/__init__.py`, `tests/unit/__init__.py`, `tests/wrapper/__init__.py`, `tests/integration/__init__.py` (empty `__init__.py` for package discovery)
  - Update `pyproject.toml` `[tool.pytest.ini_options]` to add `markers = ["integration: real-Cortex tests, run with -m integration"]` and `addopts = "-m 'not integration'"` (skip integration by default)
  - Add `src/` to `pyproject.toml` build config: `[tool.hatch.build.targets.wheel] packages = ["src/cortex_plugin"]`
  - **Editable install required for imports to resolve**: run `pip install -e ".[dev]"` from repo root. This makes `from cortex_plugin.X import ...` work in tests and runtime. Without this step, ALL subsequent unit/wrapper tests fail with `ModuleNotFoundError: cortex_plugin`. Verify via `python -c "import cortex_plugin; print(cortex_plugin.__file__)"` outputting a path inside `src/cortex_plugin/`.

  **Must NOT do**:
  - Don't tag with `-a -m` annotated tags — lightweight tag is intentional for rollback simplicity
  - Don't add new dev dependencies beyond what already exists
  - Don't modify `pyproject.toml [project] dependencies` (no new runtime deps)
  - Don't create any other files yet (subsequent tasks own their own files)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Trivial directory creation + tag; no business logic
  - **Skills**: `[]`
    - No domain skills needed for git tagging and `mkdir`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1, but blocks all other Wave 1 tasks (provides scaffolding)
  - **Blocks**: Tasks 2, 3, 4, 5 (all need the directory tree)
  - **Blocked By**: None — start immediately

  **References**:

  **Pattern References**:
  - `pyproject.toml:1-24` — current build/test config style; preserve hatchling layout

  **API/Type References**:
  - None for this task

  **Test References**:
  - None for this task (no tests in this task)

  **External References**:
  - pytest markers docs: `https://docs.pytest.org/en/stable/example/markers.html` — for the `markers` config block

  **WHY Each Reference Matters**:
  - `pyproject.toml:1-24` shows the existing structure; keep `[build-system]` and `[project]` blocks unchanged

  **Acceptance Criteria**:

  - [ ] `git tag --list pre-cortex-primary-v1` outputs `pre-cortex-primary-v1`
  - [ ] All directories exist: `test -d src/cortex_plugin && test -d prompts && test -d tests/unit && test -d tests/wrapper && test -d tests/integration && test -d .sisyphus/evidence`
  - [ ] `pyproject.toml` contains `markers = ["integration: ...]` and `addopts = "-m 'not integration'"`
  - [ ] Editable install succeeded: `python -c "import cortex_plugin; print(cortex_plugin.__file__)"` outputs a path containing `src/cortex_plugin/__init__.py`
  - [ ] `python -m pytest --collect-only -q` succeeds (no test collection errors)

  **QA Scenarios**:

  ```
  Scenario: Tag, scaffolding, and editable install succeed
    Tool: Bash
    Preconditions: Repo at clean HEAD; no untracked files in src/, tests/unit, tests/wrapper, tests/integration; venv active
    Steps:
      1. Run `git tag pre-cortex-primary-v1`
      2. Run `mkdir -p src/cortex_plugin prompts tests/unit tests/wrapper tests/integration .sisyphus/evidence`
      3. Run `touch src/cortex_plugin/__init__.py tests/__init__.py tests/unit/__init__.py tests/wrapper/__init__.py tests/integration/__init__.py`
      4. Edit pyproject.toml to add markers, addopts, and `[tool.hatch.build.targets.wheel] packages = ["src/cortex_plugin"]` as specified
      5. Run `pip install -e ".[dev]" 2>&1 | tee .sisyphus/evidence/task-1-install.txt`
      6. Run `python -c "import cortex_plugin; print(cortex_plugin.__file__)" | tee .sisyphus/evidence/task-1-import.txt`
      7. Run `git tag --list pre-cortex-primary-v1 | tee .sisyphus/evidence/task-1-tag.txt`
      8. Run `ls -la src/cortex_plugin tests/unit tests/wrapper tests/integration | tee .sisyphus/evidence/task-1-dirs.txt`
      9. Run `python -m pytest --collect-only -q | tee .sisyphus/evidence/task-1-collect.txt`
    Expected Result: tag list contains pre-cortex-primary-v1; install.txt shows successful editable install; import.txt outputs a path containing `src/cortex_plugin`; all dirs listed; pytest collects 0 tests (or only the existing test_skill_idempotency.py if T5 hasn't run yet) without errors
    Failure Indicators: tag missing, dir missing, install failed, import error, pytest collection errors
    Evidence: .sisyphus/evidence/task-1-install.txt, task-1-import.txt, task-1-tag.txt, task-1-dirs.txt, task-1-collect.txt

  Scenario: Integration marker is honored (negative — runs aren't accidentally collecting)
    Tool: Bash
    Preconditions: pyproject.toml updated with markers + addopts
    Steps:
      1. Run `python -m pytest -v 2>&1 | tee .sisyphus/evidence/task-1-default-run.txt`
      2. Confirm output mentions "no tests collected" or only collects pre-existing non-integration tests
      3. Run `python -m pytest -v -m integration 2>&1 | tee .sisyphus/evidence/task-1-integration-run.txt`
      4. Confirm output mentions "no tests collected" (integration tests don't exist yet — expected)
    Expected Result: default run skips integration; explicit `-m integration` finds nothing yet
    Evidence: .sisyphus/evidence/task-1-default-run.txt, .sisyphus/evidence/task-1-integration-run.txt
  ```

  **Evidence to Capture**:
  - [ ] `task-1-tag.txt`, `task-1-dirs.txt`, `task-1-collect.txt`, `task-1-default-run.txt`, `task-1-integration-run.txt`

  **Commit**: YES (groups standalone)
  - Message: `chore: tag pre-refactor commit and scaffold cortex-primary directories`
  - Files: `pyproject.toml`, `src/cortex_plugin/__init__.py`, `tests/__init__.py`, `tests/unit/__init__.py`, `tests/wrapper/__init__.py`, `tests/integration/__init__.py`
  - Pre-commit: `python -m pytest --collect-only -q`

- [x] 2. **🔴 BLOCKING SPIKE — Verify `_memory` plugin can be silenced**

  **What to do**:
  - SSH to LXC 500 (root@192.168.1.5 → `pct exec 500`) and locate AZ's `_memory` plugin: `ls /opt/agent-zero/data/python/extensions/monologue_end/`
  - Identify which `_50_*.py` and `_51_*.py` files belong to `_memory` plugin (likely `_50_memorize_fragments.py`, `_51_memorize_solutions.py`, plus a recall extension)
  - Inspect the per-project memory settings file (likely under `/opt/agent-zero/data/usr/projects/{project}/memory_settings.json` or similar — check AZ source for canonical location)
  - Set `memory_memorize_enabled=false` and `memory_recall_enabled=false` for one test project (e.g., create `_test_cortex_primary` project)
  - Trigger ONE test session in AZ with that project, observing whether `_memory` LLM extraction calls appear in `docker logs agent-zero --tail 200`
  - **Outcome A (PASS)**: settings flag effective → `_memory` is silent → plan proceeds to Wave 2
  - **Outcome B (FAIL)**: settings flag ineffective → `_memory` LLM calls still happen → **plan HALTS**, present finding to user, await new decision (e.g., patch `_memory` files, or accept dual-write)
  - Write outcome + log evidence to `.sisyphus/evidence/task-2-spike.md`

  **Must NOT do**:
  - Don't modify `_memory` plugin files (out of scope; if disable mechanism doesn't work, escalate to user)
  - Don't proceed to Wave 2 if outcome is FAIL — surface the issue and wait for user decision
  - Don't make this a destructive test on production — use the disposable `_test_cortex_primary` project
  - Don't skip if "it usually works" — verify with concrete log evidence

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Requires SSH access, deployment poking, deep log reading, and browser automation to trigger AZ session
  - **Skills**: `[dev-browser]`
    - `dev-browser`: Required for agent-executable AZ web UI interaction (project switch + send test message). NO human interaction permitted; Playwright drives the UI.

  **Parallelization**:
  - **Can Run In Parallel**: YES (alongside T3, T4, T5 once T1 completes)
  - **Parallel Group**: Wave 1 (with T3, T4, T5)
  - **Blocks**: ALL of Wave 2, Wave 3, Wave 4, Wave FINAL (this is the gate)
  - **Blocked By**: T1

  **References**:

  **Pattern References**:
  - `/Users/paolo/Documents/Projects/agent-zero/plugins/_memory/extensions/python/monologue_end/_50_memorize_fragments.py:14-36` — shows the `set["memory_memorize_enabled"]` settings check, confirms the gate exists in code
  - `/Users/paolo/Documents/Projects/agent-zero/plugins/_memory/extensions/python/message_loop_prompts_after/_50_recall_memories.py:26-58` — shows `set["memory_recall_enabled"]` check
  - `/Users/paolo/Documents/Projects/agent-zero/plugins/_memory/plugin.yaml` — confirms `always_enabled: true` and `per_project_config: true`

  **API/Type References**:
  - `/Users/paolo/Documents/Projects/agent-zero/helpers/plugins.py:get_plugin_config` — function used by built-in extensions to read settings; confirms how `memory_*_enabled` is consumed

  **Test References**:
  - None — this is a runtime spike, not a unit test

  **External References**:
  - AZ plugin docs: `https://github.com/frdel/agent-zero` — for plugin settings location

  **WHY Each Reference Matters**:
  - The first three references PROVE the settings gate exists in built-in code. The spike's only question: does the per-project settings file actually flip the flag at runtime?

  **Acceptance Criteria**:

  - [ ] Evidence file `.sisyphus/evidence/task-2-spike.md` created with:
    - Section "Method": exact commands run on LXC 500
    - Section "Observation": grep'd log lines showing presence/absence of `_memory` LLM calls
    - Section "Outcome": PASS or FAIL, with rationale
  - [ ] If PASS: a follow-up command confirms NO log line matches `_50_memorize_fragments` / `_50_recall_memories` debug output during the test session (use `journalctl` or `docker logs`)
  - [ ] If FAIL: file documents what was observed, what was expected, and a proposal for the user to choose

  **QA Scenarios**:

  ```
  Scenario: _memory plugin silenced (PASS path)
    Tool: Bash + SSH + dev-browser (Playwright)
    Preconditions: LXC 500 reachable; CORTEX_API_KEY set in env; agent-zero-cortex .toggle-1 active; AZ web UI URL known (typically http://192.168.1.12:50080 or as configured)
    Steps:
      1. ssh root@192.168.1.5 "pct exec 500 -- mkdir -p /opt/agent-zero/data/usr/projects/_test_cortex_primary/.a0proj/plugins/_memory"
      2. ssh root@192.168.1.5 "pct exec 500 -- bash -c 'cat > /opt/agent-zero/data/usr/projects/_test_cortex_primary/.a0proj/plugins/_memory/config.json' << EOF
{\"memory_memorize_enabled\": false, \"memory_recall_enabled\": false}
EOF"
         (Path is the per-project plugin asset path read by `helpers.plugins.get_plugin_config('_memory', agent)` — confirmed by reading `/Users/paolo/Documents/Projects/agent-zero/helpers/plugins.py`. Settings JSON is FLAT — no `"_memory":` wrapper key — because `get_plugin_config` already namespaces by plugin name via the file path.)
      3. Use `dev-browser` skill (Playwright) to programmatically:
         a. Navigate to AZ web UI (URL from operator-supplied env or `AZ_UI_URL` config)
         b. Click the project selector dropdown; select `_test_cortex_primary`
         c. Locate the message input (selector: `textarea[placeholder*="message"]` or equivalent — confirm via initial inspection screenshot saved to evidence)
         d. Type: `Remember that the test marker is XYZQ-2026-Spike-T2`
         e. Click send (selector: `button[type="submit"]` near input)
         f. Wait for response (poll for new message bubble in chat history, timeout 60s)
         g. Save final screenshot to .sisyphus/evidence/task-2-ui-final.png
      4. ssh root@192.168.1.5 "pct exec 500 -- docker logs agent-zero --tail 300 2>&1" > .sisyphus/evidence/task-2-logs.txt
      5. Inspect logs for any line containing "Memorizing new information" or "Searching memories" (these are the built-in _memory plugin's log markers from `_50_memorize_fragments.py:25` and `_50_recall_memories.py:34`)
    Expected Result: logs contain ZERO matches for the built-in markers; only `cortex.init` / `cortex.memorize` (or absence if our plugin not deployed yet) appears
    Failure Indicators: log contains "Memorizing new information" or "Searching memories" → built-in still running → FAIL
    Evidence: .sisyphus/evidence/task-2-logs.txt, .sisyphus/evidence/task-2-ui-final.png, .sisyphus/evidence/task-2-spike.md
    Note: If AZ web UI is unreachable from the agent's network, alternative: use AZ's internal HTTP API directly via curl. AZ exposes `POST /chat` or `POST /api/messages` — the executor must locate the actual endpoint by reading AZ's source at `/Users/paolo/Documents/Projects/agent-zero/python/api/` and use it. Document the chosen approach in `task-2-spike.md`.

  Scenario: _memory plugin NOT silenced (FAIL path — must halt and escalate)
    Tool: Bash
    Preconditions: same as above; outcome was FAIL
    Steps:
      1. Write `.sisyphus/evidence/task-2-spike.md` with: outcome=FAIL, observed log lines verbatim, proposed escalations
      2. Do NOT proceed to Wave 2
      3. Surface findings to user via plan-execution layer
    Expected Result: plan execution paused; user decides between (a) patching/removing built-in `_memory` extension files, (b) accepting dual-write with idempotency dedup, (c) abandoning refactor
    Evidence: .sisyphus/evidence/task-2-spike.md
  ```

  **Evidence to Capture**:
  - [ ] `task-2-logs.txt` (raw log dump)
  - [ ] `task-2-spike.md` (structured outcome doc)

  **Commit**: YES (committable as a chore that records the spike outcome)
  - Message: `chore: verification spike — confirm _memory plugin can be silenced`
  - Files: `.sisyphus/evidence/task-2-spike.md`, `.sisyphus/evidence/task-2-logs.txt` (if fits in repo; otherwise gitignore evidence/ and just commit the .md outcome)
  - Pre-commit: none (this is documentation of an external spike result)

- [x] 3. **SPIKE — Measure Cortex POST latency baseline**

  **What to do**:
  - Run a series of `POST /v1/memories` calls against live Cortex with realistic payloads (content sizes 200, 500, 1000, 2000 chars; 6 calls each size, serial)
  - Time each call (wall-clock from request start to response received)
  - Compute p50, p95, p99 per content size; total wall-clock for serial 6-of-each-size batches
  - Decide: is the 10s posting budget realistic for ~6–10 memories per session?
  - If p95×10 > 10s, flag and propose adjustment to plan (e.g., reduce `recall_limit`, accept partial-write more readily, or reduce posts per session)
  - Save raw timings + summary stats to `.sisyphus/evidence/task-3-latency.md`

  **Must NOT do**:
  - Don't pollute production data — use unique session_id `spike-task-3-{timestamp}` so memories are easy to filter out / forget later
  - Don't run more than 50 calls total (respect rate limits and OpenAI cost)
  - Don't change plan parameters in this task; just gather evidence and surface findings

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Real network calls, timing instrumentation, summary stats; not creative but requires care
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T2, T4, T5)
  - **Parallel Group**: Wave 1
  - **Blocks**: None directly (informational; informs T11 timeout decisions but doesn't gate them)
  - **Blocked By**: T1

  **References**:
  - Cortex API contract from research: `POST /v1/memories` synchronous embedding via OpenAI `text-embedding-3-small` — expect 0.5–2s/call
  - `pyproject.toml` already has `httpx>=0.28` available for the spike script

  **Acceptance Criteria**:
  - [ ] `.sisyphus/evidence/task-3-latency.md` exists with: methodology, raw timings table, p50/p95/p99 per size, recommended action if budget tight
  - [ ] Cleanup command run: forget all spike memories via `POST /v1/memories action=forget` for each id

  **QA Scenarios**:
  ```
  Scenario: Latency baseline measured
    Tool: Bash + python (one-shot script in /tmp/, NOT in repo)
    Preconditions: CORTEX_URL and CORTEX_API_KEY set; LAN reachable
    Steps:
      1. Write throwaway script at /tmp/spike_latency.py: serially POST 6 memories at each of 4 content sizes (200/500/1000/2000 chars), measure each via time.monotonic(); print json summary
      2. Run `python /tmp/spike_latency.py | tee .sisyphus/evidence/task-3-raw.json`
      3. Compute p50/p95/p99 from the json (jq one-liner) and write summary to .sisyphus/evidence/task-3-latency.md
      4. For each returned id, POST forget action: `curl -X POST -H "Authorization: Bearer $CORTEX_API_KEY" -d '{"action":"forget","memory_id":"<id>"}' $CORTEX_URL/v1/memories`
      5. rm /tmp/spike_latency.py
    Expected Result: summary doc shows realistic p95 < ~2.0s per POST; for 10 POSTs serial, total < 20s comfortably
    Failure Indicators: p95 > 5s/call (Cortex backend issue); all 6 calls of one size return 401/500 (auth or backend error)
    Evidence: .sisyphus/evidence/task-3-raw.json, .sisyphus/evidence/task-3-latency.md
  ```

  **Evidence**:
  - [ ] `task-3-raw.json`, `task-3-latency.md`

  **Commit**: YES
  - Message: `chore: spike — measure Cortex POST latency baseline`
  - Files: `.sisyphus/evidence/task-3-latency.md` (raw json optional)
  - Pre-commit: none

- [x] 4. **Vendor extraction prompts (verbatim from upstream AZ commit `2613fac0`)**

  **What to do**:
  - Copy `/Users/paolo/Documents/Projects/agent-zero/plugins/_memory/prompts/memory.memories_sum.sys.md` → `prompts/memory.memories_sum.sys.md`
  - Copy `/Users/paolo/Documents/Projects/agent-zero/plugins/_memory/prompts/memory.solutions_sum.sys.md` → `prompts/memory.solutions_sum.sys.md`
  - At the END of each file, append a single comment line: `<!-- Sourced from frdel/agent-zero@2613fac0:plugins/_memory/prompts/<filename>; do not edit -->`
  - Verify byte-identical content (except the appended comment): `diff <(head -n -1 prompts/X) /Users/paolo/.../X` should output nothing

  **Must NOT do**:
  - DO NOT edit the prompt content; this is verbatim copy
  - Don't add a YAML frontmatter or metadata block (the prompts are .md system prompts, plain text)
  - Don't reformat indentation or whitespace

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: File copy + one-line append; trivial
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T2, T3, T5)
  - **Parallel Group**: Wave 1
  - **Blocks**: T9 (prompts.py loads these), T11 (extraction.py uses them)
  - **Blocked By**: T1

  **References**:
  - `/Users/paolo/Documents/Projects/agent-zero/plugins/_memory/prompts/memory.memories_sum.sys.md` — fragment extraction prompt (full text known from research bg_f8211492)
  - `/Users/paolo/Documents/Projects/agent-zero/plugins/_memory/prompts/memory.solutions_sum.sys.md` — solution extraction prompt

  **Acceptance Criteria**:
  - [ ] Both prompt files exist in `prompts/` directory
  - [ ] Byte-identity (except comment): `diff <(sed '$d' prompts/memory.memories_sum.sys.md) /Users/paolo/Documents/Projects/agent-zero/plugins/_memory/prompts/memory.memories_sum.sys.md` exits 0
  - [ ] Same for solutions
  - [ ] Each file ends with the `<!-- Sourced from ... -->` line
  - [ ] `wc -l prompts/*.md` shows reasonable counts (>20 lines each)

  **QA Scenarios**:
  ```
  Scenario: Prompts vendored byte-identically
    Tool: Bash
    Preconditions: AZ clone exists at /Users/paolo/Documents/Projects/agent-zero/
    Steps:
      1. cp /Users/paolo/Documents/Projects/agent-zero/plugins/_memory/prompts/memory.memories_sum.sys.md prompts/
      2. cp /Users/paolo/Documents/Projects/agent-zero/plugins/_memory/prompts/memory.solutions_sum.sys.md prompts/
      3. printf '\n<!-- Sourced from frdel/agent-zero@2613fac0:plugins/_memory/prompts/memory.memories_sum.sys.md; do not edit -->\n' >> prompts/memory.memories_sum.sys.md
      4. printf '\n<!-- Sourced from frdel/agent-zero@2613fac0:plugins/_memory/prompts/memory.solutions_sum.sys.md; do not edit -->\n' >> prompts/memory.solutions_sum.sys.md
      5. diff <(sed '$d' prompts/memory.memories_sum.sys.md) /Users/paolo/Documents/Projects/agent-zero/plugins/_memory/prompts/memory.memories_sum.sys.md | tee .sisyphus/evidence/task-4-diff-fragments.txt
      6. diff <(sed '$d' prompts/memory.solutions_sum.sys.md) /Users/paolo/Documents/Projects/agent-zero/plugins/_memory/prompts/memory.solutions_sum.sys.md | tee .sisyphus/evidence/task-4-diff-solutions.txt
      7. tail -1 prompts/memory.memories_sum.sys.md prompts/memory.solutions_sum.sys.md | tee .sisyphus/evidence/task-4-stamps.txt
    Expected Result: both diff outputs are EMPTY; both files end with the source-stamp comment
    Failure Indicators: diff shows differences; tail doesn't show the stamp
    Evidence: .sisyphus/evidence/task-4-diff-fragments.txt, .sisyphus/evidence/task-4-diff-solutions.txt, .sisyphus/evidence/task-4-stamps.txt
  ```

  **Evidence**:
  - [ ] `task-4-diff-fragments.txt`, `task-4-diff-solutions.txt`, `task-4-stamps.txt`

  **Commit**: YES
  - Message: `feat: vendor AZ memory extraction prompts (commit 2613fac0)`
  - Files: `prompts/memory.memories_sum.sys.md`, `prompts/memory.solutions_sum.sys.md`
  - Pre-commit: `diff` checks above

- [x] 5. **Delete dead code (`client.py`, `default_config.yaml`, all 4 existing test files)**

  **What to do**:
  - Delete: `client.py`, `default_config.yaml`
  - Delete: `tests/test_init.py`, `tests/test_memorize.py`, `tests/test_recall_append.py`, `tests/test_skill_idempotency.py`
  - Delete: `tests/__init__.py` if it exists (will be re-created at proper layer-package level by T1; if T1 already created it, leave it)
  - DO NOT delete `tests/__pycache__/` from git (it's already gitignored)
  - DO NOT delete the existing extension files yet — those get rewritten in Wave 3 (T14, T15, T16)

  **Must NOT do**:
  - Don't delete extension files (`extensions/python/**/_60_*.py`) — they're rewritten in-place in Wave 3
  - Don't delete `prompts/` (just created in T4)
  - Don't delete `pyproject.toml` settings established in T1

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: File deletions; trivial
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T2, T3, T4)
  - **Parallel Group**: Wave 1
  - **Blocks**: None (cleanup is independent of all subsequent work)
  - **Blocked By**: T1

  **References**:
  - From research bg_c7580e4f: `client.py` is unused (no imports); `default_config.yaml` is not consumed by code; existing tests test the wrong shape (module-level `execute()` vs real `Cls(agent).execute()`)

  **Acceptance Criteria**:
  - [ ] `test ! -f client.py && test ! -f default_config.yaml` exits 0
  - [ ] `test ! -f tests/test_init.py && test ! -f tests/test_memorize.py && test ! -f tests/test_recall_append.py && test ! -f tests/test_skill_idempotency.py` exits 0
  - [ ] `python -m pytest --collect-only -q` succeeds (no broken imports)
  - [ ] `git status` shows the deletions staged

  **QA Scenarios**:
  ```
  Scenario: Dead code removed cleanly
    Tool: Bash
    Preconditions: T1 has created tests/{unit,wrapper,integration} dirs already
    Steps:
      1. git rm client.py default_config.yaml tests/test_init.py tests/test_memorize.py tests/test_recall_append.py tests/test_skill_idempotency.py
      2. ls -la client.py default_config.yaml 2>&1 | tee .sisyphus/evidence/task-5-deleted.txt
      3. python -m pytest --collect-only -q 2>&1 | tee .sisyphus/evidence/task-5-collect.txt
      4. git status --short | tee .sisyphus/evidence/task-5-status.txt
    Expected Result: ls outputs "No such file"; pytest collects 0 tests with 0 errors; git status shows 6 deletions staged
    Failure Indicators: file still present; pytest reports import errors; git status shows unrelated changes
    Evidence: .sisyphus/evidence/task-5-deleted.txt, .sisyphus/evidence/task-5-collect.txt, .sisyphus/evidence/task-5-status.txt
  ```

  **Evidence**:
  - [ ] `task-5-deleted.txt`, `task-5-collect.txt`, `task-5-status.txt`

  **Commit**: YES
  - Message: `chore: remove dead code (client.py, default_config.yaml, old tests)`
  - Files: deletions of the 6 files above
  - Pre-commit: `python -m pytest --collect-only -q`

- [x] 6. **`src/cortex_plugin/slugs.py` — sanitize_slug + project_resolve (TDD)**

  **What to do** (RED → GREEN → REFACTOR):
  - **RED**: Write `tests/unit/test_slugs.py` with cases:
    - `sanitize_slug("homelab")` → `"homelab"`
    - `sanitize_slug("Foo Bar/Baz!")` → `"foo_bar_baz_"`
    - `sanitize_slug("a"*100)` → 64-char output
    - `sanitize_slug("")` → `""`
    - `sanitize_slug(None)` raises `TypeError`
    - `project_resolve(None)` → `(None, None)` (slug, original)
    - `project_resolve("")` → `(None, "")`
    - `project_resolve("default")` → `(None, "default")` — sentinel
    - `project_resolve("HomeLab")` → `("homelab", "HomeLab")`
    - `project_resolve("Foo Bar")` → `("foo_bar", "Foo Bar")`
  - **GREEN**: Implement `sanitize_slug(name: str) -> str` (regex `[^a-z0-9_-]` → `_`, lowercase, max 64 chars) and `project_resolve(project_name: str | None) -> tuple[str | None, str | None]` (returns `(sanitized_slug, original_name)`; returns `(None, name)` for None/""/"default")
  - **REFACTOR**: Extract regex constant; ensure docstrings; ensure type hints

  **Must NOT do**:
  - Don't import from `helpers.*` or `agent.*` — pure function library, ZERO AZ-runtime imports
  - Don't accept `bytes` input or do any encoding fiddling
  - Don't add unicode normalization (NFD/NFC) — keep behavior identical to existing `_60_cortex_init.py:_sanitize_slug`

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Trivial pure function with clear specification
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 2 — independent of T7, T8, T9, T10)
  - **Parallel Group**: Wave 2
  - **Blocks**: T11 (uses slugs in extraction context), T15 (memorize wrapper uses for source_project), T14 (init wrapper uses for topic-lock)
  - **Blocked By**: T1

  **References**:
  - **Pattern**: `extensions/python/monologue_start/_60_cortex_init.py:12-16` — current `_SLUG_RE` and `_sanitize_slug`; replicate exact behavior
  - **Pattern**: `extensions/python/monologue_end/_60_cortex_memorize.py:62-66` — current duplicated sanitization (this task de-duplicates it)

  **Acceptance Criteria** (TDD):
  - [ ] Test file `tests/unit/test_slugs.py` exists with all 10 cases above
  - [ ] `python -m pytest tests/unit/test_slugs.py -v` exits 0 (10 PASSED)
  - [ ] `! grep -E "(from helpers|import helpers|from agent|import agent\b)" src/cortex_plugin/slugs.py`
  - [ ] `python -c "from cortex_plugin.slugs import sanitize_slug, project_resolve; print(project_resolve('HomeLab'))"` outputs `('homelab', 'HomeLab')`

  **QA Scenarios**:
  ```
  Scenario: All cases green via TDD
    Tool: Bash + pytest
    Preconditions: Wave 1 complete; src/cortex_plugin/__init__.py exists
    Steps:
      1. Write tests/unit/test_slugs.py with the 10 cases (TestSanitizeSlug + TestProjectResolve classes or as plain test functions)
      2. Run `python -m pytest tests/unit/test_slugs.py -v 2>&1 | tee .sisyphus/evidence/task-6-red.txt` — expect ALL FAILED (no slugs.py yet)
      3. Implement src/cortex_plugin/slugs.py minimally to make tests pass
      4. Run `python -m pytest tests/unit/test_slugs.py -v 2>&1 | tee .sisyphus/evidence/task-6-green.txt` — expect ALL PASSED
      5. Run import-check: `! grep -E "(from helpers|import helpers|from agent|import agent\b)" src/cortex_plugin/slugs.py | tee .sisyphus/evidence/task-6-purity.txt`
    Expected Result: red.txt shows 10 failures (collection or assertion); green.txt shows 10 passed; purity check finds zero forbidden imports
    Evidence: task-6-red.txt, task-6-green.txt, task-6-purity.txt

  Scenario: Boundary case — exactly 64 chars input
    Tool: Bash + pytest
    Preconditions: GREEN passed
    Steps:
      1. python -c "from cortex_plugin.slugs import sanitize_slug; s = sanitize_slug('a' * 64); assert len(s) == 64, len(s); print('ok')" | tee .sisyphus/evidence/task-6-boundary-eq.txt
      2. python -c "from cortex_plugin.slugs import sanitize_slug; s = sanitize_slug('a' * 65); assert len(s) == 64, len(s); print('ok')" | tee .sisyphus/evidence/task-6-boundary-gt.txt
    Expected Result: both print "ok"
    Evidence: task-6-boundary-eq.txt, task-6-boundary-gt.txt
  ```

  **Evidence**: `task-6-red.txt`, `task-6-green.txt`, `task-6-purity.txt`, `task-6-boundary-eq.txt`, `task-6-boundary-gt.txt`

  **Commit**: YES
  - Message: `feat(lib): slugs module with sanitize_slug and project_resolve`
  - Files: `src/cortex_plugin/slugs.py`, `tests/unit/test_slugs.py`
  - Pre-commit: `python -m pytest tests/unit/test_slugs.py -v`

- [x] 7. **`src/cortex_plugin/keys.py` — idempotency_key (TDD)**

  **What to do** (RED → GREEN → REFACTOR):
  - **RED**: Write `tests/unit/test_keys.py`:
    - `idempotency_key("ses-1", "fragments", "hello")` → 64-char hex string
    - Same inputs → same key (deterministic)
    - Different content → different key
    - Different area → different key
    - Different session → different key
    - Empty content allowed → returns valid hex string (don't reject; consumer's choice to filter empties)
    - Unicode content (e.g., "€100", "日本語") → returns valid hex (utf-8 encoded internally)
  - **GREEN**: `def idempotency_key(session_id: str, area: str, content: str) -> str: return hashlib.sha256(f"{session_id}|{area}|{content}".encode("utf-8")).hexdigest()`
  - **REFACTOR**: Add docstring documenting that this matches Cortex's server-side `dedup_key` format

  **Must NOT do**:
  - Don't change the format — must match Cortex's server-side dedup key exactly (`sha256(source_session_id|area|content)` UTF-8)
  - Don't accept None inputs (let TypeError surface)
  - Don't strip/normalize content — byte-exact

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: T11 (extraction passes keys to memorize POST), T15 (memorize wrapper)
  - **Blocked By**: T1

  **References**:
  - **Pattern**: `extensions/python/monologue_end/_60_cortex_memorize.py:23-25` — current `_idempotency_key` to be replaced

  **Acceptance Criteria** (TDD):
  - [ ] `tests/unit/test_keys.py` exists with all 7 cases
  - [ ] `python -m pytest tests/unit/test_keys.py -v` exits 0 (7 PASSED)
  - [ ] `! grep -E "(from helpers|import helpers|from agent|import agent\b)" src/cortex_plugin/keys.py`
  - [ ] Manual byte-check: `python -c "import hashlib; print(hashlib.sha256(b'ses-1|fragments|hello').hexdigest())"` matches `python -c "from cortex_plugin.keys import idempotency_key; print(idempotency_key('ses-1', 'fragments', 'hello'))"`

  **QA Scenarios**:
  ```
  Scenario: TDD red→green
    Tool: Bash + pytest
    Steps:
      1. Write tests/unit/test_keys.py with 7 cases
      2. pytest tests/unit/test_keys.py -v 2>&1 | tee .sisyphus/evidence/task-7-red.txt   (expect FAIL)
      3. Implement src/cortex_plugin/keys.py
      4. pytest tests/unit/test_keys.py -v 2>&1 | tee .sisyphus/evidence/task-7-green.txt (expect 7 PASSED)
    Expected Result: red shows failures; green shows 7 passes
    Evidence: task-7-red.txt, task-7-green.txt

  Scenario: Format matches Cortex server-side dedup
    Tool: Bash
    Steps:
      1. python -c "import hashlib; print(hashlib.sha256(b'ses-1|fragments|hello').hexdigest())" > /tmp/expected
      2. python -c "from cortex_plugin.keys import idempotency_key; print(idempotency_key('ses-1', 'fragments', 'hello'))" > /tmp/actual
      3. diff /tmp/expected /tmp/actual | tee .sisyphus/evidence/task-7-format-match.txt
    Expected Result: diff is empty
    Evidence: task-7-format-match.txt
  ```

  **Evidence**: `task-7-red.txt`, `task-7-green.txt`, `task-7-format-match.txt`

  **Commit**: YES
  - Message: `feat(lib): keys module with deterministic idempotency_key`
  - Files: `src/cortex_plugin/keys.py`, `tests/unit/test_keys.py`
  - Pre-commit: `python -m pytest tests/unit/test_keys.py -v`

- [x] 8. **`src/cortex_plugin/config.py` — env reads + hardcoded constants (TDD)**

  **What to do** (RED → GREEN → REFACTOR):
  - **RED**: Write `tests/unit/test_config.py`:
    - `load_config()` returns dict-like or NamedTuple with: `url, api_key, enabled, recall_limit, recall_threshold, recall_legacy_rank, prompt_dir`
    - Defaults when env unset: `url="http://192.168.1.12:8001"`, `api_key=""`, `enabled=True`, `recall_limit=5`, `recall_threshold=0.02`, `recall_legacy_rank=False`, `prompt_dir=None`
    - `enabled=False` when `CORTEX_ENABLED=false` (case-insensitive); `recall_legacy_rank=True` when `CORTEX_RECALL_LEGACY_RANK=true` (case-insensitive)
    - `recall_limit` from env coerced to int; `recall_threshold` from env coerced to float
    - Lenient bool parsing for `recall_legacy_rank`: `"true"`, `"True"`, `"1"`, `"yes"` → True; `"false"`, `"False"`, `"0"`, `"no"`, `""`, invalid → False (no exception)
    - **Constants exposed (NOT env-configurable)**: `EXTRACTION_TIMEOUT_SEC=5`, `POSTING_TIMEOUT_SEC=10`, `HTTP_TIMEOUT_SEC=10`, `RECALL_CANDIDATE_MULTIPLIER=5`, `RECALL_CANDIDATE_FLOOR=30`, `FRAGMENT_IMPORTANCE=0.5`, `SOLUTION_IMPORTANCE=0.7`, `RETRY_ATTEMPTS=2` (1 attempt + 1 retry), `RECALL_QUERY_MIN_CHARS=3`, `MAX_HISTORY_CHARS=80000`
  - **GREEN**: Use `os.environ.get` for env vars, expose constants as module-level UPPER_SNAKE_CASE
  - **REFACTOR**: Use a `NamedTuple` (`CortexConfig`) for the env-derived values for clarity. Add docstring noting `recall_threshold` is calibration-dependent on Cortex scoring algorithm (see plan compatibility matrix); `recall_legacy_rank` is forward-compat escape hatch.

  **Must NOT do**:
  - Don't add new env vars beyond the 7 documented
  - Don't read settings from a YAML/TOML/JSON file
  - Don't cache the config (re-read each call so env changes take effect without restart)
  - Don't validate `api_key` is non-empty here (extensions decide what to do with empty)
  - Don't raise on unparseable `CORTEX_RECALL_LEGACY_RANK` value — fall back to `False` silently (defensive: env is operator-controlled, surprising failures harm reliability)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: T9, T10, T11, T12, T14, T15, T16 (everything reads config)
  - **Blocked By**: T1

  **References**:
  - **Pattern**: existing extensions read env vars inline at top of `execute()` — this consolidates them
  - **External**: `os.environ.get` standard pattern

  **Acceptance Criteria** (TDD):
  - [ ] `tests/unit/test_config.py` exists with ≥10 cases (defaults, each of 7 env vars, type coercion, case-insensitive bool parsing for enabled + legacy_rank, lenient parse of invalid legacy_rank values, constants present)
  - [ ] `python -m pytest tests/unit/test_config.py -v` exits 0
  - [ ] All 10 hardcoded constants importable: `python -c "from cortex_plugin.config import EXTRACTION_TIMEOUT_SEC, POSTING_TIMEOUT_SEC, HTTP_TIMEOUT_SEC, RECALL_CANDIDATE_MULTIPLIER, RECALL_CANDIDATE_FLOOR, FRAGMENT_IMPORTANCE, SOLUTION_IMPORTANCE, RETRY_ATTEMPTS, RECALL_QUERY_MIN_CHARS, MAX_HISTORY_CHARS; print('ok')"`
  - [ ] All 7 env-derived fields importable: `python -c "from cortex_plugin.config import load_config; c = load_config(); print(c.url, c.api_key, c.enabled, c.recall_limit, c.recall_threshold, c.recall_legacy_rank, c.prompt_dir)"`
  - [ ] No forbidden imports

  **QA Scenarios**:
  ```
  Scenario: TDD with mocked env
    Tool: Bash + pytest (uses monkeypatch fixture-free via os.environ in tests)
    Steps:
      1. Write tests/unit/test_config.py using `unittest.mock.patch.dict(os.environ, ...)` for env permutations
      2. pytest tests/unit/test_config.py -v 2>&1 | tee .sisyphus/evidence/task-8-red.txt   (expect FAIL)
      3. Implement src/cortex_plugin/config.py
      4. pytest tests/unit/test_config.py -v 2>&1 | tee .sisyphus/evidence/task-8-green.txt (expect ALL PASSED)
    Expected Result: red→green
    Evidence: task-8-red.txt, task-8-green.txt

  Scenario: Constants exist (no missing knobs)
    Tool: Bash
    Steps:
      1. python -c "from cortex_plugin import config; print(config.EXTRACTION_TIMEOUT_SEC, config.POSTING_TIMEOUT_SEC, config.HTTP_TIMEOUT_SEC, config.RECALL_CANDIDATE_MULTIPLIER, config.RECALL_CANDIDATE_FLOOR, config.FRAGMENT_IMPORTANCE, config.SOLUTION_IMPORTANCE, config.RETRY_ATTEMPTS, config.RECALL_QUERY_MIN_CHARS, config.MAX_HISTORY_CHARS)" | tee .sisyphus/evidence/task-8-constants.txt
    Expected Result: outputs values: 5 10 10 5 30 0.5 0.7 2 3 80000
    Evidence: task-8-constants.txt

  Scenario: Exactly 7 documented env vars; no extras
    Tool: Bash
    Steps:
      1. grep -E "os\.environ\.(get|.get)" src/cortex_plugin/config.py | tee .sisyphus/evidence/task-8-envvars.txt
      2. Manual review: must reference exactly CORTEX_URL, CORTEX_API_KEY, CORTEX_ENABLED, CORTEX_RECALL_LIMIT, CORTEX_RECALL_THRESHOLD, CORTEX_RECALL_LEGACY_RANK, CORTEX_PROMPT_DIR — no others
      3. Count unique env var names: `grep -oE 'CORTEX_[A-Z_]+' src/cortex_plugin/config.py | sort -u | wc -l` → must be 7
    Expected Result: 7 unique env-var references; no `CORTEX_FAISS_*`, no `CORTEX_MERGE_*`, no `CORTEX_RETRY_*`, no `CORTEX_RERANK_*`
    Evidence: task-8-envvars.txt

  Scenario: Lenient bool parsing for CORTEX_RECALL_LEGACY_RANK
    Tool: pytest
    Steps:
      1. pytest tests/unit/test_config.py::test_legacy_rank_parsing -v 2>&1 | tee .sisyphus/evidence/task-8-legacyrank.txt
      2. Cases tested: "true"/"True"/"1"/"yes" → True; "false"/"False"/"0"/"no"/""/invalid → False
    Expected Result: PASSED
    Evidence: task-8-legacyrank.txt
  ```

  **Evidence**: `task-8-red.txt`, `task-8-green.txt`, `task-8-constants.txt`, `task-8-envvars.txt`, `task-8-legacyrank.txt`

  **Commit**: YES
  - Message: `feat(lib): config module reading 6 env vars + hardcoded constants`
  - Files: `src/cortex_plugin/config.py`, `tests/unit/test_config.py`
  - Pre-commit: `python -m pytest tests/unit/test_config.py -v`

- [x] 9. **`src/cortex_plugin/prompts.py` — load vendored .md files with override hook (TDD)**

  **What to do** (RED → GREEN → REFACTOR):
  - **RED**: Write `tests/unit/test_prompts.py`:
    - `load_fragments_prompt()` returns string starting with `# Assistant's job` (the actual content's first line)
    - `load_solutions_prompt()` returns string mentioning "successful technical solutions"
    - `load_fragments_prompt()` cached (returns same `id()` on second call) via `lru_cache`
    - When `CORTEX_PROMPT_DIR=/tmp/test_override` set and `/tmp/test_override/memory.memories_sum.sys.md` exists with content `OVERRIDE`: returns `OVERRIDE`
    - When override dir doesn't have file: falls back to vendored prompt
    - When override path is invalid (e.g., file unreadable): falls back to vendored, logs warning
  - **GREEN**: Implement `prompts.py` with `@functools.lru_cache(maxsize=2)` — wait, lru_cache needs to invalidate when env changes for tests. Use a private dict cache keyed by (CORTEX_PROMPT_DIR, name) and a manual `_clear_cache_for_tests()` helper.
  - Use `pathlib.Path` to resolve paths
  - Read with `Path.read_text(encoding="utf-8")`
  - Vendored fallback: `Path(__file__).parent.parent.parent / "prompts" / filename`
  - **REFACTOR**: Constants `_FRAGMENT_PROMPT_FILE = "memory.memories_sum.sys.md"`, `_SOLUTION_PROMPT_FILE = "memory.solutions_sum.sys.md"`

  **Must NOT do**:
  - Don't use `lru_cache` if it makes test invalidation hard — manual dict cache is fine
  - Don't read prompts at module import time (lazy on first call)
  - Don't `yaml.load` — these are plain markdown text files
  - Don't strip or modify the loaded content (return as-is)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T6, T7, T8, T10) — but logically depends on T4 (vendored prompts must exist)
  - **Parallel Group**: Wave 2
  - **Blocks**: T11 (extraction.py uses load_fragments_prompt, load_solutions_prompt)
  - **Blocked By**: T1, T4

  **References**:
  - **Pattern**: T4 vendored files at `prompts/memory.memories_sum.sys.md` and `prompts/memory.solutions_sum.sys.md`
  - **External**: `pathlib.Path` and `functools.lru_cache` stdlib

  **Acceptance Criteria** (TDD):
  - [ ] `tests/unit/test_prompts.py` exists with all 6 cases (3 happy path + 3 override scenarios)
  - [ ] `python -m pytest tests/unit/test_prompts.py -v` exits 0
  - [ ] `python -c "from cortex_plugin.prompts import load_fragments_prompt, load_solutions_prompt; print(len(load_fragments_prompt()), len(load_solutions_prompt()))"` outputs two non-zero integers
  - [ ] No forbidden imports

  **QA Scenarios**:
  ```
  Scenario: TDD red→green with override
    Tool: Bash + pytest
    Preconditions: T4 prompts exist
    Steps:
      1. Write tests/unit/test_prompts.py with 6 cases (use tmp_path fixture or manual mkdtemp)
      2. pytest tests/unit/test_prompts.py -v 2>&1 | tee .sisyphus/evidence/task-9-red.txt
      3. Implement src/cortex_plugin/prompts.py
      4. pytest tests/unit/test_prompts.py -v 2>&1 | tee .sisyphus/evidence/task-9-green.txt
    Expected Result: red FAIL, green ALL PASSED (6/6)
    Evidence: task-9-red.txt, task-9-green.txt

  Scenario: Override hook works end-to-end
    Tool: Bash
    Steps:
      1. mkdir /tmp/cortex-prompts-test
      2. echo "TESTING_OVERRIDE_PROMPT" > /tmp/cortex-prompts-test/memory.memories_sum.sys.md
      3. CORTEX_PROMPT_DIR=/tmp/cortex-prompts-test python -c "from cortex_plugin.prompts import load_fragments_prompt; print(load_fragments_prompt())" | tee .sisyphus/evidence/task-9-override.txt
      4. Confirm output is "TESTING_OVERRIDE_PROMPT"
      5. rm -rf /tmp/cortex-prompts-test
    Expected Result: override content returned
    Evidence: task-9-override.txt
  ```

  **Evidence**: `task-9-red.txt`, `task-9-green.txt`, `task-9-override.txt`

  **Commit**: YES
  - Message: `feat(lib): prompts module loads vendored .md files with override hook`
  - Files: `src/cortex_plugin/prompts.py`, `tests/unit/test_prompts.py`
  - Pre-commit: `python -m pytest tests/unit/test_prompts.py -v`

- [x] 10. **`src/cortex_plugin/http.py` — minimal async POST/GET helpers (TDD)**

  **What to do** (RED → GREEN → REFACTOR):
  - **RED**: Write `tests/unit/test_http.py`:
    - `cortex_post(url, path, body, api_key, headers=None, params=None, timeout_sec=10)` returns parsed JSON on 2xx — supports optional `params: dict[str, str] | None` for query string (used by recall to pass `legacy_rank=true` when configured)
    - Raises `httpx.HTTPStatusError` on 4xx/5xx (or returns custom error type — choose one and stick to it; recommend let `httpx` exceptions surface, callers catch)
    - Authorization header always added: `Bearer {api_key}`
    - Custom headers (e.g., `Idempotency-Key`) merged in correctly
    - Query params correctly URL-encoded and appended: `params={"legacy_rank": "true"}` produces `?legacy_rank=true`
    - Timeout honored: mocked slow response triggers `httpx.TimeoutException` after `timeout_sec`
    - `cortex_get(url, path, api_key, params=None, timeout_sec=10)` mirrors POST
  - **GREEN**: Implement `cortex_post` and `cortex_get` as async functions. Each call creates `async with httpx.AsyncClient(timeout=timeout_sec) as client: ...` (per-call client; no global client pool). Pass `params=` through to `client.post(...)` / `client.get(...)`.
  - **REFACTOR**: Extract `_build_headers(api_key, extra)` helper

  **Must NOT do**:
  - Don't create a `CortexClient` class — just plain async functions
  - Don't share an `httpx.AsyncClient` across calls — per-call client is intentional (simpler lifecycle)
  - Don't add retry logic here (callers handle retries)
  - Don't add response model validation (callers parse JSON dict)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Async + mocking httpx requires care; simple but easy to get wrong
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: T11, T12, T14, T15, T16 (everyone uses HTTP)
  - **Blocked By**: T1, T8

  **References**:
  - **External**: httpx async client docs `https://www.python-httpx.org/async/`
  - **Pattern**: existing extensions inline `async with httpx.AsyncClient(timeout=10.0)` — this codifies the pattern

  **Acceptance Criteria** (TDD):
  - [ ] `tests/unit/test_http.py` exists with ≥7 cases (200, 401, 500, timeout, headers merge, GET happy, query-params encoding)
  - [ ] `python -m pytest tests/unit/test_http.py -v` exits 0
  - [ ] No forbidden imports
  - [ ] No `CortexClient` class anywhere: `! grep -E "class CortexClient" src/cortex_plugin/http.py`
  - [ ] Query-params support verified: `pytest tests/unit/test_http.py::test_query_params_appended -v` passes (mocked httpx receives `params={"legacy_rank":"true"}` and outgoing URL includes `?legacy_rank=true`)

  **QA Scenarios**:
  ```
  Scenario: TDD with mocked httpx
    Tool: Bash + pytest + unittest.mock
    Steps:
      1. Write tests/unit/test_http.py mocking `httpx.AsyncClient` via patch context manager (similar to existing test_recall_append.py style — but cleaner, no extension imports)
      2. pytest tests/unit/test_http.py -v 2>&1 | tee .sisyphus/evidence/task-10-red.txt
      3. Implement src/cortex_plugin/http.py
      4. pytest tests/unit/test_http.py -v 2>&1 | tee .sisyphus/evidence/task-10-green.txt
    Expected Result: red FAIL, green PASS (≥6/6)
    Evidence: task-10-red.txt, task-10-green.txt

  Scenario: Bearer header always present
    Tool: pytest assertion within test_http.py
    Steps:
      1. Inside test_http.py: assert captured headers["Authorization"] == "Bearer test-key"
      2. Run that specific test: pytest tests/unit/test_http.py::test_bearer_header_added -v 2>&1 | tee .sisyphus/evidence/task-10-bearer.txt
    Expected Result: PASSED
    Evidence: task-10-bearer.txt

  Scenario: Per-call client lifecycle (negative — no shared state leak)
    Tool: pytest
    Steps:
      1. Inside test_http.py: assert that two sequential calls each instantiate `httpx.AsyncClient` (mock call_count == 2)
      2. pytest tests/unit/test_http.py::test_per_call_client -v 2>&1 | tee .sisyphus/evidence/task-10-percall.txt
    Expected Result: PASSED
    Evidence: task-10-percall.txt
  ```

  **Evidence**: `task-10-red.txt`, `task-10-green.txt`, `task-10-bearer.txt`, `task-10-percall.txt`

  **Commit**: YES
  - Message: `feat(lib): http module with thin async post/get wrappers`
  - Files: `src/cortex_plugin/http.py`, `tests/unit/test_http.py`
  - Pre-commit: `python -m pytest tests/unit/test_http.py -v`

- [x] 11. **`src/cortex_plugin/extraction.py` — parallel LLM extraction + DirtyJson parse + retry-once + serial POSTs (TDD)**

  **What to do** (RED → GREEN → REFACTOR):
  - **RED**: Write `tests/unit/test_extraction.py` with ≥12 cases covering:
    - `parse_fragments(raw_text)` parses JSON array of strings via DirtyJson; returns `list[str]`
    - `parse_fragments` handles wrapping in markdown ```json blocks
    - `parse_fragments` handles single-string instead of array — wraps in list
    - `parse_fragments` returns `[]` on empty array
    - `parse_fragments` raises custom `ExtractionParseError` on totally malformed input (after retry)
    - `parse_solutions(raw_text)` returns `list[dict]` with required keys `problem`, `solution`
    - `parse_solutions` filters out dicts missing required keys (logs warning, doesn't fail)
    - `extract_fragments_and_solutions(messages_str, utility_call, ...)` runs two prompts in parallel via `asyncio.gather`
    - When one prompt fails, the other's results are still returned (asymmetric success)
    - Retry-once: first call returns malformed, second call returns valid → returns valid
    - Two consecutive failures → returns empty `(fragments=[], solutions=[])` with warning log
    - `EXTRACTION_TIMEOUT_SEC=5` from config enforced via `asyncio.wait_for` — timeout returns whatever completed
    - `History truncation: input > MAX_HISTORY_CHARS (80000)` is truncated to last N chars before being passed to LLM
    - `write_memories_to_cortex(session_id, project_slug, fragments, solutions, http_post, posting_timeout_sec)` POSTs serially with idempotency keys; returns `{written: int, failed: int, timed_out: bool}` dict
    - Solution → two memories: problem with `area=fragments, kind="solution-problem"`, solution with `area=solutions, kind="solution-step"`. NO `metadata` field in body.
    - Project-less (project_slug=None): no `source_project` field in body
    - Failure on POST 3 of 5 → counts written=4, failed=1, no exception escapes
    - POSTs respect `POSTING_TIMEOUT_SEC=10` — past timeout, return current counts with `timed_out=True`
  - **GREEN**: Implement `extraction.py` with three public functions:
    - `parse_fragments(raw: str) -> list[str]`
    - `parse_solutions(raw: str) -> list[dict[str, str]]`
    - `extract_fragments_and_solutions(history: str, utility_call: Callable[[str, str], Awaitable[str]], fragments_prompt: str, solutions_prompt: str, *, timeout_sec: int = 5) -> tuple[list[str], list[dict]]`
    - `write_memories_to_cortex(session_id: str, project_slug: str | None, fragments: list[str], solutions: list[dict], http_post: Callable, *, posting_timeout_sec: int = 10) -> dict`
  - DirtyJson: `import dirtyjson` then call `dirtyjson.loads(raw_text)` to parse. (The actual `dirtyjson` package API is `loads(s)` / `load(fp)` — modeled after stdlib `json` — NOT `parse_string`.) Add `dirtyjson>=1.0.0` to `pyproject.toml [project] dependencies` — this is the **only new runtime dependency** explicitly authorized by this refactor's guardrail exception. AZ upstream already uses `dirtyjson` for the same purpose (see `_memory` plugin `_50_memorize_fragments.py`), so this maintains parity. If `dirtyjson` is somehow already in the dep list, no edit needed.
  - **REFACTOR**: Extract POST-payload builder helper; ensure all dict keys match Cortex API contract exactly

  **Must NOT do**:
  - DON'T add `metadata` field to POST body (Cortex API doesn't have it)
  - DON'T add `linked_id` or any cross-link mechanism (impossible without metadata)
  - DON'T parallelize POSTs (Cortex sync embeddings make it pointless and risky)
  - DON'T use `tenacity` or `backoff` libraries — `for attempt in range(2)` literal
  - DON'T raise on extraction failure — return empty lists with warning logs (non-fatal contract)
  - DON'T strip the conversation history of LLM-instruction-shaped text (we trust the extraction prompt to handle that)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Most complex pure-function module; multiple async patterns, retry, partial-success, payload schema correctness
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T12)
  - **Parallel Group**: Wave 2
  - **Blocks**: T15 (memorize wrapper calls these)
  - **Blocked By**: T1, T6, T7, T8, T9, T10

  **References**:
  - **Pattern**: `/Users/paolo/Documents/Projects/agent-zero/plugins/_memory/extensions/python/monologue_end/_50_memorize_fragments.py:39-110` — fragment extraction pattern (LLM call + DirtyJson + truncation)
  - **Pattern**: `/Users/paolo/Documents/Projects/agent-zero/plugins/_memory/extensions/python/monologue_end/_51_memorize_solutions.py:38-189` — solution extraction pattern
  - **API**: Cortex `/v1/memories` POST schema (from research bg_56e873e6): required `content, kind, area`; optional `source_session_id, source_project, importance`; returns `{id, dedup_key, embedding_status}`
  - **Test**: `tests/unit/test_extraction.py` from this task (TDD-first)

  **Acceptance Criteria** (TDD):
  - [ ] `tests/unit/test_extraction.py` exists with ≥12 cases
  - [ ] `python -m pytest tests/unit/test_extraction.py -v` exits 0
  - [ ] No forbidden imports
  - [ ] No `metadata` field anywhere: `! grep -E "metadata" src/cortex_plugin/extraction.py`
  - [ ] No parallel POSTs: `! grep -E "asyncio\.gather.*post|gather.*write" src/cortex_plugin/extraction.py`
  - [ ] No retry libraries: `! grep -E "(tenacity|backoff)" src/cortex_plugin/extraction.py`

  **QA Scenarios**:
  ```
  Scenario: TDD red→green
    Tool: Bash + pytest
    Steps:
      1. Write tests/unit/test_extraction.py with ≥12 cases (mock utility_call as AsyncMock returning canned strings; mock http_post as AsyncMock)
      2. pytest tests/unit/test_extraction.py -v 2>&1 | tee .sisyphus/evidence/task-11-red.txt
      3. Implement src/cortex_plugin/extraction.py
      4. pytest tests/unit/test_extraction.py -v 2>&1 | tee .sisyphus/evidence/task-11-green.txt
    Expected Result: red FAIL, green ALL PASSED
    Evidence: task-11-red.txt, task-11-green.txt

  Scenario: Solution → two memories with correct schema
    Tool: pytest
    Steps:
      1. Inside test_extraction.py write `test_solution_creates_two_memories`: simulate parsed solutions=[{"problem": "P", "solution": "S"}], call write_memories_to_cortex with mocked http_post, capture two POST bodies
      2. Assert body 1: area="fragments", kind="solution-problem", content="P"
      3. Assert body 2: area="solutions", kind="solution-step", content="S"
      4. Assert NEITHER body has "metadata" key
      5. pytest tests/unit/test_extraction.py::test_solution_creates_two_memories -v 2>&1 | tee .sisyphus/evidence/task-11-solution-schema.txt
    Expected Result: PASSED; both POST bodies match expected schema
    Evidence: task-11-solution-schema.txt

  Scenario: Project-less omits source_project from body
    Tool: pytest
    Steps:
      1. Inside test_extraction.py: call write_memories_to_cortex with project_slug=None, capture POST body
      2. Assert "source_project" NOT in body, OR body["source_project"] is None
      3. pytest tests/unit/test_extraction.py::test_no_source_project_when_projectless -v 2>&1 | tee .sisyphus/evidence/task-11-projectless.txt
    Expected Result: PASSED
    Evidence: task-11-projectless.txt

  Scenario: Posting timeout returns partial counts
    Tool: pytest with asyncio mocking
    Steps:
      1. Inside test_extraction.py: mock http_post to sleep 1s; provide 15 memories; set posting_timeout_sec=5
      2. Call write_memories_to_cortex; assert returned dict has timed_out=True and written < 15
      3. pytest tests/unit/test_extraction.py::test_posting_timeout_partial -v 2>&1 | tee .sisyphus/evidence/task-11-timeout.txt
    Expected Result: PASSED; partial-write count >= 1, < 15, timed_out=True
    Evidence: task-11-timeout.txt
  ```

  **Evidence**: `task-11-red.txt`, `task-11-green.txt`, `task-11-solution-schema.txt`, `task-11-projectless.txt`, `task-11-timeout.txt`

  **Commit**: YES
  - Message: `feat(lib): extraction module — parallel LLM calls + DirtyJson parse + retry`
  - Files: `src/cortex_plugin/extraction.py`, `tests/unit/test_extraction.py`, `pyproject.toml` (add `dirtyjson>=1.0.0` to runtime deps — the single authorized new dependency)
  - Pre-commit: `python -m pytest tests/unit/test_extraction.py -v && pip install -e . && python -c "import dirtyjson; print(dirtyjson.loads('{\"k\":1}'))"`

- [x] 12. **`src/cortex_plugin/recall.py` — fence rerank + ## Memories block formatter (TDD)**

  **What to do** (RED → GREEN → REFACTOR):
  - **RED**: Write `tests/unit/test_recall.py` with ≥12 cases covering:
    - `should_skip_query(query: str) -> bool` returns True when `len(query.strip()) < RECALL_QUERY_MIN_CHARS (3)`
    - `compute_candidate_count(recall_limit)` returns `max(recall_limit * RECALL_CANDIDATE_MULTIPLIER, RECALL_CANDIDATE_FLOOR)` → e.g., for limit=5 returns 30; for limit=10 returns 50
    - `fence_rerank(results, current_project, recall_limit)` for project session: same-project results take priority slots, fill from cross-project. Specifically: if current_project="homelab" and 3 same-project results + 5 cross-project, with recall_limit=5, returns the 3 same-project ones first (in score order) then top-2 cross-project
    - `fence_rerank` for project-less (current_project=None): returns top recall_limit results in raw score order (no partition)
    - `fence_rerank` adversarial test: same-project score 0.03, cross-project score 0.10 → same-project STILL ranks first (boost via fence wins regardless of score difference)
    - `fence_rerank` works correctly across both score regimes: with RRF-style scores (0.01–0.05) AND composite-style scores (0.10–0.95) — fence is score-distribution-agnostic
    - `fence_rerank` empty same-project: returns top recall_limit cross-project in score order
    - `fence_rerank` empty cross-project: returns same-project in score order
    - `format_memories_block(results)` produces `## Memories\n\n<content1>\n\n---\n\n<content2>\n\n...` exact format
    - `format_memories_block([])` returns empty string `""`
    - `format_memories_block` skips entries with empty/missing content (logs warning)
    - `recall_and_format(query, session_id, current_project, http_post, *, threshold, legacy_rank=False)` orchestrates full flow: skip-check → POST `/v1/recall` with `limit=candidate_count, threshold=<from-config>` → fence rerank → format. When `legacy_rank=True`, passes `params={"legacy_rank": "true"}` to `http_post` (forces Cortex v1.1+ to use pre-v1.1 RRF ordering for backward compat).
    - `recall_and_format` with `legacy_rank=True`: verify `http_post` received `params={"legacy_rank": "true"}` (mock spy)
    - `recall_and_format` with `legacy_rank=False` (default): verify `http_post` received `params=None` or omitted (no query string appended)
    - `recall_and_format` on Cortex error: returns `""` and logs warning (extras unchanged caller-side)
  - **GREEN**: Implement `recall.py` with the 5 public functions above. `recall_and_format` reads `threshold` and `legacy_rank` from caller-passed args (plumbed from `config.load_config()` by the wrapper); pure-function library MUST NOT call `load_config()` directly.
  - **REFACTOR**: Ensure all defaults come from `config.py` constants (not redefined locally)

  **Must NOT do**:
  - DON'T filter by `area` field — Cortex `/v1/recall` doesn't return area; can't filter on it (and we don't want to exclude `area=main` migrated memories)
  - DON'T use a multiplier-based boost — fence is the chosen strategy
  - DON'T import from `extensions/`, `helpers/`, or `agent/`
  - DON'T cache recall results (each call is fresh)
  - DON'T deduplicate within results (Cortex returns unique memories already)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Fence rerank logic, formatting correctness, edge cases (empty pools, project-less)
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T11)
  - **Parallel Group**: Wave 2
  - **Blocks**: T16 (recall wrapper)
  - **Blocked By**: T1, T8, T10

  **References**:
  - **Pattern**: existing `extensions/python/message_loop_prompts_after/_60_cortex_recall.py:81-88` — current append behavior; new code REPLACES instead
  - **Pattern**: AZ built-in `/Users/paolo/Documents/Projects/agent-zero/plugins/_memory/extensions/python/message_loop_prompts_after/_50_recall_memories.py:60-70` — they DELETE keys from extras before populating; we'll do the same (clear before set)
  - **API**: Cortex `/v1/recall` returns `[{id, content, score, source_project, matched_via}]` — no `area` field

  **Acceptance Criteria** (TDD):
  - [ ] `tests/unit/test_recall.py` exists with ≥12 cases
  - [ ] `python -m pytest tests/unit/test_recall.py -v` exits 0
  - [ ] No forbidden imports
  - [ ] No multiplier-based boost: `! grep -E "score.*\* 1\.5|boost.*1\.5|RECALL_PROJECT_BOOST" src/cortex_plugin/recall.py`
  - [ ] No area filtering: `! grep -E "area\s*==\s*'(main|fragments|solutions)'" src/cortex_plugin/recall.py`
  - [ ] `legacy_rank` parameter plumbed: `grep -E "legacy_rank" src/cortex_plugin/recall.py` finds matches in `recall_and_format` signature and HTTP-call site
  - [ ] Pure-function purity preserved: `recall.py` does NOT import or call `config.load_config()` (caller-injection only)

  **QA Scenarios**:
  ```
  Scenario: TDD red→green
    Tool: Bash + pytest
    Steps:
      1. Write tests/unit/test_recall.py with ≥10 cases
      2. pytest tests/unit/test_recall.py -v 2>&1 | tee .sisyphus/evidence/task-12-red.txt
      3. Implement src/cortex_plugin/recall.py
      4. pytest tests/unit/test_recall.py -v 2>&1 | tee .sisyphus/evidence/task-12-green.txt
    Expected Result: red FAIL, green ALL PASSED
    Evidence: task-12-red.txt, task-12-green.txt

  Scenario: Fence dominates score (adversarial)
    Tool: pytest
    Steps:
      1. Inside test_recall.py: results=[{content:"A", score:0.10, source_project:"other"}, {content:"B", score:0.03, source_project:"homelab"}]
      2. Assert fence_rerank(results, current_project="homelab", recall_limit=2) returns [{content:"B"...}, {content:"A"...}] (B FIRST despite lower score)
      3. pytest tests/unit/test_recall.py::test_fence_dominates_score -v 2>&1 | tee .sisyphus/evidence/task-12-fence-adversarial.txt
    Expected Result: PASSED
    Evidence: task-12-fence-adversarial.txt

  Scenario: Format block exact bytes
    Tool: pytest
    Steps:
      1. Inside test_recall.py: results=[{content:"foo"}, {content:"bar"}]
      2. Assert format_memories_block(results) == "## Memories\n\nfoo\n\n---\n\nbar"
      3. pytest tests/unit/test_recall.py::test_format_block_exact -v 2>&1 | tee .sisyphus/evidence/task-12-format.txt
    Expected Result: PASSED
    Evidence: task-12-format.txt

  Scenario: Skip empty/short query
    Tool: pytest
    Steps:
      1. Inside test_recall.py: assert recall_and_format("", "ses", "p", mock_post) returns "" and mock_post NOT called
      2. assert recall_and_format("ok", "ses", "p", mock_post) returns "" and mock_post NOT called (len < 3)
      3. pytest tests/unit/test_recall.py::test_skip_short_query -v 2>&1 | tee .sisyphus/evidence/task-12-skipshort.txt
    Expected Result: PASSED
    Evidence: task-12-skipshort.txt
  ```

  **Evidence**: `task-12-red.txt`, `task-12-green.txt`, `task-12-fence-adversarial.txt`, `task-12-format.txt`, `task-12-skipshort.txt`

  **Commit**: YES
  - Message: `feat(lib): recall module — fence rerank + ## Memories block formatting`
  - Files: `src/cortex_plugin/recall.py`, `tests/unit/test_recall.py`
  - Pre-commit: `python -m pytest tests/unit/test_recall.py -v`

- [x] 13. **`tests/wrapper/conftest.py` — vendored `helpers.extension.Extension` stub**

  **What to do**:
  - Create `tests/wrapper/conftest.py` that registers a stub `helpers` package + submodules in `sys.modules` so wrapper tests can import the real extension files (`extensions/python/**/_60_cortex_*.py`) without AZ runtime
  - Stub `helpers.extension.Extension`: `class Extension:` with `__init__(self, agent, **kwargs)` storing `self.agent = agent` and `self.kwargs = kwargs`; abstract `execute(self, **kwargs)` (NotImplementedError default)
  - Stub `helpers.projects.get_context_project_name(context)`: callable function. Default implementation: returns `context.get_data("project")` if `context` has `get_data`, else falls back to `getattr(context, "current_project", None)`. (Matches AZ's actual canonical project lookup — primary path is `context.get_data("project")`, with `current_project` attribute as legacy/test-fixture compat.)
  - Stub `helpers.dirty_json` module: re-export `loads` from the real `dirtyjson` package (`from dirtyjson import loads`) so any extension code that imports `from helpers.dirty_json import loads` works in tests
  - Add a top-of-file comment: `"""Sourced from frdel/agent-zero@2613fac0:helpers/extension.py:212-220, helpers/projects.py:get_context_project_name, helpers/dirty_json.py. Update if upstream changes."""`

  **Must NOT do**:
  - Don't import from real `helpers` (it doesn't exist locally — that's the whole point)
  - Don't add fixtures here that bleed into other test layers (this conftest only applies to `tests/wrapper/`)
  - Don't make the stub fail-loud on missing methods — match real signature only

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T6-T12 in Wave 2 — actually it's the FIRST task of Wave 3)
  - **Parallel Group**: Wave 3
  - **Blocks**: T14, T15, T16 (wrapper tests)
  - **Blocked By**: T1

  **References**:
  - **Pattern**: `/Users/paolo/Documents/Projects/agent-zero/helpers/extension.py:212-220` — actual `Extension` base class
  - **Pattern**: `/Users/paolo/Documents/Projects/agent-zero/helpers/projects.py` — `get_context_project_name`

  **Acceptance Criteria**:
  - [ ] `tests/wrapper/conftest.py` exists
  - [ ] After conftest loads, both `from helpers.extension import Extension` and `from helpers.projects import get_context_project_name` work in wrapper tests
  - [ ] `get_context_project_name(fake_ctx)` returns the value of `fake_ctx.get_data("project")` when set, else falls back to `fake_ctx.current_project`
  - [ ] Stub source comment includes upstream commit SHA `2613fac0`

  **QA Scenarios**:
  ```
  Scenario: Wrapper tests can import extension modules without AZ runtime
    Tool: Bash + pytest
    Preconditions: Wave 1 + Wave 2 done
    Steps:
      1. Write tests/wrapper/conftest.py with stub registration
      2. Write a tiny smoke test tests/wrapper/test_smoke.py: `def test_can_import(): from extensions.python.monologue_start._60_cortex_init import CortexInit; assert CortexInit is not None`
      3. pytest tests/wrapper/test_smoke.py -v 2>&1 | tee .sisyphus/evidence/task-13-smoke.txt
      4. Delete the smoke test file (it served its purpose; real wrapper tests come in T14-T16)
    Expected Result: smoke test PASSED — import works through the stub
    Evidence: task-13-smoke.txt
  ```

  **Evidence**: `task-13-smoke.txt`

  **Commit**: YES
  - Message: `test: vendor helpers.extension.Extension stub for wrapper tests`
  - Files: `tests/wrapper/conftest.py`
  - Pre-commit: `python -m pytest tests/wrapper/ -v` (collection only — should pass with no tests)

- [x] 14. **Rewrite `extensions/python/monologue_start/_60_cortex_init.py` as thin wrapper + wrapper test (TDD)**

  **What to do** (RED → GREEN → REFACTOR):
  - **RED**: Write `tests/wrapper/test_init_wrapper.py` with ≥7 cases:
    - `CortexInit(agent=fake_agent).execute()` calls `cortex_plugin.config.load_config()`
    - **Project lookup uses canonical AZ helper**: test asserts `helpers.projects.get_context_project_name(self.agent.context)` is called (verified via mock); the fake_agent.context has `get_data("project") -> "homelab"` and the test verifies the wrapper picks up "homelab" through that path (not via `current_project` attribute)
    - Project lookup fallback: when `get_context_project_name` raises, wrapper falls back to `current_project` attribute (test by patching helper to raise; ensure wrapper continues with `getattr` fallback)
    - When config disabled or no api_key: returns silently, no HTTP calls
    - On valid config: calls `cortex_plugin.http.cortex_post("/v1/sessions", ...)` once with body `{"external_session_id": ctx.id, "source": "az", "initial_topic_slug": <slug or None>}`
    - On 200: calls `agent.context.set_data("cortex_session_id", <returned id>)` AND `agent.context.set_data("cortex_project_slug", <slug>)` AND `agent.context.set_data("cortex_project_name", <original>)`
    - For project-less (project_resolve returns None slug): no topic-lock POST; sets `cortex_project_slug=None`
    - For project session: AFTER session POST, calls `cortex_post("/v1/sessions/{id}/topic", body={"topic":<slug>, "lock":True, "create_if_missing":True})` ONCE
    - On HTTP exception: no exception escapes; logs warning; returns silently
    - Logs INFO once per successful fire: `cortex.init: session=<uuid> project=<slug or none>`
  - **GREEN**: Rewrite `_60_cortex_init.py`:
    - Imports: `import logging; from cortex_plugin import config, http, slugs; from helpers.extension import Extension; from helpers import projects as proj_helpers` (lazy/late-bind helpers.projects inside execute() if you prefer to keep import surface small; either pattern is fine)
    - `class CortexInit(Extension):` with async `execute(self, **kwargs)` that orchestrates
    - **Project lookup (canonical AZ pattern)**: `project_name = proj_helpers.get_context_project_name(self.agent.context)` — this is the AZ-canonical path. If that raises (e.g., older AZ where helper signature differs), fall back to `getattr(self.agent.context, "current_project", None)` for legacy compat. Document both paths in the wrapper.
    - All business logic delegated to pure functions (config.load, slugs.project_resolve, http.cortex_post)
    - Top-level try/except catches everything, logs warning, returns
  - **REFACTOR**: Ensure no business logic in the wrapper; ≤40 lines of orchestration

  **Must NOT do**:
  - Don't put any HTTP construction or slug logic in the wrapper — call pure functions
  - Don't add new env vars
  - Don't break the public set_data keys (keep `cortex_session_id` for backward compat with `_60_cortex_memorize.py` and `_60_cortex_recall.py`)
  - Don't import from `extensions/` siblings — wrappers don't share code with each other

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Wrapper logic + AZ runtime contract correctness
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T15, T16)
  - **Parallel Group**: Wave 3
  - **Blocks**: T17 (integration session lifecycle)
  - **Blocked By**: T6, T8, T10, T13

  **References**:
  - **Pattern**: existing `extensions/python/monologue_start/_60_cortex_init.py:1-82` — current behavior to preserve (session create, set_data) + add (topic lock)
  - **API**: Cortex `POST /v1/sessions` and `POST /v1/sessions/{id}/topic` from research bg_56e873e6
  - **Test**: T13 conftest provides `Extension` stub

  **Acceptance Criteria** (TDD):
  - [ ] `tests/wrapper/test_init_wrapper.py` exists with ≥6 cases
  - [ ] `python -m pytest tests/wrapper/test_init_wrapper.py -v` exits 0
  - [ ] Wrapper file ≤80 lines (excluding docstrings); business logic in pure lib only
  - [ ] No HTTP/regex code in wrapper: `! grep -E "httpx|re\.compile|hashlib" extensions/python/monologue_start/_60_cortex_init.py`

  **QA Scenarios**:
  ```
  Scenario: TDD red→green for wrapper
    Tool: Bash + pytest
    Steps:
      1. Write tests/wrapper/test_init_wrapper.py mocking cortex_plugin.config, http, slugs (use unittest.mock.patch)
      2. pytest tests/wrapper/test_init_wrapper.py -v 2>&1 | tee .sisyphus/evidence/task-14-red.txt
      3. Rewrite _60_cortex_init.py as thin orchestration over pure lib
      4. pytest tests/wrapper/test_init_wrapper.py -v 2>&1 | tee .sisyphus/evidence/task-14-green.txt
    Expected Result: red FAIL, green ALL PASSED
    Evidence: task-14-red.txt, task-14-green.txt

  Scenario: Topic-lock POST happens for project session
    Tool: pytest
    Steps:
      1. test_topic_lock_for_project: fake_agent.context.current_project = "homelab"; mock cortex_post; call execute(); assert cortex_post called twice — once for /v1/sessions, once for /v1/sessions/{id}/topic
      2. pytest tests/wrapper/test_init_wrapper.py::test_topic_lock_for_project -v 2>&1 | tee .sisyphus/evidence/task-14-topiclock.txt
    Expected Result: PASSED
    Evidence: task-14-topiclock.txt

  Scenario: Project-less skips topic POST
    Tool: pytest
    Steps:
      1. test_no_topic_lock_projectless: fake_agent.context.current_project = None; mock cortex_post; call execute(); assert cortex_post called ONCE only (just /v1/sessions)
      2. pytest tests/wrapper/test_init_wrapper.py::test_no_topic_lock_projectless -v 2>&1 | tee .sisyphus/evidence/task-14-noprojectlock.txt
    Expected Result: PASSED
    Evidence: task-14-noprojectlock.txt

  Scenario: Wrapper purity (no business logic in extension file)
    Tool: Bash
    Steps:
      1. wc -l extensions/python/monologue_start/_60_cortex_init.py | tee .sisyphus/evidence/task-14-wc.txt
      2. ! grep -E "httpx|re\.compile|hashlib" extensions/python/monologue_start/_60_cortex_init.py | tee .sisyphus/evidence/task-14-purity.txt
    Expected Result: line count ≤80; purity grep returns empty
    Evidence: task-14-wc.txt, task-14-purity.txt
  ```

  **Evidence**: `task-14-red.txt`, `task-14-green.txt`, `task-14-topiclock.txt`, `task-14-noprojectlock.txt`, `task-14-wc.txt`, `task-14-purity.txt`

  **Commit**: YES
  - Message: `feat: rewrite _60_cortex_init.py as thin wrapper over pure lib`
  - Files: `extensions/python/monologue_start/_60_cortex_init.py`, `tests/wrapper/test_init_wrapper.py`
  - Pre-commit: `python -m pytest tests/wrapper/test_init_wrapper.py -v`

- [x] 15. **Rewrite `extensions/python/monologue_end/_60_cortex_memorize.py` as thin wrapper + wrapper test (TDD)**

  **What to do** (RED → GREEN → REFACTOR):
  - **RED**: Write `tests/wrapper/test_memorize_wrapper.py` with ≥9 cases:
    - When config disabled or no api_key: returns silently
    - When `cortex_session_id` not set in context: logs warning, returns silently
    - **Project lookup uses canonical helper**: test that `helpers.projects.get_context_project_name(ctx)` is called for stale-project detection (mock the helper, verify call); when stored slug "homelab" != fresh-resolved "luthien" → info log "project changed mid-session"
    - On valid context: calls `agent.concat_messages(agent.history)` to get `messages_str`
    - Calls `cortex_plugin.prompts.load_fragments_prompt()` and `load_solutions_prompt()`
    - Calls `cortex_plugin.extraction.extract_fragments_and_solutions(messages_str, agent.call_utility_model, frag_prompt, sol_prompt, timeout_sec=5)` once
    - Calls `cortex_plugin.extraction.write_memories_to_cortex(session_id, project_slug, fragments, solutions, http_post, posting_timeout_sec=10)` once
    - Total wall-clock < 16s (5s + 10s + buffer for setup)
    - Logs INFO once with structured format: `cortex.memorize: written=<n> failed=<n> timed_out=<bool> ms=<n>`
    - On any unhandled exception in pure-lib calls: catches, logs warning, returns (non-fatal)
    - **Critical (per Metis E12)**: For memorize, test that no `extras_persistent["memories"]` mutation happens (memorize doesn't touch extras — that's recall's job)
  - **GREEN**: Rewrite `_60_cortex_memorize.py`:
    - Import: `from cortex_plugin import config, http, prompts, slugs, extraction; from helpers.extension import Extension; from helpers import projects as proj_helpers`
    - `class CortexMemorize(Extension):` with async `execute(self, loop_data=None, **kwargs)`
    - Read session_id and stored project info from `agent.context.get_data("cortex_session_id")` and `get_data("cortex_project_slug")`
    - **Stale-project escape hatch (canonical lookup)**: re-resolve current project via `proj_helpers.get_context_project_name(self.agent.context)` (with fallback to `getattr(ctx, "current_project", None)` if helper raises); if resolved slug differs from stored `cortex_project_slug`, log info "project changed mid-session: <old> → <new>" and use new slug for this memorize call. (Don't try to re-bind topic from inside memorize — let next monologue's init handle it.)
    - Build `http_post` partial: `partial(http.cortex_post, base_url=cfg.url, api_key=cfg.api_key, ...)` for the extraction.write to use
    - Wrap entire flow in `try/except Exception as e: logger.warning(...)` — non-fatal contract
  - **REFACTOR**: Ensure wrapper is ≤100 lines; all logic in pure lib

  **Must NOT do**:
  - Don't read `loop_data.fragments` or `loop_data.solutions` (deprecated path; we extract independently now)
  - Don't add FAISS mtime check (FAISS is gone — code DELETED in this rewrite)
  - Don't keep the `CORTEX_FAISS_ASSERTION_CHECK` env var read
  - Don't add cross-link metadata (impossible, see T11)
  - Don't parallelize POSTs (per T11)
  - Don't catch exceptions inside the loop and continue silently — let extraction.py's partial-success handle that

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Stale-project handling, AZ-runtime calls (call_utility_model, concat_messages), timing constraints
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T14, T16)
  - **Parallel Group**: Wave 3
  - **Blocks**: T18 (integration memorize roundtrip)
  - **Blocked By**: T6, T7, T8, T9, T10, T11, T13

  **References**:
  - **Pattern**: existing `extensions/python/monologue_end/_60_cortex_memorize.py` — DELETE all of it, including the FAISS mtime block (lines 79–128)
  - **Pattern**: `/Users/paolo/Documents/Projects/agent-zero/plugins/_memory/extensions/python/monologue_end/_50_memorize_fragments.py:14-36` — the `DeferredTask` pattern is what AZ uses; we're choosing awaited-with-timeout instead (per user decision)
  - **API**: `agent.call_utility_model(system: str, message: str) -> Awaitable[str]` and `agent.concat_messages(agent.history) -> str` (from research bg_f8211492)

  **Acceptance Criteria** (TDD):
  - [ ] `tests/wrapper/test_memorize_wrapper.py` exists with ≥8 cases
  - [ ] `python -m pytest tests/wrapper/test_memorize_wrapper.py -v` exits 0
  - [ ] No FAISS code: `! grep -E "(faiss|FAISS|mtime|index\.faiss)" extensions/python/monologue_end/_60_cortex_memorize.py`
  - [ ] Wrapper file ≤100 lines

  **QA Scenarios**:
  ```
  Scenario: TDD red→green
    Tool: Bash + pytest
    Steps:
      1. Write tests/wrapper/test_memorize_wrapper.py with ≥8 cases (mock cortex_plugin.* and agent.call_utility_model)
      2. pytest tests/wrapper/test_memorize_wrapper.py -v 2>&1 | tee .sisyphus/evidence/task-15-red.txt
      3. Rewrite _60_cortex_memorize.py
      4. pytest tests/wrapper/test_memorize_wrapper.py -v 2>&1 | tee .sisyphus/evidence/task-15-green.txt
    Expected Result: red FAIL, green ALL PASSED
    Evidence: task-15-red.txt, task-15-green.txt

  Scenario: Stale-project escape hatch
    Tool: pytest
    Steps:
      1. test_stale_project_rebinds: simulate stored slug "homelab", current_project changed to "luthien"; assert info log "project changed mid-session"; new slug used in POST bodies (verified via mock call_args_list on http.cortex_post)
      2. pytest tests/wrapper/test_memorize_wrapper.py::test_stale_project_rebinds -v 2>&1 | tee .sisyphus/evidence/task-15-stale.txt
    Expected Result: PASSED
    Evidence: task-15-stale.txt

  Scenario: No FAISS code remains
    Tool: Bash
    Steps:
      1. ! grep -E "(faiss|FAISS|mtime|index\.faiss|CORTEX_FAISS_ASSERTION_CHECK)" extensions/python/monologue_end/_60_cortex_memorize.py | tee .sisyphus/evidence/task-15-faissfree.txt
    Expected Result: empty (no matches)
    Evidence: task-15-faissfree.txt

  Scenario: Wall-clock under 16s with mocked slow components
    Tool: pytest
    Steps:
      1. test_total_wallclock_under_16s: mock extraction to take 4s, write_memories_to_cortex to take 9s; assert total wall-clock < 16s; assert one INFO log line emitted with `ms=` field present
      2. pytest tests/wrapper/test_memorize_wrapper.py::test_total_wallclock_under_16s -v 2>&1 | tee .sisyphus/evidence/task-15-wallclock.txt
    Expected Result: PASSED
    Evidence: task-15-wallclock.txt
  ```

  **Evidence**: `task-15-red.txt`, `task-15-green.txt`, `task-15-stale.txt`, `task-15-faissfree.txt`, `task-15-wallclock.txt`

  **Commit**: YES
  - Message: `feat: rewrite _60_cortex_memorize.py as thin wrapper over pure lib`
  - Files: `extensions/python/monologue_end/_60_cortex_memorize.py`, `tests/wrapper/test_memorize_wrapper.py`
  - Pre-commit: `python -m pytest tests/wrapper/test_memorize_wrapper.py -v`

- [x] 16. **Rewrite `extensions/python/message_loop_prompts_after/_60_cortex_recall.py` as thin wrapper + wrapper test (TDD)**

  **What to do** (RED → GREEN → REFACTOR):
  - **RED**: Write `tests/wrapper/test_recall_wrapper.py` with ≥8 cases:
    - When config disabled or `cortex_session_id` missing: returns silently, no HTTP, no `extras` mutation
    - On valid state: extracts query from `loop_data.messages[-1].content` truncated to 500 chars
    - When query length < 3 chars (after strip): skips recall (no HTTP call); existing `extras["memories"]` left UNCHANGED (don't accidentally clear)
    - **Project lookup uses canonical helper**: test that `helpers.projects.get_context_project_name(ctx)` is called at each fire (mock the helper, verify call); resolved slug is passed to `recall_and_format` as `current_project_slug`
    - Calls `cortex_plugin.recall.recall_and_format(query, session_id, current_project_slug, http_post, threshold=cfg.recall_threshold, legacy_rank=cfg.recall_legacy_rank)` once — verify both config-derived params plumbed correctly via mock spy
    - **Legacy-rank toggle test**: with `CORTEX_RECALL_LEGACY_RANK=true` set, wrapper passes `legacy_rank=True` to `recall_and_format`; with unset/false, passes `legacy_rank=False`
    - On non-empty result: REPLACES `loop_data.extras_persistent["memories"]` with returned block (set, not append)
    - On empty result: sets `loop_data.extras_persistent["memories"] = ""` (clear stale FAISS leftovers from previous iterations)
    - On HTTP exception: catches, logs warning, leaves `extras["memories"]` UNCHANGED (no clobber)
    - Logs INFO: `cortex.recall: results=<n> after_fence=<n> project=<slug or none> ms=<n>`
  - **GREEN**: Rewrite `_60_cortex_recall.py`:
    - Imports: `from cortex_plugin import config, http, slugs, recall as recall_lib; from helpers.extension import Extension; from helpers import projects as proj_helpers`
    - `class CortexRecall(Extension):` with async `execute(self, loop_data=None, **kwargs)`
    - **Project lookup (canonical AZ pattern + fallback)**: at each fire, resolve current project via `proj_helpers.get_context_project_name(self.agent.context)` (with fallback to `getattr(ctx, "current_project", None)` if helper raises); use resolved slug for the fence partition (current_project_slug param to recall_and_format)
    - **Plumb config to recall_and_format**: read `cfg = config.load_config()`; pass `threshold=cfg.recall_threshold` and `legacy_rank=cfg.recall_legacy_rank` to `recall_lib.recall_and_format(...)`. This makes Cortex version compatibility env-driven without code changes.
    - All other logic delegated; wrapper just orchestrates
    - Ensure 15s overall recall budget (much less in practice; just safety)
  - **REFACTOR**: Ensure ≤80 lines; structured logging

  **Must NOT do**:
  - Don't APPEND to `extras["memories"]` — REPLACE (per user decision Round 1)
  - Don't preserve any "FAISS block" prefix — there isn't one anymore
  - Don't include the `CORTEX_MERGE_STRATEGY=off` branch (env var removed)
  - Don't filter results by `area` (Cortex doesn't return area; we shouldn't anyway)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Replace-vs-no-clobber semantics across error paths; subtle state transitions
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T14, T15)
  - **Parallel Group**: Wave 3
  - **Blocks**: T19 (integration recall quality)
  - **Blocked By**: T6, T8, T10, T12, T13

  **References**:
  - **Pattern**: existing `extensions/python/message_loop_prompts_after/_60_cortex_recall.py:1-93` — DELETE most; current append-mode is being replaced by replace-mode
  - **Pattern**: built-in `_50_recall_memories.py:60-70` — they `del extras["memories"]` before populating; we set `=""` for clarity

  **Acceptance Criteria** (TDD):
  - [ ] `tests/wrapper/test_recall_wrapper.py` exists with ≥7 cases
  - [ ] `python -m pytest tests/wrapper/test_recall_wrapper.py -v` exits 0
  - [ ] Wrapper file ≤80 lines
  - [ ] No `MERGE_STRATEGY` reference: `! grep -E "MERGE_STRATEGY|merge_strategy|append_mode" extensions/python/message_loop_prompts_after/_60_cortex_recall.py`

  **QA Scenarios**:
  ```
  Scenario: TDD red→green
    Tool: Bash + pytest
    Steps:
      1. Write tests/wrapper/test_recall_wrapper.py with ≥7 cases
      2. pytest tests/wrapper/test_recall_wrapper.py -v 2>&1 | tee .sisyphus/evidence/task-16-red.txt
      3. Rewrite _60_cortex_recall.py
      4. pytest tests/wrapper/test_recall_wrapper.py -v 2>&1 | tee .sisyphus/evidence/task-16-green.txt
    Expected Result: red FAIL, green ALL PASSED
    Evidence: task-16-red.txt, task-16-green.txt

  Scenario: Replace, not append
    Tool: pytest
    Steps:
      1. test_replaces_extras: pre-set fake_loop.extras_persistent["memories"] = "OLD_FAISS_CONTENT"; mock recall_and_format to return "## Memories\n\nNEW"; call execute(); assert extras["memories"] == "## Memories\n\nNEW" (no "OLD_FAISS_CONTENT" remnant)
      2. pytest tests/wrapper/test_recall_wrapper.py::test_replaces_extras -v 2>&1 | tee .sisyphus/evidence/task-16-replace.txt
    Expected Result: PASSED
    Evidence: task-16-replace.txt

  Scenario: HTTP failure leaves extras UNCHANGED
    Tool: pytest
    Steps:
      1. test_failure_no_clobber: pre-set extras["memories"] = "PREVIOUS_VALUE"; mock recall_and_format to raise httpx.RequestError; call execute(); assert extras["memories"] == "PREVIOUS_VALUE" (unchanged); assert warning logged
      2. pytest tests/wrapper/test_recall_wrapper.py::test_failure_no_clobber -v 2>&1 | tee .sisyphus/evidence/task-16-noclobber.txt
    Expected Result: PASSED
    Evidence: task-16-noclobber.txt

  Scenario: Empty results clear stale extras
    Tool: pytest
    Steps:
      1. test_empty_clears_stale: pre-set extras["memories"] = "STALE_FAISS"; mock recall_and_format to return ""; assert extras["memories"] == "" (cleared)
      2. pytest tests/wrapper/test_recall_wrapper.py::test_empty_clears_stale -v 2>&1 | tee .sisyphus/evidence/task-16-empty-clear.txt
    Expected Result: PASSED
    Evidence: task-16-empty-clear.txt
  ```

  **Evidence**: `task-16-red.txt`, `task-16-green.txt`, `task-16-replace.txt`, `task-16-noclobber.txt`, `task-16-empty-clear.txt`

  **Commit**: YES
  - Message: `feat: rewrite _60_cortex_recall.py as thin wrapper over pure lib`
  - Files: `extensions/python/message_loop_prompts_after/_60_cortex_recall.py`, `tests/wrapper/test_recall_wrapper.py`
  - Pre-commit: `python -m pytest tests/wrapper/test_recall_wrapper.py -v`

- [x] 15.5. **`scripts/calibrate-recall-threshold.sh` — Cortex version-aware threshold calibration utility**

  **What to do**:
  - Create `scripts/calibrate-recall-threshold.sh` (bash) + `scripts/calibrate_recall_threshold.py` (python helper, called by the bash wrapper)
  - **Inputs**: env vars `CORTEX_URL`, `CORTEX_API_KEY`, plus a fixed golden query set at `scripts/golden-queries.json` (50 queries with marker `[CALIB-{uuid}]` content, half tagged `relevant`, half `irrelevant`)
  - **Procedure** (idempotent):
    1. POST 50 calibration memories to Cortex with unique `[CALIB-{run-uuid}]` content prefix and known `source_project="_calibration"` tag (fixed test session_id derived from run timestamp; cleanup-tracked)
    2. Wait 5s for embedding generation to settle
    3. For each of 50 queries: POST `/v1/recall` with `threshold=0.0, limit=50`, capture all returned `score` values (and whether each result's content matches the relevant/irrelevant labeling)
    4. Compute score distribution stats: min, p5, p25, p50, p75, p95, max — separately for `relevant` matches and `irrelevant` matches
    5. **Recommended threshold = max(p25 of irrelevant scores, 5th-percentile of relevant scores)** — this is the "noise floor that doesn't lose true positives" heuristic
    6. Also compute distribution with `?legacy_rank=true` query string (if Cortex v1.1+ active) and produce a comparison report
    7. Output JSON to `.sisyphus/evidence/calibration/threshold-recommendation-{date}.json` containing: detected scoring algorithm hint (RRF-like if max < 0.10, composite-like if max > 0.20), recommended threshold value, recommended `CORTEX_RECALL_LEGACY_RANK` setting, raw stats
    8. **Cleanup**: forget all calibration memories (track IDs from POST responses; POST forget action for each); verify residue == 0 via content-prefix-filtered recall
  - **Output a single human-readable line at the end**: `RECOMMENDED: CORTEX_RECALL_THRESHOLD=<value> CORTEX_RECALL_LEGACY_RANK=<bool>`
  - **Document in `MIGRATION.md`** (T21 will reference this): "Run after every Cortex version upgrade or scoring-algorithm change"
  - Marked `@pytest.mark.integration` if invoked via pytest; runnable standalone via bash

  **Must NOT do**:
  - Don't pollute production memories: `[CALIB-{run-uuid}]` prefix unique per run; cleanup is mandatory
  - Don't run more than 50 calibration POSTs total (cost control: ~$0.001 per run at OpenAI embedding rates)
  - Don't trust a single run — script should be run-multiple-times-and-average if results are noisy
  - Don't fail script execution on cleanup errors — log warnings, continue (operator can manually clean up by recall + forget)
  - Don't hardcode threshold guesses — empirical only

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Empirical measurement script + Cortex API contract usage; runs against live Cortex
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T17, T18, T19, T19.5, T20, T21, T22)
  - **Parallel Group**: Wave 4
  - **Blocks**: F1 (compliance audit checks calibration script exists), F3 (live deploy verification can re-run calibration post-deploy)
  - **Blocked By**: T8 (config), T10 (http), T12 (recall pure-lib) — needs the working library to call Cortex

  **References**:
  - Cortex API contract from research bg_56e873e6 — `POST /v1/recall` schema
  - Cortex v1.1 plan composite-scoring formula: `0.5·semantic + 0.3·recency + 0.2·importance`
  - Cortex v1.1 plan line 116: `?legacy_rank=true` backward-compat query parameter
  - This plan's "Cortex Version Compatibility Matrix" — which threshold ranges are expected per Cortex version

  **Acceptance Criteria**:
  - [ ] `scripts/calibrate-recall-threshold.sh` exists, executable (`chmod +x`)
  - [ ] `scripts/calibrate_recall_threshold.py` exists, no forbidden imports
  - [ ] `scripts/golden-queries.json` exists with ≥50 entries, each `{id, query, label: "relevant"|"irrelevant", expected_content: str}`
  - [ ] Running script against current Cortex (MVP scoring) outputs a recommendation in range `0.01`–`0.05` (RRF-like distribution)
  - [ ] Script's cleanup leaves zero residue: post-run recall for `[CALIB-]` prefix returns 0 matching results
  - [ ] Output JSON at `.sisyphus/evidence/calibration/threshold-recommendation-*.json` is valid JSON parseable by `jq`

  **QA Scenarios**:
  ```
  Scenario: Calibration runs end-to-end against live Cortex (MVP)
    Tool: Bash + curl + jq
    Preconditions: CORTEX_URL=http://192.168.1.12:8001 and CORTEX_API_KEY env set; LAN reachable; Cortex MVP scoring active
    Steps:
      1. CORTEX_URL=$CORTEX_URL CORTEX_API_KEY=$CORTEX_API_KEY bash scripts/calibrate-recall-threshold.sh 2>&1 | tee .sisyphus/evidence/task-15.5-run.txt
      2. ls .sisyphus/evidence/calibration/threshold-recommendation-*.json
      3. jq '.recommended.threshold' .sisyphus/evidence/calibration/threshold-recommendation-*.json
      4. jq '.recommended.legacy_rank' .sisyphus/evidence/calibration/threshold-recommendation-*.json
      5. jq '.detected_scoring_hint' .sisyphus/evidence/calibration/threshold-recommendation-*.json
    Expected Result: script exits 0; JSON file present; threshold value is a number in [0.01, 0.50]; legacy_rank is bool; scoring hint is "rrf_like" (current MVP) or "composite_like" (post-v1.1)
    Evidence: task-15.5-run.txt, .sisyphus/evidence/calibration/threshold-recommendation-{date}.json

  Scenario: Cleanup leaves zero residue (content-prefix-filtered)
    Tool: Bash + curl + jq
    Preconditions: calibration script just completed
    Steps:
      1. curl -s -H "Authorization: Bearer $CORTEX_API_KEY" -H 'Content-Type: application/json' -X POST 'http://192.168.1.12:8001/v1/recall' -d '{"query":"[CALIB-","threshold":0.0,"limit":100}' > /tmp/calib-residue.json
      2. jq '[.[] | select(.content | startswith("[CALIB-"))] | length' /tmp/calib-residue.json | tee .sisyphus/evidence/task-15.5-residue.txt
    Expected Result: residue == 0
    Failure Indicators: residue > 0 → cleanup logic broken
    Evidence: task-15.5-residue.txt

  Scenario: Recommendation matches Cortex MVP expectations
    Tool: jq
    Steps:
      1. jq -e '.detected_scoring_hint == "rrf_like"' .sisyphus/evidence/calibration/threshold-recommendation-*.json
      2. jq -e '.recommended.threshold >= 0.01 and .recommended.threshold <= 0.10' .sisyphus/evidence/calibration/threshold-recommendation-*.json
      3. jq -e '.recommended.legacy_rank == false' .sisyphus/evidence/calibration/threshold-recommendation-*.json
    Expected Result: all three jq -e succeed (exit 0). For Cortex MVP, expect rrf_like hint, threshold in 0.01-0.10 range, legacy_rank=false
    Evidence: implicit in JSON output

  Scenario: Idempotent — multiple runs produce stable recommendations (within ±20%)
    Tool: Bash + jq
    Steps:
      1. Run calibration 3 times in a row (each run uses unique CALIB-{run-uuid}-N prefix and cleans up after itself)
      2. Compute mean and stddev of the 3 recommended thresholds via jq
      3. Assert: stddev / mean < 0.20 (recommendations are stable across runs)
    Expected Result: stable recommendations
    Note: mark this scenario `@pytest.mark.slow` — only run during initial validation, not on every CI loop
    Evidence: .sisyphus/evidence/task-15.5-stability.txt
  ```

  **Evidence**: `task-15.5-run.txt`, `task-15.5-residue.txt`, `task-15.5-stability.txt`, `.sisyphus/evidence/calibration/threshold-recommendation-*.json`

  **Commit**: YES
  - Message: `feat(scripts): recall threshold calibration utility for Cortex version compat`
  - Files: `scripts/calibrate-recall-threshold.sh`, `scripts/calibrate_recall_threshold.py`, `scripts/golden-queries.json`
  - Pre-commit: `bash scripts/calibrate-recall-threshold.sh && jq '.recommended.threshold' .sisyphus/evidence/calibration/threshold-recommendation-*.json`

- [x] 17. **Integration test — session lifecycle (init + topic-lock + project-less)**

  **What to do**:
  - Write `tests/integration/test_session_lifecycle.py` marked with `@pytest.mark.integration` (top-level marker on every test)
  - Test happy path: POST /v1/sessions with `external_session_id="test-{uuid4}"`, source="az", initial_topic_slug="cortex-test"; verify 201 response with valid `id`
  - Test idempotent re-create: same external_session_id+source returns same id (Cortex `ON CONFLICT` semantics)
  - Test topic-lock: POST /v1/sessions/{id}/topic with `{topic: "cortex-test", lock: true, create_if_missing: true}`; verify 200 and that subsequent GET /v1/sessions/{id} returns `topic_locked=true`
  - Test project-less: POST /v1/sessions WITHOUT `initial_topic_slug`; verify session created without bound topic
  - Cleanup: NO server-side cleanup needed (sessions persist; identifiable via `test-` prefix on `external_session_id`)
  - Run only when `CORTEX_URL` and `CORTEX_API_KEY` env vars are set; otherwise skip via pytest fixture

  **Must NOT do**:
  - Don't pollute production: ALL test session_ids must use `test-{uuid4}` prefix
  - Don't run by default — `pytest -m integration` only
  - Don't depend on Cortex being seeded with specific topics; use `create_if_missing=true`
  - Don't leak the API key in evidence files

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Real network calls + Cortex contract verification
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T18, T19, T20, T21, T22)
  - **Parallel Group**: Wave 4
  - **Blocks**: F1, F2, F3, F4 (final review wave)
  - **Blocked By**: T14 (init wrapper); also benefits from T10, T8

  **References**:
  - **API**: Cortex `/v1/sessions` and `/v1/sessions/{id}/topic` contracts from research bg_56e873e6
  - **Test pattern**: `tests/wrapper/test_init_wrapper.py` from T14 — but here using REAL httpx, not mocks

  **Acceptance Criteria**:
  - [ ] `tests/integration/test_session_lifecycle.py` exists with ≥4 tests, all marked `@pytest.mark.integration`
  - [ ] `pytest tests/integration/test_session_lifecycle.py -v -m integration` exits 0 when CORTEX_URL/CORTEX_API_KEY set
  - [ ] Default run with `-m 'not integration'` (from pyproject.toml addopts) deselects all integration tests; pytest exits **5** (no tests ran) — verify with `pytest tests/integration/test_session_lifecycle.py -v; [ $? -eq 5 ]`. Exit 5 is the canonical pytest "no tests collected/all deselected" code, not exit 0.

  **QA Scenarios**:
  ```
  Scenario: Live session lifecycle test passes
    Tool: Bash + pytest
    Preconditions: CORTEX_URL=http://192.168.1.12:8001 and CORTEX_API_KEY env set; LAN reachable
    Steps:
      1. CORTEX_URL=http://192.168.1.12:8001 CORTEX_API_KEY=$CORTEX_API_KEY pytest tests/integration/test_session_lifecycle.py -v -m integration 2>&1 | tee .sisyphus/evidence/task-17-live.txt
    Expected Result: ALL PASSED (≥4 tests); evidence shows 200/201 status codes and valid topic_locked=true return
    Evidence: task-17-live.txt

  Scenario: Default run deselects integration tests (pytest exit 5)
    Tool: Bash + pytest
    Steps:
      1. unset CORTEX_URL CORTEX_API_KEY
      2. pytest tests/integration/test_session_lifecycle.py -v 2>&1 | tee .sisyphus/evidence/task-17-deselected.txt
      3. echo "exit_code=$?" >> .sisyphus/evidence/task-17-deselected.txt
    Expected Result: pytest output shows "deselected" or "no tests ran"; recorded exit_code=5 (pytest's standard code for no-tests-collected). Default `-m 'not integration'` filter from pyproject.toml causes deselection.
    Evidence: task-17-deselected.txt
  ```

  **Evidence**: `task-17-live.txt`, `task-17-skipped.txt`

  **Commit**: YES
  - Message: `test(integration): session lifecycle (init, topic-lock, project-less)`
  - Files: `tests/integration/test_session_lifecycle.py`
  - Pre-commit: `pytest tests/wrapper/ tests/unit/ -v` (don't run integration in pre-commit)

- [x] 18. **Integration test — memorize roundtrip (extraction → POST → readback)**

  **What to do**:
  - Write `tests/integration/test_memorize_roundtrip.py` marked `@pytest.mark.integration`
  - Test: create session → POST 2 fragments + 1 solution (yields 3 memory POSTs total: 2 fragments + problem + solution-step) → wait briefly → confirm memories visible
    - Use direct HTTP calls (don't go through Extension wrapper here — wrapper is tested in T15; this verifies the **Cortex contract** end-to-end)
    - Idempotency keys deterministic from `(session_id, area, content)`
  - Test: replay POST with same idempotency key → server returns existing memory id; total count UNCHANGED (verify via /v1/recall searching for the test content with threshold=0.0 limit=20)
  - Test: forget action removes a memory (POST `{action: "forget", memory_id: ...}`; subsequent recall confirms it's no longer in active results)
  - Test: timeout-style failure simulation — POST with `httpx.AsyncClient(timeout=0.1)` confirms `httpx.TimeoutException` propagates correctly (this is the unit-equivalent for confirming our http.py contract under real network conditions)
  - All test memories use content prefix **`[TEST-T18-MEMORIZE]`** (unique to this test file — distinct from T19's `[TEST-T19-RECALL]` to prevent residue collision)
  - **Track created memory IDs explicitly** in a module-level `list[str]` populated as each test creates memories (the POST `/v1/memories` response returns `id`)
  - **Cleanup (mandatory)**: use a pytest fixture with `yield` + finalizer at module scope that:
    1. Iterates the tracked-IDs list and POSTs `{"action":"forget","memory_id":<id>}` for each
    2. Verification step: query `POST /v1/recall` with `{"query": "[TEST-T18-MEMORIZE]", "threshold": 0.0, "limit": 100}`, then **filter results client-side** to count only those whose `content` field contains the literal substring `"[TEST-T18-MEMORIZE]"`. The filtered count must be `0`. (Recall may return unrelated top-K memories at threshold 0.0; only matching content counts as residue.)
  - DO NOT rely on recall results to identify what to forget — track IDs from POST responses. DO NOT count un-prefixed memories as residue (other tests' memories may still be in Cortex).

  **Must NOT do**:
  - Don't measure latency precisely (T3 spike covered baseline; this is correctness)
  - Don't modify production Cortex topics
  - Don't write more than 10 memories total in this test file (cost control)
  - Don't depend on classification results (it's async)
  - Don't use `[TEST-CORTEX-PRIMARY]` or any prefix shared with T19 — each integration test file owns its own unique prefix
  - Don't skip cleanup on test failure (use `try/finally` or pytest finalizer to guarantee forget-action runs)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T17, T19, T20, T21, T22)
  - **Parallel Group**: Wave 4
  - **Blocks**: F1-F4
  - **Blocked By**: T11 (extraction logic), T15 (memorize wrapper)

  **References**:
  - **API**: Cortex `/v1/memories` POST and forget action; `/v1/recall` for readback (research bg_56e873e6)
  - **Pattern**: T11 `write_memories_to_cortex` — same payload schema

  **Acceptance Criteria**:
  - [ ] `tests/integration/test_memorize_roundtrip.py` exists with ≥4 tests
  - [ ] All tests marked `@pytest.mark.integration`
  - [ ] `pytest tests/integration/test_memorize_roundtrip.py -v -m integration` exits 0
  - [ ] Memories created during test are recallable via `/v1/recall` with threshold 0.0
  - [ ] **Post-test cleanup verified by content-prefix filter**: after all tests pass, run `curl ... /v1/recall -d '{"query":"[TEST-T18-MEMORIZE]","threshold":0.0,"limit":100}' | jq '[.[] | select(.content | contains("[TEST-T18-MEMORIZE]"))] | length'` — returns `0`. (Note the `select(...contains(...))` filter — recall returns top-K including unrelated memories at threshold 0.0; only content-matching results count as T18 residue.)

  **QA Scenarios**:
  ```
  Scenario: Memorize → Recall roundtrip
    Tool: Bash + pytest
    Preconditions: CORTEX_URL/CORTEX_API_KEY set
    Steps:
      1. CORTEX_URL=http://192.168.1.12:8001 CORTEX_API_KEY=$CORTEX_API_KEY pytest tests/integration/test_memorize_roundtrip.py -v -m integration 2>&1 | tee .sisyphus/evidence/task-18-roundtrip.txt
    Expected Result: ALL PASSED; ≥4 tests; the recall test shows the just-written memory in results
    Evidence: task-18-roundtrip.txt

  Scenario: Idempotency works server-side
    Tool: pytest (subset)
    Steps:
      1. pytest tests/integration/test_memorize_roundtrip.py::test_replay_no_duplicates -v -m integration 2>&1 | tee .sisyphus/evidence/task-18-idem.txt
    Expected Result: PASSED — replaying same idempotency-keyed write returns existing id; recall count unchanged
    Evidence: task-18-idem.txt

  Scenario: Forget action verified
    Tool: pytest (subset)
    Steps:
      1. pytest tests/integration/test_memorize_roundtrip.py::test_forget_removes_memory -v -m integration 2>&1 | tee .sisyphus/evidence/task-18-forget.txt
    Expected Result: PASSED — forgotten memory absent from recall results
    Evidence: task-18-forget.txt

  Scenario: Cleanup leaves zero T18-prefixed residue (proves no cross-test pollution with T19)
    Tool: Bash + curl + jq
    Preconditions: full test run completed (finalizer fired)
    Steps:
      1. curl -s -H "Authorization: Bearer $CORTEX_API_KEY" -H 'Content-Type: application/json' -X POST 'http://192.168.1.12:8001/v1/recall' -d '{"query":"[TEST-T18-MEMORIZE]","threshold":0.0,"limit":100}' > /tmp/task-18-recall.json
      2. jq '[.[] | select(.content | contains("[TEST-T18-MEMORIZE]"))] | length' /tmp/task-18-recall.json | tee .sisyphus/evidence/task-18-residue.txt
      3. cp /tmp/task-18-recall.json .sisyphus/evidence/task-18-recall-raw.json
    Expected Result: residue == 0 (no memory whose content contains "[TEST-T18-MEMORIZE]" remains active). Raw recall may have other (non-T18) results — those are unrelated and should NOT cause failure.
    Failure Indicators: residue > 0 → some T18 memories not forgotten → finalizer failed for those IDs
    Evidence: task-18-residue.txt, task-18-recall-raw.json
  ```

  **Evidence**: `task-18-roundtrip.txt`, `task-18-idem.txt`, `task-18-forget.txt`, `task-18-residue.txt`

  **Commit**: YES
  - Message: `test(integration): memorize roundtrip (extraction → POST → readback)`
  - Files: `tests/integration/test_memorize_roundtrip.py`
  - Pre-commit: `pytest tests/wrapper/ tests/unit/ -v`

- [x] 19. **Integration test — recall quality + fence + project-less**

  **What to do**:
  - Write `tests/integration/test_recall_quality.py` marked `@pytest.mark.integration`
  - **Use unique content prefix**: `[TEST-T19-RECALL]` (distinct from T18's `[TEST-T18-MEMORIZE]` — prevents residue collision)
  - Test setup (per test, not shared): create test session, POST 3 memories with `source_project="test-cortex-primary"` and 3 with `source_project="test-cortex-other"`, all with `[TEST-T19-RECALL]` prefix
  - Test: query with content matching ALL 6 memories, request limit=4 with project="test-cortex-primary"; assert returned 4 results have first 3 from "test-cortex-primary" (fence dominates)
  - Test: same query but project=None (project-less); assert top-4 returned by raw score (no fence)
  - Test: query with non-matching content (`"completely_unrelated_xyz123_T19"`); assert 0 results returned (or all below threshold)
  - Test: short query (`"x"`) → asserts 0 results AND verify no recall HTTP call was made via skip-check (this is more a wrapper test, but here we verify the contract end-to-end via integration)
  - Test: cross-project bleed observed when no fence (project=None) — confirms server doesn't filter by source_project today (verifies the limitation we're working around)
  - **Track created memory IDs explicitly** in module-level `list[str]` populated as memories are POSTed
  - **Cleanup (mandatory, file-scope finalizer)**:
    1. Iterate tracked-IDs list, POST forget action for each id
    2. Verify: query `POST /v1/recall` with `[TEST-T19-RECALL]` content marker, **filter results client-side** for `content` containing `"[TEST-T19-RECALL]"`, count must be `0`
  - DO NOT forget memories from recall results (other tests' top-K memories may appear); only forget IDs we explicitly tracked from our POST responses.

  **Must NOT do**:
  - Don't make assumptions about Cortex result ordering when scores are very close (use clearly distinct queries)
  - Don't pollute: cleanup forget-action all 6 memories at end of file
  - Don't share state across tests (each test creates its own session_id and memories)
  - Don't use `[TEST-CORTEX-PRIMARY]`, `[TEST-T18-MEMORIZE]`, or any prefix shared with another test file
  - Don't skip cleanup on test failure (use `try/finally` or pytest finalizer to guarantee forget-action runs)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T17, T18, T20, T21, T22)
  - **Parallel Group**: Wave 4
  - **Blocks**: F1-F4
  - **Blocked By**: T12 (recall logic), T16 (recall wrapper)

  **References**:
  - **API**: Cortex `/v1/recall` (research bg_56e873e6)
  - **Pattern**: T12 unit tests for fence — same logic, real Cortex
  - **Limitation**: Cortex `session_id`/`topic_ids` filters in /v1/recall are accepted but ignored in SQL today (research finding — explains why client-side fence is needed)

  **Acceptance Criteria**:
  - [ ] `tests/integration/test_recall_quality.py` exists with ≥5 tests
  - [ ] All marked `@pytest.mark.integration`
  - [ ] Cleanup forget-action runs even if a test fails (use try/finally or pytest fixture finalizer)
  - [ ] `pytest tests/integration/test_recall_quality.py -v -m integration` exits 0

  **QA Scenarios**:
  ```
  Scenario: Fence wins against high cross-project score
    Tool: Bash + pytest
    Preconditions: CORTEX_URL/CORTEX_API_KEY set
    Steps:
      1. CORTEX_URL=http://192.168.1.12:8001 CORTEX_API_KEY=$CORTEX_API_KEY pytest tests/integration/test_recall_quality.py::test_fence_dominates -v -m integration 2>&1 | tee .sisyphus/evidence/task-19-fence.txt
    Expected Result: PASSED — first 3 results in returned list all from "test-cortex-primary"; fourth is from "test-cortex-other"
    Evidence: task-19-fence.txt

  Scenario: Project-less recall is unfiltered
    Tool: pytest
    Steps:
      1. pytest tests/integration/test_recall_quality.py::test_projectless_no_fence -v -m integration 2>&1 | tee .sisyphus/evidence/task-19-projectless.txt
    Expected Result: PASSED — top-4 ordered purely by score; both projects represented
    Evidence: task-19-projectless.txt

  Scenario: All T19 test memories cleaned up (prefix-filtered residue check)
    Tool: pytest + curl + jq
    Steps:
      1. After all tests run: pytest tests/integration/test_recall_quality.py -v -m integration --tb=short 2>&1 | tee .sisyphus/evidence/task-19-runall.txt
      2. curl -s -H "Authorization: Bearer $CORTEX_API_KEY" -H 'Content-Type: application/json' -X POST -d '{"query":"[TEST-T19-RECALL]","threshold":0.0,"limit":100}' http://192.168.1.12:8001/v1/recall > /tmp/task-19-recall.json
      3. jq '[.[] | select(.content | contains("[TEST-T19-RECALL]"))] | length' /tmp/task-19-recall.json | tee .sisyphus/evidence/task-19-residue.txt
      4. cp /tmp/task-19-recall.json .sisyphus/evidence/task-19-recall-raw.json
    Expected Result: residue count == 0 (no content with "[TEST-T19-RECALL]" remains active). Recall may return unrelated top-K — those don't count as T19 residue.
    Failure Indicators: residue > 0 → finalizer failed for some IDs
    Evidence: task-19-runall.txt, task-19-residue.txt, task-19-recall-raw.json
  ```

  **Evidence**: `task-19-fence.txt`, `task-19-projectless.txt`, `task-19-runall.txt`, `task-19-residue.txt`

  **Commit**: YES
  - Message: `test(integration): recall quality with fence + cross-project boost`
  - Files: `tests/integration/test_recall_quality.py`
  - Pre-commit: `pytest tests/wrapper/ tests/unit/ -v`

- [x] 19.5. **Integration test — forward-compatibility with Cortex v1.1+ (legacy_rank, threshold, Reflector tolerance)**

  **What to do**:
  - Write `tests/integration/test_forward_compat.py` marked `@pytest.mark.integration`
  - **Use unique content prefix**: `[TEST-T19.5-FWDCOMPAT]` (distinct from T18/T19 prefixes; same cleanup pattern)
  - **Test 1 — `legacy_rank=true` query parameter accepted by Cortex**:
    - With `CORTEX_RECALL_LEGACY_RANK=true` set in test env, call recall via the wrapper (or `recall_lib.recall_and_format` directly)
    - Verify the outgoing HTTP call included `?legacy_rank=true` (use a captured-request httpx mock OR introspect the integration request log)
    - **Result tolerance**: Cortex MVP currently IGNORES the `legacy_rank` parameter (it's only meaningful post-v1.1). Test asserts the request was MADE correctly; Cortex's response is allowed to be either RRF (v1.1+) or default-RRF (MVP)
    - Cortex v1.1+ specific assertion (skip with `pytest.skip()` if MVP): when `legacy_rank=true` AND v1.1+ is detected, response score range is RRF-like (max < 0.10); when `legacy_rank=false`, response score range is composite-like (max may exceed 0.10)
  - **Test 2 — Threshold filtering works in both regimes**:
    - With `CORTEX_RECALL_THRESHOLD=0.5` (high), confirm zero results returned for any query (since RRF max is ~0.05 — all filtered out)
    - With `CORTEX_RECALL_THRESHOLD=0.0` (no filter), confirm at least 1 result returned for a known-relevant query
    - Validates that threshold actually IS applied client-or-server-side (Cortex applies server-side; this confirms the contract)
  - **Test 3 — Reflector mutation tolerance (cooperative test, only meaningful post-v1.1)**:
    - POST a memory `[TEST-T19.5-FWDCOMPAT] User likes coffee` with idempotency-key K1; capture returned ID as M1
    - POST a near-duplicate `[TEST-T19.5-FWDCOMPAT] User prefers coffee` with idempotency-key K2; capture as M2
    - **If v1.1 sleep mode runs during test**: M1 may be merged into M2 (or vice versa), with `superseded_at` set on the loser
    - Recall via our wrapper for query `coffee preference` — assert returned `content` field is one of the two original strings OR a merged version; assert NO duplicate (no two results with our test prefix)
    - **In MVP** (v1.1 not yet deployed): both memories returned independently; assertion auto-passes
    - **In v1.1+**: merge may have happened; assertion still passes (canonical version returned)
    - **This test documents that our plugin is forward-compatible with Reflector mutations** — no code path expects specific memory IDs to persist
  - **Test 4 — Configuration matrix smoke test**:
    - For each of `(threshold=0.02, legacy_rank=False)`, `(threshold=0.30, legacy_rank=True)`, `(threshold=0.30, legacy_rank=False)` — instantiate config, call `recall_and_format` against a known-content query, assert response shape valid (string OR empty string)
    - Validates no crashes across config permutations expected by the version compat matrix
  - **Cleanup (mandatory)**: track all created memory IDs; finalizer iterates and POSTs forget actions; verify content-prefix-filtered residue == 0

  **Must NOT do**:
  - Don't fail Test 1 or Test 3 when running against Cortex MVP — those assertions are conditional on v1.1+ detection (use `pytest.skip()` for v1.1-specific assertions if `?legacy_rank=true` doesn't change response)
  - Don't depend on Reflector running during test (it's nightly at 3 AM UTC; tests should NOT trigger it)
  - Don't pollute: use unique `[TEST-T19.5-FWDCOMPAT]` prefix; clean up via tracked-IDs finalizer
  - Don't assume composite scoring — test must work in both regimes

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Real Cortex calls + version-conditional logic + cooperative tests with server-side mutations
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T15.5, T17, T18, T19, T20, T21, T22)
  - **Parallel Group**: Wave 4
  - **Blocks**: F1, F3
  - **Blocked By**: T12 (recall lib with legacy_rank support), T16 (recall wrapper with config plumbing), T8 (config with new env var)

  **References**:
  - Cortex v1.1 plan line 116: `?legacy_rank=true` query param backward compat
  - Cortex v1.1 plan T16: composite rerank + `superseded_at IS NULL` filter
  - Cortex v1.1 plan T11: importance decay (long-term, doesn't affect short test runs)
  - Cortex v1.1 plan T15: Reflector pass during sleep mode (3 AM UTC)
  - This plan's "Cortex Version Compatibility Matrix" — defines expected behavior per version

  **Acceptance Criteria**:
  - [ ] `tests/integration/test_forward_compat.py` exists with ≥4 tests, all marked `@pytest.mark.integration`
  - [ ] `pytest tests/integration/test_forward_compat.py -v -m integration` exits 0 against current Cortex MVP
  - [ ] Each test handles both MVP and v1.1+ scoring regimes (no hardcoded assumption about score range)
  - [ ] Cleanup verified: `curl ... /v1/recall -d '{"query":"[TEST-T19.5-FWDCOMPAT]","threshold":0.0,"limit":100}' | jq '[.[] | select(.content | contains("[TEST-T19.5-FWDCOMPAT]"))] | length'` returns `0` post-suite

  **QA Scenarios**:
  ```
  Scenario: Forward-compat suite passes against current Cortex
    Tool: Bash + pytest
    Preconditions: CORTEX_URL/CORTEX_API_KEY set; Cortex MVP active (or v1.1+ — test should pass either way)
    Steps:
      1. CORTEX_URL=http://192.168.1.12:8001 CORTEX_API_KEY=$CORTEX_API_KEY pytest tests/integration/test_forward_compat.py -v -m integration 2>&1 | tee .sisyphus/evidence/task-19.5-fwdcompat.txt
    Expected Result: ALL PASSED (≥4 tests); v1.1-specific assertions skipped if MVP detected (pytest output shows "SKIPPED" for those, others PASSED)
    Evidence: task-19.5-fwdcompat.txt

  Scenario: legacy_rank query parameter actually transmitted (not silently dropped)
    Tool: pytest
    Steps:
      1. pytest tests/integration/test_forward_compat.py::test_legacy_rank_param_transmitted -v -m integration 2>&1 | tee .sisyphus/evidence/task-19.5-legacyrank.txt
    Expected Result: PASSED — outgoing request URL captured (via httpx event hooks or test proxy) contains `?legacy_rank=true`
    Evidence: task-19.5-legacyrank.txt

  Scenario: Threshold actually filters (smoke test of contract)
    Tool: pytest
    Steps:
      1. pytest tests/integration/test_forward_compat.py::test_threshold_filtering -v -m integration 2>&1 | tee .sisyphus/evidence/task-19.5-threshold.txt
    Expected Result: PASSED — high threshold returns 0 results, low threshold returns ≥1
    Evidence: task-19.5-threshold.txt

  Scenario: Cleanup leaves zero residue
    Tool: Bash + curl + jq
    Steps:
      1. After full file run: curl -s -H "Authorization: Bearer $CORTEX_API_KEY" -H 'Content-Type: application/json' -X POST 'http://192.168.1.12:8001/v1/recall' -d '{"query":"[TEST-T19.5-FWDCOMPAT]","threshold":0.0,"limit":100}' > /tmp/task-19.5-recall.json
      2. jq '[.[] | select(.content | contains("[TEST-T19.5-FWDCOMPAT]"))] | length' /tmp/task-19.5-recall.json | tee .sisyphus/evidence/task-19.5-residue.txt
    Expected Result: residue == 0
    Evidence: task-19.5-residue.txt
  ```

  **Evidence**: `task-19.5-fwdcompat.txt`, `task-19.5-legacyrank.txt`, `task-19.5-threshold.txt`, `task-19.5-residue.txt`

  **Commit**: YES
  - Message: `test(integration): forward-compatibility with Cortex v1.1+ (legacy_rank, threshold, Reflector)`
  - Files: `tests/integration/test_forward_compat.py`
  - Pre-commit: `pytest tests/wrapper/ tests/unit/ -v`

- [x] 20. **Update `README.md` for Cortex-primary architecture**

  **What to do**:
  - Rewrite the "What it does" section: Cortex is now PRIMARY; FAISS is permanently disabled; the plugin extracts fragments/solutions independently via its own LLM call
  - Update "How each extension works": describe the new flow (single combined memorize, fence rerank, replace not append, two-tier timeout)
  - Update "Configuration" table: **7 env vars** (REMOVE `CORTEX_MERGE_STRATEGY`, `CORTEX_FAISS_ASSERTION_CHECK`; ADD `CORTEX_PROMPT_DIR` and `CORTEX_RECALL_LEGACY_RANK`)
  - Update "Architecture" diagram: no FAISS; show two-tier timeout, fence rerank, vendored prompts
  - **NEW SECTION "Cortex Version Compatibility"**: include the version compatibility matrix from this plan (MVP / v1.1 / v2.0 / v2.1 with recommended threshold + legacy_rank values per version). Document the calibration procedure:
    1. Run `bash scripts/calibrate-recall-threshold.sh` after every Cortex version upgrade
    2. Update `CORTEX_RECALL_THRESHOLD` in deployment env to the recommended value
    3. If quality regresses post-upgrade, set `CORTEX_RECALL_LEGACY_RANK=true` as immediate mitigation
  - **NEW SECTION "Reflector Mutation Awareness (Cortex v1.1+)"**: explain that memories may be auto-merged or superseded by the Cortex Reflector during nightly sleep mode (3 AM UTC). Recall surfaces the canonical (post-merge) version. This is intended behavior, not a bug.
  - **Update "Installation" section**: add the new `pip install -e /opt/agent-zero/data/usr/plugins/agent-zero-cortex` step (run inside the AZ container) — this makes `cortex_plugin` and `dirtyjson` importable in the AZ runtime. Document that without this step, extension wrappers fail with `ModuleNotFoundError: cortex_plugin`. Provide the canonical command form: `docker exec agent-zero pip install -e /opt/agent-zero/data/usr/plugins/agent-zero-cortex`.
  - Update "Verifying it works": new bash one-liners that test the new flow, including a `docker exec agent-zero python -c "import cortex_plugin, dirtyjson; print('ok')"` runtime-import check
  - Update "Troubleshooting": new failure modes (extraction LLM failure, posting timeout, project-less behavior, stale-project rebind log lines, `ModuleNotFoundError: cortex_plugin` → fix with the pip install step, **post-Cortex-v1.1-deploy recall returns junk → run calibration script and update threshold, OR set `CORTEX_RECALL_LEGACY_RANK=true` as emergency rollback**)
  - REMOVE: "FAISS is never touched" framing, FAISS mtime verification step, side-by-side architecture references

  **Must NOT do**:
  - Don't promise area-aware recall (Cortex API doesn't support it)
  - Don't promise server-side project isolation (Cortex /v1/recall filters are ignored today)
  - Don't recommend running migration (`MIGRATION.md` is doc-only now)
  - Don't include implementation-detail content that should live in code comments

  **Recommended Agent Profile**:
  - **Category**: `writing`
    - Reason: Documentation rewrite; clear prose, accurate technical content
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T17, T18, T19, T21, T22)
  - **Parallel Group**: Wave 4
  - **Blocks**: F1 (compliance audit reads README to verify deliverables)
  - **Blocked By**: T1 (none of the technical writing depends on actual code completion — accurate spec from this plan suffices)

  **References**:
  - Existing `README.md:1-293` — current FAISS-centric content; rewrite the affected sections
  - This plan's "Final Architecture" section — single source of truth for behavior
  - Final env-var matrix above

  **Acceptance Criteria**:
  - [ ] `README.md` no longer contains "FAISS" except in historical context (e.g., a `Why this exists` section briefly mentioning FAISS was retired)
  - [ ] All **7** final env vars documented with defaults; no removed env vars referenced
  - [ ] Architecture diagram updated to remove FAISS branches
  - [ ] No mention of `CORTEX_MERGE_STRATEGY` or `CORTEX_FAISS_ASSERTION_CHECK`
  - [ ] Project-less behavior documented (no source_project, no topic lock, no recall filter)
  - [ ] **Cortex Version Compatibility section present** with matrix table (MVP / v1.1 / v2.0 / v2.1)
  - [ ] **Reflector Mutation Awareness section present** explaining merge/supersede behavior

  **QA Scenarios**:
  ```
  Scenario: README accuracy check (FAISS removed, all 7 env vars present)
    Tool: Bash
    Steps:
      1. ! grep -i "side-by-side\|faiss is never touched\|mtime" README.md | tee .sisyphus/evidence/task-20-no-old-framing.txt
      2. ! grep -E "CORTEX_MERGE_STRATEGY|CORTEX_FAISS_ASSERTION_CHECK" README.md | tee .sisyphus/evidence/task-20-no-removed-vars.txt
      3. for v in CORTEX_URL CORTEX_API_KEY CORTEX_ENABLED CORTEX_RECALL_LIMIT CORTEX_RECALL_THRESHOLD CORTEX_RECALL_LEGACY_RANK CORTEX_PROMPT_DIR; do grep -q "$v" README.md || echo "MISSING: $v"; done | tee .sisyphus/evidence/task-20-vars-present.txt
    Expected Result: outputs 1 and 2 are EMPTY; output 3 has no "MISSING:" lines (all 7 vars referenced)
    Evidence: task-20-no-old-framing.txt, task-20-no-removed-vars.txt, task-20-vars-present.txt

  Scenario: Project-less documented
    Tool: Bash
    Steps:
      1. grep -A 3 -i "project.less\|projectless\|no project" README.md | tee .sisyphus/evidence/task-20-projectless-doc.txt
    Expected Result: README contains a section/paragraph explaining project-less session behavior (no tag, no lock, no filter)
    Evidence: task-20-projectless-doc.txt

  Scenario: Cortex Version Compatibility section present and accurate
    Tool: Bash + Grep
    Steps:
      1. grep -E "Cortex Version Compatibility|MVP|v1.1|v2.0|v2.1" README.md | tee .sisyphus/evidence/task-20-compat-section.txt
      2. grep -E "calibrate-recall-threshold" README.md | tee .sisyphus/evidence/task-20-calibration-mention.txt
      3. grep -i "Reflector Mutation Awareness\|Reflector.*merge\|supersede" README.md | tee .sisyphus/evidence/task-20-reflector-doc.txt
    Expected Result: all three files non-empty; matrix references all 4 Cortex versions; calibration script mentioned in installation/troubleshooting; Reflector behavior documented
    Evidence: task-20-compat-section.txt, task-20-calibration-mention.txt, task-20-reflector-doc.txt
  ```

  **Evidence**: `task-20-no-old-framing.txt`, `task-20-no-removed-vars.txt`, `task-20-vars-present.txt`, `task-20-projectless-doc.txt`, `task-20-compat-section.txt`, `task-20-calibration-mention.txt`, `task-20-reflector-doc.txt`

  **Commit**: YES
  - Message: `docs: rewrite README for Cortex-primary architecture`
  - Files: `README.md`
  - Pre-commit: visual review only

- [x] 21. **Rename `SKILL.md` → `MIGRATION.md` + add rollback procedure**

  **What to do**:
  - `git mv SKILL.md MIGRATION.md`
  - Add at the TOP of MIGRATION.md a new section "Rollback Procedure" with exact commands:
    - Stop AZ via `docker compose -f /opt/agent-zero/docker-compose.yml stop`
    - Checkout pre-refactor tag: `git checkout pre-cortex-primary-v1`
    - **Uninstall the new package from AZ runtime** (only relevant if rollback to pre-pip-install state): `docker exec agent-zero pip uninstall -y agent-zero-cortex` (this removes the editable install of `cortex_plugin`)
    - Re-deploy old extension files via the standard deployment commands from the **pre-refactor README** (note: pre-refactor extensions did NOT need `pip install` because they had no `cortex_plugin` dependency; they used inlined HTTP code)
    - Start AZ via `docker compose ... up -d`
    - Verify rollback: `docker exec agent-zero ls /a0/python/extensions/monologue_end/_60_cortex_memorize.py` returns the file path; `docker exec agent-zero python -c "import cortex_plugin"` should now FAIL (expected post-rollback)
  - Add **NEW SECTION "Cortex Version Compatibility & Calibration"** documenting:
    - The 4-row version matrix (MVP / v1.1 / v2.0 / v2.1) with recommended `CORTEX_RECALL_THRESHOLD` and `CORTEX_RECALL_LEGACY_RANK` values per version
    - Calibration procedure: when to run `bash scripts/calibrate-recall-threshold.sh`, how to interpret the output JSON, how to update env without code changes (no AZ restart needed — env is read on every call)
    - Emergency rollback: setting `CORTEX_RECALL_LEGACY_RANK=true` forces Cortex v1.1+ to return pre-v1.1 RRF ordering for one-release backward compat (per Cortex v1.1 plan line 116)
    - **Reflector Mutation Notice**: in Cortex v1.1+, memories may be auto-merged or superseded by the Reflector during nightly sleep mode. This is intended Cortex behavior. Our plugin holds no memory IDs across calls, so we tolerate mutations transparently. Recall always surfaces the canonical (post-merge) version.
    - Specific deployment-time checklist: post-Cortex-upgrade smoke test (run `pytest tests/integration/test_forward_compat.py -v -m integration` to confirm plugin still works)
  - Add a section "Why this file exists" explaining that the FAISS migration was a one-time event in May 2026; the script remains documented for historical/forensic purposes
  - DO NOT make the FAISS migration script executable; mark explicitly as "doc-only — DO NOT RE-RUN"

  **Must NOT do**:
  - Don't preserve the old filename — `git mv` is necessary so git history follows
  - Don't add migration logic in code (this stays out of scope per Metis G5)

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T17-T20, T22)
  - **Parallel Group**: Wave 4
  - **Blocks**: F1
  - **Blocked By**: T1 (commit tag exists)

  **References**:
  - Existing `SKILL.md:1-87` — historical migration content; preserve as-is in body, just add header sections

  **Acceptance Criteria**:
  - [ ] `test ! -f SKILL.md && test -f MIGRATION.md` exits 0
  - [ ] `git log --follow MIGRATION.md` shows commits from former `SKILL.md` history
  - [ ] MIGRATION.md contains "Rollback Procedure" header
  - [ ] MIGRATION.md contains "DO NOT RE-RUN" warning
  - [ ] References `pre-cortex-primary-v1` git tag
  - [ ] **MIGRATION.md contains "Cortex Version Compatibility & Calibration" section** with the 4-row version matrix (verifiable via `grep -c "MVP\|v1.1\|v2.0\|v2.1" MIGRATION.md` returns ≥4)
  - [ ] **MIGRATION.md mentions `calibrate-recall-threshold.sh`** (verifiable via `grep "calibrate-recall-threshold" MIGRATION.md`)
  - [ ] **MIGRATION.md documents Reflector mutation tolerance** (verifiable via `grep -i "Reflector" MIGRATION.md`)

  **QA Scenarios**:
  ```
  Scenario: Rename + rollback section
    Tool: Bash
    Steps:
      1. git mv SKILL.md MIGRATION.md
      2. Edit MIGRATION.md to add Rollback section + warnings
      3. test ! -f SKILL.md && test -f MIGRATION.md && echo "ok" | tee .sisyphus/evidence/task-21-rename.txt
      4. grep -E "Rollback Procedure|DO NOT RE-RUN|pre-cortex-primary-v1" MIGRATION.md | tee .sisyphus/evidence/task-21-content.txt
      5. git log --follow --oneline MIGRATION.md | tee .sisyphus/evidence/task-21-history.txt
    Expected Result: rename.txt outputs "ok"; content.txt has 3 grep matches; history.txt shows ≥2 commits (the original SKILL.md commit plus this rename)
    Evidence: task-21-rename.txt, task-21-content.txt, task-21-history.txt
  ```

  **Evidence**: `task-21-rename.txt`, `task-21-content.txt`, `task-21-history.txt`

  **Commit**: YES
  - Message: `docs: rename SKILL.md to MIGRATION.md and add rollback procedure`
  - Files: rename of `SKILL.md`, edits to `MIGRATION.md`
  - Pre-commit: `test -f MIGRATION.md && test ! -f SKILL.md`

- [x] 22. **Update `plugin.yaml`, `AGENTS.md`, `.serena/memories/architecture.md`**

  **What to do**:
  - **`plugin.yaml`**: bump `version` to `1.0.0`; update `description` from "Side-by-side Cortex memory backend" to "Primary memory backend for Agent Zero (Cortex API)"
  - **`AGENTS.md`**: update the "Repo layout" section to reflect new directories (`src/cortex_plugin/`, `prompts/`, `scripts/calibrate-recall-threshold.sh`, three-layer tests/); update "Running tests" section to document the three layers and the `-m integration` marker; update "Known pre-existing failure" section — REMOVE it (no longer pre-existing failure; replaced by working three-layer suite); update "Configuration" env-var table to the **7 final vars** including `CORTEX_RECALL_LEGACY_RANK`; add brief "Cortex Version Compatibility" subsection pointing to MIGRATION.md for full matrix
  - **`.serena/memories/architecture.md`**: rewrite to describe the new flow (single combined memorize, fence rerank, replace not append, two-tier timeout, vendored prompts, no FAISS); REMOVE "both always written" lines
  - **`.serena/memories/code_style_and_conventions.md`**: update the test section — note the three-layer pyramid and the `helpers.extension` stub vendoring location
  - **`.serena/memories/task_completion_checklist.md`**: update the test command to `pytest tests/unit/ tests/wrapper/ -v` (drop the "8 expected failures" note); add deployment guidance for `pre-cortex-primary-v1` rollback tag
  - **`.serena/memories/suggested_commands.md`**: update test commands; add the `pytest -m integration` invocation

  **Must NOT do**:
  - Don't change the plugin name (still `agent-zero-cortex`)
  - Don't change `settings_sections` or `per_project_config` / `per_agent_config` in plugin.yaml
  - Don't rewrite ALL of AGENTS.md — preserve hard-earned content (deployment notes, idempotency notes, Python conventions); only update sections affected by this refactor

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T17-T21)
  - **Parallel Group**: Wave 4
  - **Blocks**: F1
  - **Blocked By**: T1

  **References**:
  - Existing `AGENTS.md`, `plugin.yaml`, `.serena/memories/*.md` — keep what's still accurate, update what's stale
  - This plan's "Final Architecture" — source of truth

  **Acceptance Criteria**:
  - [ ] `plugin.yaml` version is `1.0.0`; description updated
  - [ ] `AGENTS.md` no longer mentions "8 of 9 tests fail"
  - [ ] `AGENTS.md` documents three-layer test pyramid and integration marker
  - [ ] `AGENTS.md` env-var table matches the 6 final vars
  - [ ] `.serena/memories/architecture.md` no longer mentions FAISS as a current backend
  - [ ] `.serena/memories/task_completion_checklist.md` updated test commands

  **QA Scenarios**:
  ```
  Scenario: All docs aligned
    Tool: Bash
    Steps:
      1. grep -E "^version:" plugin.yaml | tee .sisyphus/evidence/task-22-pluginyaml.txt
      2. ! grep -i "8 of 9 tests fail" AGENTS.md | tee .sisyphus/evidence/task-22-agentsmd-clean.txt
      3. grep -E "tests/(unit|wrapper|integration)" AGENTS.md | tee .sisyphus/evidence/task-22-pyramid.txt
      4. for v in CORTEX_URL CORTEX_API_KEY CORTEX_ENABLED CORTEX_RECALL_LIMIT CORTEX_RECALL_THRESHOLD CORTEX_RECALL_LEGACY_RANK CORTEX_PROMPT_DIR; do grep -q "\| .$v" AGENTS.md || echo "MISSING: $v"; done | tee .sisyphus/evidence/task-22-vars.txt
      5. ! grep -i "both always written\|side-by-side" .serena/memories/architecture.md | tee .sisyphus/evidence/task-22-serena-clean.txt
      6. grep -i "Cortex Version Compatibility\|MIGRATION\.md" AGENTS.md | tee .sisyphus/evidence/task-22-compat-pointer.txt
    Expected Result: pluginyaml.txt shows "version: 1.0.0"; agentsmd-clean.txt is EMPTY; pyramid.txt has matches for all 3 layers; vars.txt has no MISSING lines (all 7 vars referenced); serena-clean.txt is EMPTY; compat-pointer.txt has at least one reference (subsection or link to MIGRATION.md)
    Evidence: task-22-pluginyaml.txt, task-22-agentsmd-clean.txt, task-22-pyramid.txt, task-22-vars.txt, task-22-serena-clean.txt, task-22-compat-pointer.txt
  ```

  **Evidence**: `task-22-pluginyaml.txt`, `task-22-agentsmd-clean.txt`, `task-22-pyramid.txt`, `task-22-vars.txt`, `task-22-serena-clean.txt`

  **Commit**: YES
  - Message: `docs: update plugin.yaml, AGENTS.md, .serena memories for new arch`
  - Files: `plugin.yaml`, `AGENTS.md`, `.serena/memories/architecture.md`, `.serena/memories/code_style_and_conventions.md`, `.serena/memories/task_completion_checklist.md`, `.serena/memories/suggested_commands.md`
  - Pre-commit: visual review

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
>
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback → fix → re-run → present again → wait for okay.

- [x] F1. **Plan Compliance Audit** — `oracle`
  Read this plan end-to-end. For each "Must Have": verify implementation exists (Read each file path; run each Definition-of-Done command). For each "Must NOT Have": grep codebase for forbidden patterns — reject with file:line if found. Specifically check: no `client.py`, no `default_config.yaml`, no `_50_cortex_*.py`, no metadata field in any POST body, no `tenacity`/`backoff` imports, no Pydantic for internal data, **all 7 env vars present** (`CORTEX_URL`, `CORTEX_API_KEY`, `CORTEX_ENABLED`, `CORTEX_RECALL_LIMIT`, `CORTEX_RECALL_THRESHOLD`, `CORTEX_RECALL_LEGACY_RANK`, `CORTEX_PROMPT_DIR` — no extras), `_60_` prefix on all three extensions, vendored prompts exist with commit-SHA reference, **`scripts/calibrate-recall-threshold.sh` exists and runs end-to-end (T15.5)**, **`tests/integration/test_forward_compat.py` exists with ≥4 tests (T19.5)**, **MIGRATION.md contains Cortex Version Compatibility section** with 4-row version matrix. Compare deliverables against plan word-by-word.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [24/24] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
  Run `python -m pytest tests/unit/ tests/wrapper/ -v` and confirm exit 0. Run `python -m pytest tests/integration/ -v -m integration` against live Cortex (use `CORTEX_URL=http://192.168.1.12:8001` and `CORTEX_API_KEY` from env) and confirm exit 0. Review all changed files in `src/cortex_plugin/`, `extensions/python/`, `tests/` for: `as Any`/`# type: ignore`, empty `except: pass`, `print()` calls, commented-out code, unused imports, dead branches. Check AI slop: excessive comments explaining what code obviously does, premature abstractions (any class with only `__init__` + one method), generic names (data/result/item/temp/handle/process), redundant docstrings repeating the function signature. Check pure-function library: ZERO `helpers.*` or `agent.*` imports.
  Output: `Build [PASS/FAIL] | Unit [N/N] | Wrapper [N/N] | Integration [N/N] | Files [N clean/N issues] | VERDICT`

- [x] F3. **Real Manual QA + Live Deployment** — `unspecified-high` (with `dev-browser` skill)

  **Phase 1 — Evidence audit (idempotent, non-destructive)**: Do NOT re-run task QA scenarios (most are non-idempotent: `git tag`, `git rm`, `git mv`, prompt copy operations succeed only once). Instead, for each of T1–T22, READ the captured evidence files from `.sisyphus/evidence/task-{N}-*` and verify each task's expected outputs match the file contents. Re-run ONLY safe/read-only commands per task: pytest invocations (idempotent), `! grep -E ...` purity checks (idempotent), `test -f` / `test ! -f` existence checks (idempotent). Compile a per-task pass/fail table to `.sisyphus/evidence/final-qa/audit.md`. If any task's evidence is missing or contradicts the task spec, mark it FAIL and surface to user.

  **Phase 2 — Live AZ deployment**:
  1. Tag deployment: `git tag deploy-{ISO8601-timestamp} HEAD` (rollback anchor; separate from `pre-cortex-primary-v1`)
  2. Build distributable: `tar czf /tmp/agent-zero-cortex.tar.gz -C /Users/paolo/Documents/Projects --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' agent-zero-cortex/`
  3. Push to LXC: `scp /tmp/agent-zero-cortex.tar.gz root@192.168.1.5:/tmp/ && ssh root@192.168.1.5 "pct push 500 /tmp/agent-zero-cortex.tar.gz /tmp/agent-zero-cortex.tar.gz"`
  4. Inside LXC 500: stop AZ → extract → install package → atomic-swap extensions → start AZ:
     ```bash
     ssh root@192.168.1.5 "pct exec 500 -- bash -c '
       set -e
       docker compose -f /opt/agent-zero/docker-compose.yml stop
       cd /tmp && tar xzf agent-zero-cortex.tar.gz
       cp -r agent-zero-cortex/* /opt/agent-zero/data/usr/plugins/agent-zero-cortex/
       # Editable install of cortex_plugin INTO AZ runtime venv (use AZ container's python)
       docker run --rm -v /opt/agent-zero:/opt/agent-zero agent-zero-image bash -c \"pip install -e /opt/agent-zero/data/usr/plugins/agent-zero-cortex && python -c 'import cortex_plugin, dirtyjson; print(cortex_plugin.__file__, dirtyjson.__name__)'\"
       # Atomic-swap extensions
       PLUGIN=/opt/agent-zero/data/usr/plugins/agent-zero-cortex/extensions/python
       EXT=/opt/agent-zero/data/python/extensions
       cp \$PLUGIN/monologue_start/_60_cortex_init.py       \$EXT/monologue_start/
       cp \$PLUGIN/monologue_end/_60_cortex_memorize.py     \$EXT/monologue_end/
       cp \$PLUGIN/message_loop_prompts_after/_60_cortex_recall.py \$EXT/message_loop_prompts_after/
       docker compose -f /opt/agent-zero/docker-compose.yml up -d --force-recreate
     '" 2>&1 | tee .sisyphus/evidence/final-qa/live/deploy.txt
     ```
  5. **Runtime import verification (gate before Phase 3)**: `ssh root@192.168.1.5 "pct exec 500 -- docker exec agent-zero python -c 'import cortex_plugin, dirtyjson; print(cortex_plugin.__file__, dirtyjson.__name__)'" 2>&1 | tee .sisyphus/evidence/final-qa/live/imports.txt` — must succeed before proceeding to Phase 3. If `ModuleNotFoundError: cortex_plugin` or `dirtyjson`, the deployment failed; investigate (likely AZ's container doesn't share the data volume's site-packages — may need `pip install` invocation inside the running container itself: `docker exec agent-zero pip install -e /opt/agent-zero/data/usr/plugins/agent-zero-cortex`).

  **Phase 3 — Live verification (agent-executable)**: use `dev-browser` (Playwright) to navigate to AZ web UI; switch to project `_test_cortex_primary`; send unique-marker message `Remember that the F3 verification marker is XYZQ-F3-VERIFY-2026-{date}` (substitute current date so marker is unique per F3 run); wait for AZ response; capture screenshot to `.sisyphus/evidence/final-qa/live/ui-after.png`. Then observe logs: `ssh root@192.168.1.5 "pct exec 500 -- docker logs agent-zero --tail 100" 2>&1 | grep -E 'cortex\.(init|memorize)' | tee .sisyphus/evidence/final-qa/live/cortex-logs.txt`. Confirm: `cortex.init: session=<uuid>` log appears, then `cortex.memorize: written=<N> ...` log appears with N≥1 within 20s of monologue end. Then verify via Cortex recall (filtered):
  ```bash
  curl -s -H "Authorization: Bearer $CORTEX_API_KEY" -H 'Content-Type: application/json' \
    -X POST 'http://192.168.1.12:8001/v1/recall' \
    -d '{"query":"XYZQ-F3-VERIFY-2026","limit":5,"threshold":0.0}' \
    | jq '[.[] | select(.content | contains("XYZQ-F3-VERIFY-2026"))] | length' \
    | tee .sisyphus/evidence/final-qa/live/recall-marker.txt
  ```
  Returns ≥1 (with content-prefix filter) AND inspect result content via `... | jq '[.[] | select(.content | contains("XYZQ-F3-VERIFY-2026"))][0].content'` to confirm full marker present.

  **Cleanup (mandatory after Phase 3)**: forget the F3 marker memories. Recall + filter + forget pattern same as T18/T19.

  Output: `Phase 1 audit [N/N pass] | Phase 2 deploy [PASS/FAIL] | Phase 2 imports [PASS/FAIL] | Phase 3 live memorize [PASS/FAIL via marker recall] | Cleanup [N forgotten] | VERDICT`

  **Notes**:
  - Cortex API has NO `GET /v1/memories?source_session_id=...` endpoint — `POST /v1/recall` with unique marker + content filter is the canonical readback path.
  - Phase 2 step 4's `pip install` invocation is the critical hot-spot: AZ container must have access to the editable install. If the container's site-packages is volume-mounted differently than expected, the executor must investigate the actual install location (read AZ's Dockerfile + docker-compose.yml on LXC 500) and adjust the install command. Document the actual approach taken in `.sisyphus/evidence/final-qa/live/deploy.txt`.
  - On failure of Phase 2 imports: Phase 3 MUST NOT proceed. Surface the issue, possibly halt and require user input.

- [x] F4. **Scope Fidelity Check** — `deep`
  For each task (T1–T22 + T15.5 + T19.5 = 24 tasks): read "What to do", read actual diff (`git diff pre-cortex-primary-v1..HEAD -- <file>`). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Specifically check the "Must NOT Have" guardrails: grep for tenacity, backoff, structured logging libraries, Pydantic models in `src/`, new env var names beyond the 7 documented, parallel POST loops in `extraction.py`/wrapper code, area filtering in recall, metadata field in POST bodies. Detect cross-task contamination: Task N touching Task M's files (e.g., did T11 modify `slugs.py` which belongs to T6?). Flag unaccounted changes in any file not listed in any task's "Files" section. Verify T15.5 and T19.5 are NOT skipped (forward-compat tasks).
  Output: `Tasks [24/24 compliant] | Guardrails enforced [Y/N] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | Forward-compat tasks [PRESENT/MISSING] | VERDICT`

---

## Commit Strategy

Atomic commits, one per task (or per logical sub-step within a task). Commit messages follow conventional-commits style:

- T1: `chore: tag pre-refactor commit and scaffold cortex-primary directories`
- T2: `chore: verification spike — confirm _memory plugin can be silenced`
- T3: `chore: spike — measure Cortex POST latency baseline`
- T4: `feat: vendor AZ memory extraction prompts (commit 2613fac0)`
- T5: `chore: remove dead code (client.py, default_config.yaml, old tests)`
- T6: `feat(lib): slugs module with sanitize_slug and project_resolve`
- T7: `feat(lib): keys module with deterministic idempotency_key`
- T8: `feat(lib): config module reading 6 env vars + hardcoded constants`
- T9: `feat(lib): prompts module loads vendored .md files with override hook`
- T10: `feat(lib): http module with thin async post/get wrappers`
- T11: `feat(lib): extraction module — parallel LLM calls + DirtyJson parse + retry`
- T12: `feat(lib): recall module — fence rerank + ## Memories block formatting`
- T13: `test: vendor helpers.extension.Extension stub for wrapper tests`
- T14: `feat: rewrite _60_cortex_init.py as thin wrapper over pure lib`
- T15: `feat: rewrite _60_cortex_memorize.py as thin wrapper over pure lib`
- T15.5: `feat(scripts): recall threshold calibration utility for Cortex version compat`
- T16: `feat: rewrite _60_cortex_recall.py as thin wrapper over pure lib`
- T17: `test(integration): session lifecycle (init, topic-lock, project-less)`
- T18: `test(integration): memorize roundtrip (extraction → POST → readback)`
- T19: `test(integration): recall quality with fence + cross-project boost`
- T19.5: `test(integration): forward-compatibility with Cortex v1.1+ (legacy_rank, threshold, Reflector)`
- T20: `docs: rewrite README for Cortex-primary architecture (incl. version compat matrix)`
- T21: `docs: rename SKILL.md to MIGRATION.md and add rollback + Cortex version compat`
- T22: `docs: update plugin.yaml, AGENTS.md, .serena memories for new arch`

Pre-commit verification (per-task): `pytest tests/unit/ tests/wrapper/ -v` must exit 0 before commit. Integration tests gated separately via `-m integration` marker.

---

## Success Criteria

### Verification Commands

```bash
# 1. All non-integration tests pass
cd /Users/paolo/Documents/Projects/agent-zero-cortex
python -m pytest tests/unit/ tests/wrapper/ -v
# Expected: all PASSED, exit 0

# 2. Integration tests pass against live Cortex
CORTEX_URL=http://192.168.1.12:8001 CORTEX_API_KEY=$CORTEX_API_KEY \
  python -m pytest tests/integration/ -v -m integration
# Expected: all PASSED, exit 0 (or "no tests selected" if no integration tests collected — should be ≥3)

# 3. No dead code
test ! -f client.py
test ! -f default_config.yaml
# Expected: both exit 0

# 4. Old _60_ extensions present (kept), no _50_cortex_* (never created)
ls extensions/python/monologue_start/_60_cortex_init.py
ls extensions/python/monologue_end/_60_cortex_memorize.py
ls extensions/python/message_loop_prompts_after/_60_cortex_recall.py
! ls extensions/python/monologue_start/_50_cortex_init.py 2>/dev/null
# Expected: first three succeed, last exits non-zero

# 5. Pure-function lib has no AZ-runtime imports
! grep -rE "(from helpers|import helpers|from agent\b|import agent\b)" src/cortex_plugin/
# Expected: exit non-zero (no matches), or empty stdout

# 6. Vendored prompts exist with version stamp
test -f prompts/memory.memories_sum.sys.md
test -f prompts/memory.solutions_sum.sys.md
grep -q "frdel/agent-zero@2613fac0" prompts/memory.memories_sum.sys.md
# Expected: all exit 0

# 7. All 7 env vars supported
python -c "from cortex_plugin.config import load_config; c = load_config(); assert hasattr(c, 'recall_legacy_rank') and hasattr(c, 'recall_threshold')"
# Expected: exit 0

# 8. Calibration script runs and outputs valid JSON
bash scripts/calibrate-recall-threshold.sh
ls .sisyphus/evidence/calibration/threshold-recommendation-*.json
jq '.recommended.threshold' .sisyphus/evidence/calibration/threshold-recommendation-*.json
# Expected: bash exit 0; ls finds file; jq returns numeric value

# 9. Forward-compat tests pass (in addition to standard integration tests)
CORTEX_URL=http://192.168.1.12:8001 CORTEX_API_KEY=$CORTEX_API_KEY \
  pytest tests/integration/test_forward_compat.py -v -m integration
# Expected: all PASSED, exit 0

# 10. Cortex Version Compatibility documented
grep -c "MVP\|v1.1\|v2.0\|v2.1" MIGRATION.md
# Expected: ≥4 (each version mentioned at least once in compatibility section)

# 11. Live deployment writes a real memory
# (Run after F3 completes successfully)
ssh root@192.168.1.5 "pct exec 500 -- docker logs agent-zero --tail 200" | grep -E "cortex\.(init|memorize): "
# Expected: at least one cortex.init line and one cortex.memorize line with written>=1
```

### Final Checklist
- [ ] All "Must Have" deliverables present
- [ ] All "Must NOT Have" guardrails enforced (verified by F4)
- [ ] All **24** implementation tasks completed with QA scenarios passing (T1–T22 + T15.5 + T19.5)
- [ ] All 4 final verification reviews APPROVE
- [ ] User has given explicit "okay" after reviewing F1-F4 results
- [ ] Live deployment verified: a real AZ session writes ≥1 memory to Cortex
- [ ] **Forward-compatibility verified**: calibration script runs end-to-end; T19.5 forward-compat tests pass; MIGRATION.md contains version compatibility matrix; `CORTEX_RECALL_LEGACY_RANK` works as escape hatch
- [ ] Draft `.sisyphus/drafts/cortex-primary-refactor.md` deleted (cleanup)
