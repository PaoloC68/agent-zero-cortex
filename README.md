# agent-zero-cortex

Agent Zero plugin that makes **Cortex** the primary memory backend. FAISS is permanently disabled — Cortex handles all memory extraction, storage, and recall.

## What it does

Three extensions fire automatically on every Agent Zero session:

| Extension | Hook | What happens |
|-----------|------|--------------|
| `_60_cortex_init.py` | `monologue_start` | Creates a Cortex session, maps the AZ project name to a Cortex topic |
| `_60_cortex_memorize.py` | `monologue_end` | Extracts fragments and solutions via an independent LLM call, then writes them to Cortex (idempotent) |
| `_60_cortex_recall.py` | `message_loop_prompts_after` | Queries Cortex for relevant memories using fence-strategy rerank, then replaces the AZ prompt memory block |

The `_60_` prefix ensures these run **after** the built-in `_memory` plugin's `_50_*` files. The built-in FAISS plugin is disabled — its hooks still fire but produce no output.

### Memory extraction

`_60_cortex_memorize.py` doesn't read from FAISS. It calls `agent.call_utility_model` with vendored prompts (from `prompts/`) to independently extract fragments and solutions from the conversation. This means memory quality depends on the extraction LLM, not on FAISS's summarization.

Two-tier timeout: 5 seconds for the extraction phase, 10 seconds for the posting phase. If extraction times out, the extension logs a warning and skips — AZ continues normally.

### Recall strategy

`_60_cortex_recall.py` uses a fence-strategy rerank: it fetches `limit × 5` candidates (floor 30), prioritizes memories from the current project, then fills remaining slots from cross-project results. The final block **replaces** `extras_persistent["memories"]` rather than appending to it.

---

## Requirements

- **Cortex API** running and reachable on your LAN (default: `http://192.168.1.12:8001`)
- **Agent Zero** — the built-in `_memory` (FAISS) plugin should be disabled or ignored
- Python `httpx` and `dirtyjson` available in the AZ venv (installed via the pip step below)

---

## Installation

### Manual (recommended for homelab)

AZ discovers extensions directly from the plugin directory — no copying required. Dependencies are installed automatically on first use by `helpers/dependencies.py`.

```bash
# 1. Clone the plugin into AZ's user plugins directory (inside the data volume)
git clone https://github.com/PaoloC68/agent-zero-cortex.git \
  /opt/agent-zero/data/usr/plugins/agent-zero-cortex

# 2. Enable the plugin (AZ uses a sentinel file for toggle state)
touch /opt/agent-zero/data/usr/plugins/agent-zero-cortex/.toggle-1

# 3. Add env vars to the AZ compose .env file
cat >> /opt/agent-zero/.env << EOF
CORTEX_URL=http://192.168.1.12:8001
CORTEX_API_KEY=your_cortex_api_key
CORTEX_ENABLED=true
CORTEX_RECALL_LIMIT=5
CORTEX_RECALL_THRESHOLD=0.02
EOF

# 4. Restart AZ to pick up the new env vars
docker compose -f /opt/agent-zero/docker-compose.yml up -d --force-recreate
```

Dependencies (`httpx`, `pydantic`, `dirtyjson`) are installed automatically the first time an extension fires. No manual `pip install` step required.

### Via Proxmox (from Mac, targeting LXC 500)

```bash
ssh root@192.168.1.5 "pct exec 500 -- bash -c '
  git clone https://github.com/PaoloC68/agent-zero-cortex.git \
    /opt/agent-zero/data/usr/plugins/agent-zero-cortex
  touch /opt/agent-zero/data/usr/plugins/agent-zero-cortex/.toggle-1

  grep -v "^CORTEX_" /opt/agent-zero/.env > /tmp/az_env_clean
  mv /tmp/az_env_clean /opt/agent-zero/.env
  cat >> /opt/agent-zero/.env << EOF
CORTEX_URL=http://192.168.1.12:8001
CORTEX_API_KEY=your_cortex_api_key
CORTEX_ENABLED=true
CORTEX_RECALL_LIMIT=5
CORTEX_RECALL_THRESHOLD=0.02
EOF
  docker compose -f /opt/agent-zero/docker-compose.yml up -d --force-recreate
'"
```

