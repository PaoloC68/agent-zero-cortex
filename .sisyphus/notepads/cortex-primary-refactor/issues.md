# Issues — cortex-primary-refactor

## Known Issues / Gotchas

### dirtyjson API
- The actual dirtyjson package API is `loads(s)` / `load(fp)` — modeled after stdlib json
- NOT `parse_string` (that's a different library)
- Use: `import dirtyjson; dirtyjson.loads(raw_text)`

### AZ Extension Loading
- Files load alphabetically by filename, first-occurrence-wins per filename across plugins
- `_60_` prefix ensures our extensions run AFTER built-in `_memory` plugin's `_50_*` files
- Built-in `_memory` is `always_enabled: true` — toggle file may not actually disable it

### Cortex API Limitations
- /v1/recall session_id/topic_ids filters ACCEPTED but IGNORED in current SQL
- No GET /v1/memories endpoint — use POST /v1/recall with unique marker for readback
- No metadata field in memory items
- RRF max scores ~0.05 (constant 60 hardcoded in Cortex backend)

### Test Isolation
- Integration test prefixes MUST be unique per file:
  - T18: [TEST-T18-MEMORIZE]
  - T19: [TEST-T19-RECALL]
  - T19.5: [TEST-T19.5-FWDCOMPAT]
  - T15.5 calibration: [CALIB-{run-uuid}]
  - F3 verification: XYZQ-F3-VERIFY-2026-{date}

### Editable Install Required
- `pip install -e ".[dev]"` must be run for `from cortex_plugin.X import ...` to work
- Without this, ALL unit/wrapper tests fail with ModuleNotFoundError: cortex_plugin
- Verify: `python -c "import cortex_plugin; print(cortex_plugin.__file__)"`

### pyproject.toml Build Config
- Must add `[tool.hatch.build.targets.wheel] packages = ["src/cortex_plugin"]`
- Must add markers and addopts to [tool.pytest.ini_options]


## F1 Plan Compliance Audit — 2026-05-08
- Required forward-compat collect command failed: `python -m pytest tests/integration/test_forward_compat.py --collect-only -q 2>&1 | grep "test session"` produced no output because default pytest addopts deselect integration tests; corrected `-m integration` collect found 5 tests.
- Required removed-env-var grep failed because stale bytecode files contain forbidden strings: `extensions/python/message_loop_prompts_after/__pycache__/_60_cortex_recall.cpython-313.pyc` contains `CORTEX_MERGE_STRATEGY`; `extensions/python/monologue_end/__pycache__/_60_cortex_memorize.cpython-313.pyc` contains `CORTEX_FAISS_ASSERTION_CHECK`.
- Unit + wrapper test suite passed: 150 passed in 0.43s.

- Must-NOT guardrail violation: pytest fixture usage found despite `NO pytest fixtures` guardrail: `tests/unit/test_prompts.py` uses `tmp_path`; integration tests define `@pytest.fixture` cleanup finalizers in `test_recall_quality.py`, `test_forward_compat.py`, and `test_memorize_roundtrip.py`.

## F3 QA Issues (2026-05-08)

### 1. AppArmor blocks Docker container restart in LXC 500
- Docker 29.3.1 in unprivileged LXC cannot read `/sys/kernel/security/apparmor/profiles`
- Fix: bind-mount fake file over `/sys/module/apparmor/parameters/enabled` to make Docker `IsEnabled()` return false
- Persisted via: `/etc/systemd/system/mask-apparmor-for-docker.service` (enabled, runs before docker.service)

### 2. docker exec returns EXIT:126 in LXC (AppArmor namespace restriction)
- `docker exec` requires process namespace access; AppArmor restricts in unprivileged LXC
- Fix: write `cortex_plugin.pth` directly into overlay2 diff layer site-packages

### 3. cortex.init / cortex.memorize log lines suppressed in docker logs
- AZ `models.py` calls `turn_off_logging()` → sets ALL loggers to ERROR level
- INFO-level cortex log lines never appear; verification must use Cortex recall API

### 4. Cortex API v1 is append-only — no DELETE/forget endpoint
- Test marker `XYZQ-F3-VERIFY-2026-20260508` remains in Cortex (0 forgotten)

### 5. Stale extraction artefacts in /tmp/agent-zero-cortex/ on LXC
- `tar xzf` leaves old files; `rm -f` stale files needed after each deployment
