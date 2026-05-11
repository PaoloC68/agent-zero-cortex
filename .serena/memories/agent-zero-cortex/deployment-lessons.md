# Deployment Lessons — agent-zero-cortex

## AZ Container Layout (LXC 500)

- Proxmox host: `root@192.168.1.5`, LXC ID: 500
- Volume mount: `/opt/agent-zero/data` → `/a0` inside container
- AZ framework Python: `/opt/venv-a0/bin/python` (NOT `python` or `python3`)
- AZ framework pip: `/opt/venv-a0/bin/pip`
- Plugin install: `docker exec agent-zero /opt/venv-a0/bin/pip install -e /a0/usr/plugins/agent-zero-cortex`

## Extension File Paths

**CORRECT** (what AZ actually loads):
```
/opt/agent-zero/data/extensions/python/monologue_start/_60_cortex_init.py
/opt/agent-zero/data/extensions/python/monologue_end/_60_cortex_memorize.py
/opt/agent-zero/data/extensions/python/message_loop_prompts_after/_60_cortex_recall.py
```

**WRONG** (old incorrect path we used initially):
```
/opt/agent-zero/data/python/extensions/...
```

Inside the container these map to `/a0/extensions/python/...`.

## Logging

- AZ root logger level is **WARNING** — `logger.info()` calls are silently dropped
- All cortex status lines must use `logger.warning()` to appear in docker logs
- Check logs with: `docker logs agent-zero --since 5m 2>&1 | grep -E "cortex\.(init|memorize|recall)"`
- Expected lines after a session:
  - `cortex.init: session=<uuid> project=<slug>`
  - `cortex.memorize: written=N failed=0 timed_out=False ms=NNN`
  - `cortex.recall: results=N after_fence=N project=<slug> ms=NNN`

## call_utility_model is Not Cancellable

- `asyncio.wait_for()` wrapping `call_utility_model` does NOT work — the underlying HTTP call is blocking and ignores asyncio cancellation
- The coroutine gets cancelled but the thread keeps running; result is discarded
- Fix: remove `asyncio.wait_for` entirely and let `call_utility_model` complete naturally
- `monologue_end` fires AFTER AZ responds to the user — slow extraction has zero UX impact

## Utility Model Latency

- Utility model: `claude-haiku-4-5` via `anthropic_oauth`
- Typical latency: 15–30s per LLM call (OAuth proxy adds overhead)
- `EXTRACTION_TIMEOUT_SEC = 30`, `POSTING_TIMEOUT_SEC = 60` are appropriate values

## Deployment Verification

Always run `scripts/verify_deployment.sh` after any deployment. It checks:
- A: Extension files at correct path
- B: Files contain our code (`get_plugin_config`), not old env-var version
- C: `cortex_plugin` importable in venv-a0
- D: (manual) WARNING log lines visible after session
- E: 18 integration tests pass against live Cortex

## Integration Tests — Run First on Issues

When something breaks in production, run integration tests BEFORE anything else:
```bash
CORTEX_URL=http://192.168.1.12:8001 CORTEX_API_KEY=cortex_prod_key \
  python -m pytest tests/integration/ -v -m integration
```
This immediately isolates whether the issue is in Cortex API, our library, or the AZ wiring.

## Config Resolution

- Plugin config stored at: `/opt/agent-zero/data/usr/plugins/agent-zero-cortex/config.json`
- This is the correct AZ resolution path (priority 4: `usr/plugins/<name>/config.json`)
- Read via `get_plugin_config("agent-zero-cortex", agent=agent)` in extensions
- `default_config.yaml` at plugin root provides fallback defaults

## Health Check

UI button in plugin settings calls `POST /api/plugins/agent-zero-cortex/health_check`.
Runs 5 checks: API reachable, DB ready, write+forget memory, recall, extensions wired.
Use this before filing any bug report.

## Cortex API

- URL: `http://192.168.1.12:8001`
- Auth: `Authorization: Bearer cortex_prod_key`
- `area` field only accepts: `main`, `fragments`, `solutions` (422 on anything else)
- `/healthz` → `{"status":"ok"}`, `/readyz` → `{"ready":true,"db":"up"}`
- Scoring: RRF (k=60), max scores ~0.01–0.05, threshold 0.01 works well
