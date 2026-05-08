# Decisions — cortex-primary-refactor

## Architectural Decisions

### Memory Write Strategy
- Two independent memories per solution: problem (area=fragments, kind=solution-problem) + solution (area=solutions, kind=solution-step)
- NO metadata field in POST body (Cortex API doesn't support it)
- NO cross-link mechanism (impossible without metadata)

### Recall Strategy
- Fence-based (NOT multiplier-based boost): same-project pool first, fill from cross-project
- Replace extras["memories"] (NOT append) — clean slate each recall
- On HTTP failure: leave extras["memories"] UNCHANGED (no clobber)
- On empty result: set extras["memories"] = "" (clear stale content)

### Project Handling
- project_resolve("default") → (None, "default") — sentinel
- project_resolve(None) → (None, None)
- Project-less: no source_project field in body, no topic lock, no recall filter
- Stale-project mid-session: log info, use new slug for current call

### Test Strategy
- TDD strict: RED → GREEN → REFACTOR per task
- No pytest fixtures, factory libraries, or testcontainers (unittest.mock only)
- No conftest.py for unit tests (pure functions don't need stub)
- Wrapper tests use vendored helpers.extension.Extension stub in tests/wrapper/conftest.py

### Forward Compatibility
- CORTEX_RECALL_LEGACY_RANK=true appends ?legacy_rank=true to /v1/recall requests
- Threshold calibration via scripts/calibrate-recall-threshold.sh after each Cortex upgrade
- Reflector mutations (merge/supersede) tolerated by design — no memory ID caching