---

## Configuration

All configuration is via environment variables in `/opt/agent-zero/.env`. No restart needed for `CORTEX_ENABLED` changes — the extensions read env vars on every call.

| Variable | Default | Description |
|----------|---------|-------------|
| `CORTEX_URL` | `http://192.168.1.12:8001` | Cortex API base URL |
| `CORTEX_API_KEY` | *(required)* | Bearer token for Cortex API |
| `CORTEX_ENABLED` | `true` | Master switch. Set to `false` to disable all three extensions without removing them |
| `CORTEX_RECALL_LIMIT` | `5` | Max memories returned per recall query |
| `CORTEX_RECALL_THRESHOLD` | `0.02` | Minimum score to include a memory. Tune this after Cortex upgrades — see Cortex Version Compatibility below |
| `CORTEX_RECALL_LEGACY_RANK` | `false` | Set to `true` to use legacy RRF ranking instead of composite scoring. Emergency rollback for post-v1.1 recall quality issues |
| `CORTEX_PROMPT_DIR` | *(unset = vendored)* | Path to a directory containing custom extraction prompt files. Falls back to vendored prompts if unset or if files are missing |

### Disabling temporarily

```bash
# Disable without removing the plugin
ssh root@192.168.1.5 "pct exec 500 -- sed -i 's/^CORTEX_ENABLED=.*/CORTEX_ENABLED=false/' /opt/agent-zero/.env"
# No restart needed — extensions check the env var on every call
```

---

## How each extension works

### `_60_cortex_init.py` — session init

Fires at the start of every AZ monologue. Posts to `POST /v1/sessions` with:
- `external_session_id`: the AZ context ID
- `source`: `"az"`
- `initial_topic_slug`: the AZ project name, sanitized to `[a-z0-9_-]` (e.g. `"My Project!"` → `"my_project_"`)

The returned Cortex session ID is stored in `agent.context` via `set_data("cortex_session_id", ...)` and used by the other two extensions.

If no AZ project is set, the extension logs a warning about project-less behavior and proceeds with a default topic slug. Recall will still work but memories won't be associated with a specific project — cross-project fence rerank will treat all memories equally.

If Cortex is unreachable, the extension logs a warning and returns — AZ continues without memory.

### `_60_cortex_memorize.py` — memory write

Fires at the end of every AZ monologue. Calls `agent.call_utility_model` with vendored prompts to extract fragments and solutions independently from the conversation history (up to 80,000 chars). Then posts each to `POST /v1/memories`:
- Fragments → `kind: "fragment"`, `area: "fragments"`, `importance: 0.5`
- Solutions → **two memories per solution**: problem (`kind: "solution-problem"`, `area: "fragments"`, `importance: 0.7`) + solution step (`kind: "solution-step"`, `area: "solutions"`, `importance: 0.7`)

Each write includes an `Idempotency-Key` header (`sha256(session_id|area|content)`), so replaying the same session never creates duplicates.

Timeouts: 5 seconds for the LLM extraction call, 10 seconds for each HTTP post to Cortex. If extraction fails or times out, the extension logs a warning and skips the write — no memories are lost from previous sessions.

If the stale-project rebind log line appears (`cortex_memorize: rebound to project ...`), it means the session's project slug changed mid-session. This is normal when AZ switches projects during a long conversation.

### `_60_cortex_recall.py` — memory recall

Fires after every AZ message loop iteration. Queries `POST /v1/recall` using the last message as the search query, fetches `limit × 5` candidates (floor 30), then applies fence-strategy rerank: same-project memories fill the first slots, cross-project memories fill the rest.

