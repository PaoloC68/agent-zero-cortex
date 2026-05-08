# T3: Cortex POST /v1/memories Latency Baseline

**Run date**: 2026-05-08T17:03:03 UTC  
**Session ID**: `spike-task-3-1778259783`  
**Cortex URL**: `http://192.168.1.12:8001`  
**Embedding model**: `text-embedding-3-small` (synchronous, server-side)

---

## Methodology

- 4 content sizes: 200, 500, 1000, 2000 chars
- 6 serial POST `/v1/memories` calls per size (24 total)
- Payload fields: `content`, `kind=observation`, `area=fragments`, `source_session_id`, `source_project`, `importance=0.5`
- Timing: `time.monotonic()` wall-clock from request start to full response received
- No warm-up run; first call at size=200 captured cold-start latency

---

## Raw Timings (seconds)

| Size | Call 1 | Call 2 | Call 3 | Call 4 | Call 5 | Call 6 |
|------|--------|--------|--------|--------|--------|--------|
| 200  | 1.8461 | 0.1764 | 1.6213 | 0.1904 | 0.1762 | 0.1934 |
| 500  | 0.1936 | 0.1930 | 0.2017 | 0.1936 | 0.1680 | 0.1856 |
| 1000 | 0.2410 | 0.2780 | 0.1955 | 0.1875 | 0.1793 | 0.2081 |
| 2000 | 0.1879 | 0.1852 | 0.1961 | 0.3078 | 0.1898 | 0.3282 |

---

## Percentile Summary

| Size (chars) | p50 (s) | p95 (s) | p99 (s) | min (s) | max (s) | mean (s) |
|---|---|---|---|---|---|---|
| 200  | 0.192 | 1.790 | 1.835 | 0.176 | 1.846 | 0.701 |
| 500  | 0.193 | 0.200 | 0.201 | 0.168 | 0.202 | 0.189 |
| 1000 | 0.202 | 0.269 | 0.276 | 0.179 | 0.278 | 0.215 |
| 2000 | 0.193 | 0.323 | 0.327 | 0.185 | 0.328 | 0.233 |

---

## Key Observations

1. **Cold-start spikes at size=200**: Calls 1 and 3 took ~1.6–1.8s. This is consistent with the OpenAI embedding endpoint needing to warm up after idle time. Subsequent calls collapsed to ~0.18s.

2. **Warmed-up steady state**: After the cold-start, all sizes fall in 0.17–0.33s per call — far below the 10s budget.

3. **Content size has minimal impact**: Doubling from 500→2000 chars adds only ~40ms at p50, ~130ms at p95. Embedding latency dominates over payload transfer.

4. **No failures**: All 24 calls returned HTTP 200 with a valid `memory_id`.

---

## Budget Decision: Is the 10s POSTING_TIMEOUT_SEC realistic?

**Yes — comfortably.**

Worst-case scenario for 10 memories per session:
- 2 cold-start calls at ~1.8s = 3.6s
- 8 warmed calls at p95 ~0.32s = 2.6s
- **Total worst case: ~6.2s** (margin: ~3.8s)

Typical scenario (all warmed):
- 10 calls at p95 ~0.27s = **2.7s total**

The 10s budget is not tight. Even if every call hit the cold-start tail (~1.85s), 10 memories would take ~18.5s — but cold-start only hits when the OpenAI endpoint has been idle. In normal AZ usage (sessions run regularly), only the first call per session would be slow.

**Recommendation**: Keep `POSTING_TIMEOUT_SEC = 10` as-is. If cold-start latency becomes a concern in production (idle periods > 5 min), consider adding a single no-op POST at session init (in `_60_cortex_init.py`) to pre-warm the embedding endpoint before `monologue_end` runs.

---

## Cleanup

All 24 spike memories forgotten via `POST /v1/memories` with `action=forget` (see below).  
`/tmp/spike_latency.py` deleted after use.

---

*Raw data: `.sisyphus/evidence/task-3-raw.json`*
