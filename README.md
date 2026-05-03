# agent-zero-cortex

Agent Zero plugin that mirrors every session's memory into the **Cortex** memory backend, running side-by-side with the existing FAISS plugin. FAISS is never touched — Cortex is additive only.

## What it does

Three extensions fire automatically on every Agent Zero session:

| Extension | Hook | What happens |
|-----------|------|--------------|
| `_60_cortex_init.py` | `monologue_start` | Creates a Cortex session, maps the AZ project name to a Cortex topic |
| `_60_cortex_memorize.py` | `monologue_end` | Writes fragments and solutions to Cortex (idempotent — safe to replay) |
| `_60_cortex_recall.py` | `message_loop_prompts_after` | Queries Cortex for relevant memories and appends them to the AZ prompt after FAISS recall |

The `_60_` prefix ensures these run **after** the built-in `_memory` plugin (`_50_*`), so FAISS always runs first.

---

## Requirements

- **Cortex API** running and reachable on your LAN (default: `http://192.168.1.12:8001`)
- **Agent Zero** with the `_memory` (FAISS) plugin enabled — this plugin does not replace it
- Python `httpx` available in the AZ venv (already present in standard AZ images)

---

## Installation

### Manual (recommended for homelab)

```bash
# 1. Copy plugin into AZ's user plugins directory (inside the data volume)
cp -r agent-zero-cortex /opt/agent-zero/data/usr/plugins/

# 2. Enable the plugin (AZ uses a sentinel file for toggle state)
touch /opt/agent-zero/data/usr/plugins/agent-zero-cortex/.toggle-1

# 3. Copy extension files into AZ's extension directories
PLUGIN=/opt/agent-zero/data/usr/plugins/agent-zero-cortex/extensions/python
EXT=/opt/agent-zero/data/python/extensions

cp $PLUGIN/monologue_start/_60_cortex_init.py       $EXT/monologue_start/
cp $PLUGIN/monologue_end/_60_cortex_memorize.py     $EXT/monologue_end/
cp $PLUGIN/message_loop_prompts_after/_60_cortex_recall.py $EXT/message_loop_prompts_after/

# 4. Add env vars to the AZ compose .env file
cat >> /opt/agent-zero/.env << EOF
CORTEX_URL=http://192.168.1.12:8001
CORTEX_API_KEY=your_cortex_api_key
CORTEX_ENABLED=true
CORTEX_RECALL_LIMIT=5
CORTEX_RECALL_THRESHOLD=0.7
CORTEX_MERGE_STRATEGY=append
EOF

# 5. Restart AZ to pick up the new env vars
docker compose -f /opt/agent-zero/docker-compose.yml up -d --force-recreate
```

### Via Proxmox (from Mac, targeting LXC 500)