The result **replaces** `loop_data.extras_persistent["memories"]` with a `## Cortex memories` markdown block. This is a full replacement, not an append.

---

## Architecture

```
AZ session start
  └── monologue_start
        └── _60_cortex_init.py
              └── POST /v1/sessions → cortex_session_id cached in ctx

AZ message loop (each iteration)
  └── message_loop_prompts_after
        └── _60_cortex_recall.py
              ├── POST /v1/recall (limit × 5 candidates, floor 30)
              ├── fence_rerank: same-project first, cross-project fill
              └── extras["memories"] replaced with ## Cortex memories block

AZ session end
  └── monologue_end
        └── _60_cortex_memorize.py
              ├── call_utility_model → extract fragments + solutions (5s timeout)
              └── POST /v1/memories × N (idempotent, 10s timeout each)
```

Cortex stores memories in PostgreSQL with hybrid retrieval (vector + BM25 + trigram). Scores depend on the Cortex version — see the compatibility matrix below.

---

## Cortex Version Compatibility

Cortex's scoring algorithm changed significantly at v1.1. The default `CORTEX_RECALL_THRESHOLD` of `0.02` is calibrated for the MVP (RRF) scoring range. After upgrading Cortex, run the calibration script and update your threshold.

| Cortex version | Scoring algorithm | Score range | Recommended threshold | `CORTEX_RECALL_LEGACY_RANK` |
|----------------|-------------------|-------------|----------------------|------------------------------|
| MVP (current) | RRF (k=60) | ~0.01–0.05 | `0.02` | `false` |
| v1.1 cognitive | Composite (vector + BM25 + recency) | ~0.10–0.95 | `0.30`–`0.50` | `false` (default) |
| v2.0 substrate | Same as v1.1 (PG18 + TimescaleDB + MCP — no scoring change) | ~0.10–0.95 | `0.30`–`0.50` | `false` |
| v2.1 scale | Same as v1.1 (DiskANN tuning is index-internal) | ~0.10–0.95 | `0.30`–`0.50` | `false` |

### Calibration procedure

Run this after every Cortex version upgrade:

```bash
bash scripts/calibrate-recall-threshold.sh
```

The script queries Cortex with a set of known-good and known-bad queries, prints the score distribution, and suggests a threshold. Update `CORTEX_RECALL_THRESHOLD` in `/opt/agent-zero/.env` accordingly. No restart needed.

If recall quality degrades immediately after a Cortex upgrade and you can't calibrate right away, set `CORTEX_RECALL_LEGACY_RANK=true` as an emergency rollback. This forces RRF-style ranking regardless of the Cortex version. Revert once you've calibrated.

---

## Reflector Mutation Awareness (Cortex v1.1+)

Starting with Cortex v1.1, the **Reflector** runs nightly at 3 AM UTC. It:
- Merges near-duplicate memories with cosine similarity >= 0.95
- Applies importance decay (×0.99 per night) to older memories
- Supersedes stale memories when a newer, higher-importance version exists

This means a memory you wrote yesterday may appear differently in recall today. The content you get back is the canonical post-merge version, not necessarily the exact text that was written. This is intended behavior, not a bug.

Practical implications:
- Don't rely on exact memory content matching across sessions
- If a memory seems "combined" with another, the Reflector merged them
- Importance scores drift downward over time — very old memories may fall below threshold

There's no way to disable the Reflector from the plugin side. If you need to preserve exact memory content, write it with high importance (`0.9`+) so decay takes longer to push it below threshold.

---

## Verifying it works

### Check the plugin is visible in AZ UI

Open the AZ web UI → Settings → Plugins. You should see **Cortex Memory Backend** with toggle ON.

### Check a session creates a Cortex session

```bash
# Before starting an AZ session, count topics
curl -s -H "Authorization: Bearer $CORTEX_API_KEY" http://192.168.1.12:8001/v1/topics | jq '.[] | {slug, memory_count}'

# Start an AZ session, then check again — memory_count should increment
```