```bash
# Package the plugin
cd /Users/paolo/Documents/Projects
tar czf /tmp/agent-zero-cortex.tar.gz agent-zero-cortex/

# Copy to Proxmox host and push into LXC 500
scp /tmp/agent-zero-cortex.tar.gz root@192.168.1.5:/tmp/
ssh root@192.168.1.5 "pct push 500 /tmp/agent-zero-cortex.tar.gz /tmp/agent-zero-cortex.tar.gz"

# Extract and install inside LXC 500
ssh root@192.168.1.5 "pct exec 500 -- bash -c '
  cd /tmp && tar xzf agent-zero-cortex.tar.gz
  cp -r agent-zero-cortex /opt/agent-zero/data/usr/plugins/
  touch /opt/agent-zero/data/usr/plugins/agent-zero-cortex/.toggle-1

  PLUGIN=/opt/agent-zero/data/usr/plugins/agent-zero-cortex/extensions/python
  EXT=/opt/agent-zero/data/python/extensions
  cp \$PLUGIN/monologue_start/_60_cortex_init.py       \$EXT/monologue_start/
  cp \$PLUGIN/monologue_end/_60_cortex_memorize.py     \$EXT/monologue_end/
  cp \$PLUGIN/message_loop_prompts_after/_60_cortex_recall.py \$EXT/message_loop_prompts_after/

  grep -v \"^CORTEX_\" /opt/agent-zero/.env > /tmp/az_env_clean
  mv /tmp/az_env_clean /opt/agent-zero/.env
  cat >> /opt/agent-zero/.env << EOF
CORTEX_URL=http://192.168.1.12:8001
CORTEX_API_KEY=your_cortex_api_key
CORTEX_ENABLED=true
CORTEX_RECALL_LIMIT=5
CORTEX_RECALL_THRESHOLD=0.7
CORTEX_MERGE_STRATEGY=append
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
| `CORTEX_RECALL_THRESHOLD` | `0.7` | Minimum RRF score to include a memory (0–1). Lower = more results, less precise |
| `CORTEX_MERGE_STRATEGY` | `append` | How Cortex memories are added to the AZ prompt. `append` = after FAISS block. `off` = recall disabled |
| `CORTEX_FAISS_ASSERTION_CHECK` | `true` | Log an error if the FAISS index mtime changes during a Cortex write (safety guard) |

### Disabling temporarily

```bash
# Disable without removing the plugin
ssh root@192.168.1.5 "pct exec 500 -- sed -i 's/^CORTEX_ENABLED=.*/CORTEX_ENABLED=false/' /opt/agent-zero/.env"
# No restart needed — extensions check the env var on every call
```

### Disabling recall only (keep memorize)

```bash
ssh root@192.168.1.5 "pct exec 500 -- sed -i 's/^CORTEX_MERGE_STRATEGY=.*/CORTEX_MERGE_STRATEGY=off/' /opt/agent-zero/.env"
```

---

## How each extension works

### `_60_cortex_init.py` — session init

Fires at the start of every AZ monologue. Posts to `POST /v1/sessions` with:
- `external_session_id`: the AZ context ID
- `source`: `"az"`
- `initial_topic_slug`: the AZ project name, sanitized to `[a-z0-9_-]` (e.g. `"My Project!"` → `"my_project_"`)

The returned Cortex session ID is stored in `agent.context` via `set_data("cortex_session_id", ...)` and used by the other two extensions.

If Cortex is unreachable, the extension logs a warning and returns — AZ continues normally with FAISS only.

### `_60_cortex_memorize.py` — memory write

Fires at the end of every AZ monologue. Reads `loop_data.fragments` and `loop_data.solutions` (the same data the FAISS plugin writes) and posts each to `POST /v1/memories`:
- Fragments → `area: "fragments"`, `importance: 0.5`
- Solutions → `area: "solutions"`, `importance: 0.7`

Each write includes an `Idempotency-Key` header (`sha256(session_id|area|content)`), so replaying the same session never creates duplicates.

If `CORTEX_FAISS_ASSERTION_CHECK=true`, the extension checks the FAISS index file's mtime before and after — if it changed, an error is logged (it should never change during a Cortex write).

### `_60_cortex_recall.py` — memory recall

Fires after every AZ message loop iteration, after FAISS recall has already run. Queries `POST /v1/recall` using the last message as the search query, then **appends** the results to `loop_data.extras_persistent["memories"]` as a `## Cortex memories (additional)` markdown block.

The FAISS memory block is always preserved — Cortex results are appended after it, never replacing it. If `CORTEX_MERGE_STRATEGY=off`, this extension does nothing.

---

## Verifying it works

### Check the plugin is visible in AZ UI

Open the AZ web UI → Settings → Plugins. You should see **Cortex Memory Backend** with toggle ON.

### Check a session creates a Cortex session

```bash
# Before starting an AZ session, count sessions
curl -s -H "Authorization: Bearer $CORTEX_API_KEY" http://192.168.1.12:8001/v1/topics | jq '.[] | {slug, memory_count}'

# Start an AZ session, then check again — memory_count should increment
```

### Check memories are being written

```bash
curl -s -H "Authorization: Bearer $CORTEX_API_KEY" \
  -H "Content-Type: application/json" \
  -X POST http://192.168.1.12:8001/v1/recall \
  -d '{"query": "your recent AZ task", "limit": 5}' | jq '.[] | {content, matched_via, score}'
```

### Check AZ logs for extension activity

```bash
# From Proxmox host
ssh root@192.168.1.5 "pct exec 500 -- docker logs agent-zero --tail 50 2>&1" | grep -E "cortex_init|cortex_memorize|cortex_recall"
```

Expected log lines:
```
cortex_init: session created <uuid> for project homelab
cortex_memorize: wrote 3 fragments, 1 solutions
cortex_recall: appended 4 memories to extras
```

### Verify FAISS is untouched

```bash
# Check FAISS index mtime before and after an AZ session
ssh root@192.168.1.5 "pct exec 500 -- stat /opt/agent-zero/data/usr/projects/homelab/.a0proj/memory/index.faiss"
# mtime should only change when AZ's own _memory plugin writes — never from Cortex
```

---

## Updating the plugin

When a new version of `agent-zero-cortex` is available:

```bash
# From Mac
cd /Users/paolo/Documents/Projects
git -C agent-zero-cortex pull

tar czf /tmp/agent-zero-cortex.tar.gz agent-zero-cortex/
scp /tmp/agent-zero-cortex.tar.gz root@192.168.1.5:/tmp/
ssh root@192.168.1.5 "pct push 500 /tmp/agent-zero-cortex.tar.gz /tmp/agent-zero-cortex.tar.gz"

ssh root@192.168.1.5 "pct exec 500 -- bash -c '
  cd /tmp && tar xzf agent-zero-cortex.tar.gz
  cp -r agent-zero-cortex/* /opt/agent-zero/data/usr/plugins/agent-zero-cortex/

  PLUGIN=/opt/agent-zero/data/usr/plugins/agent-zero-cortex/extensions/python
  EXT=/opt/agent-zero/data/python/extensions
  cp \$PLUGIN/monologue_start/_60_cortex_init.py       \$EXT/monologue_start/
  cp \$PLUGIN/monologue_end/_60_cortex_memorize.py     \$EXT/monologue_end/
  cp \$PLUGIN/message_loop_prompts_after/_60_cortex_recall.py \$EXT/message_loop_prompts_after/
'"
# No restart needed — AZ loads extensions dynamically
```

---

## Uninstalling

```bash
ssh root@192.168.1.5 "pct exec 500 -- bash -c '
  # Remove extension files
  rm -f /opt/agent-zero/data/python/extensions/monologue_start/_60_cortex_init.py
  rm -f /opt/agent-zero/data/python/extensions/monologue_end/_60_cortex_memorize.py
  rm -f /opt/agent-zero/data/python/extensions/message_loop_prompts_after/_60_cortex_recall.py

  # Remove plugin directory
  rm -rf /opt/agent-zero/data/usr/plugins/agent-zero-cortex

  # Remove env vars
  grep -v \"^CORTEX_\" /opt/agent-zero/.env > /tmp/az_env_clean
  mv /tmp/az_env_clean /opt/agent-zero/.env
'"
# No restart needed
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Plugin not visible in AZ UI | Missing `.toggle-1` file | `touch /opt/agent-zero/data/usr/plugins/agent-zero-cortex/.toggle-1` |
| Extensions not firing | Files not copied to `data/python/extensions/` | Re-run the `cp` commands in the install section |
| `cortex_init: failed` in logs | Cortex API unreachable or wrong key | Check `CORTEX_URL` and `CORTEX_API_KEY`; `curl http://192.168.1.12:8001/healthz` |
| `cortex_memorize: no cortex_session_id` | `_60_cortex_init.py` didn't run | Verify the file is in `data/python/extensions/monologue_start/` |
| No memories appearing in recall | `CORTEX_RECALL_THRESHOLD` too high | Lower to `0.3` or `0.1` for testing; embeddings may not be generated yet |
| FAISS mtime changed error | Bug — Cortex wrote to FAISS path | File a bug; check `CORTEX_FAISS_ASSERTION_CHECK=true` logs |
| `cortex_memorize: fragment write failed: 401` | Wrong `CORTEX_API_KEY` | Update key in `/opt/agent-zero/.env` |

---

## Architecture

```
AZ session start
  └── monologue_start
        ├── _10_memory_init.py   (FAISS — built-in)
        └── _60_cortex_init.py   (Cortex — this plugin)
              └── POST /v1/sessions → cortex_session_id cached in ctx

AZ message loop (each iteration)
  └── message_loop_prompts_after
        ├── _50_recall_memories.py  (FAISS — built-in, runs first)
        └── _60_cortex_recall.py    (Cortex — appends after FAISS block)
              └── POST /v1/recall → results appended to extras["memories"]

AZ session end
  └── monologue_end
        ├── _50_memorize_fragments.py  (FAISS — built-in)
        └── _60_cortex_memorize.py     (Cortex — mirrors to Cortex)
              └── POST /v1/memories (fragments + solutions, idempotent)
```

Cortex stores memories in PostgreSQL with hybrid retrieval (vector + BM25 + trigram). FAISS stores them in a local `.faiss` file. Both are always written — neither is a replacement for the other.