### Check memories are being written

```bash
curl -s -H "Authorization: Bearer $CORTEX_API_KEY" \
  -H "Content-Type: application/json" \
  -X POST http://192.168.1.12:8001/v1/recall \
  -d '{"query": "your recent AZ task", "limit": 5, "threshold": 0.01}' \
  | jq '.[] | {content, matched_via, score}'
```

### Check AZ logs for extension activity

```bash
# From Proxmox host
ssh root@192.168.1.5 "pct exec 500 -- docker logs agent-zero --tail 50 2>&1" | grep -E "cortex\.(init|memorize|recall)"
```

Expected log lines:

```
cortex.init: session=<uuid> project=homelab
cortex.memorize: written=4 failed=0 timed_out=False ms=1234
cortex.recall: results=30 after_fence=4 project=homelab ms=456
```

---

## Updating the plugin

When a new version of `agent-zero-cortex` is available:

```bash
ssh root@192.168.1.5 "pct exec 500 -- bash -c '
  git -C /opt/agent-zero/data/usr/plugins/agent-zero-cortex pull --ff-only
'"
# No restart needed — AZ loads extensions dynamically from the plugin directory
```

---

## Uninstalling

```bash
ssh root@192.168.1.5 "pct exec 500 -- bash -c '
  # Remove plugin directory
  rm -rf /opt/agent-zero/data/usr/plugins/agent-zero-cortex

  # Remove env vars
  grep -v "^CORTEX_" /opt/agent-zero/.env > /tmp/az_env_clean
  mv /tmp/az_env_clean /opt/agent-zero/.env
'"
# No restart needed
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Plugin not visible in AZ UI | Missing `.toggle-1` file | `touch /opt/agent-zero/data/usr/plugins/agent-zero-cortex/.toggle-1` |
| Extensions not firing | Plugin not enabled or `.toggle-1` missing | `touch /opt/agent-zero/data/usr/plugins/agent-zero-cortex/.toggle-1` |
| `ModuleNotFoundError: cortex_plugin` | `uv` not on PATH or `requirements.txt` missing | Verify `uv` is available in the container; check plugin dir is intact |
| `cortex.init: failed` in logs | Cortex API unreachable or wrong key | Check `CORTEX_URL` and `CORTEX_API_KEY`; `curl http://192.168.1.12:8001/healthz` |
| `cortex.memorize: no cortex_session_id` | `_60_cortex_init.py` didn't run | Verify the file is in `data/extensions/python/monologue_start/` |
| `cortex.memorize: extraction timed out` | LLM call exceeded 5s | Check AZ utility model availability; consider a faster model |
| `cortex.memorize: extraction failed` | LLM returned unparseable JSON | Check AZ logs for the raw LLM response; `dirtyjson` handles most malformed JSON but not all |
| No memories appearing in recall | `CORTEX_RECALL_THRESHOLD` too high for current Cortex version | Run `bash scripts/calibrate-recall-threshold.sh` and update threshold |
| Recall returns junk after Cortex upgrade | Score range changed (v1.1+ uses composite scoring) | Run calibration script and update `CORTEX_RECALL_THRESHOLD`, OR set `CORTEX_RECALL_LEGACY_RANK=true` as emergency rollback |
| `cortex.init: project-less session` in logs | AZ session has no project set | Expected behavior — memories are stored without project association; recall still works |
| `cortex.memorize: project changed mid-session` | Project slug changed mid-session | Normal for long sessions that switch AZ projects |
| `cortex.memorize: failed` with 401 | Wrong `CORTEX_API_KEY` | Update key in `/opt/agent-zero/.env` |
| `cortex.memorize: timed_out=True` in logs | Cortex API slow or overloaded | Check Cortex server health; the 10s timeout is intentionally generous |
