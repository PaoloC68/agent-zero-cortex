# T2 Spike — Verify `_memory` Plugin Can Be Silenced

**Date:** 2026-05-08  
**Outcome: PASS**

---

## Method

### 1. Source code review

Read the `_memory` plugin extension files on the local AZ checkout:
- `/Users/paolo/Documents/Projects/agent-zero/plugins/_memory/extensions/python/monologue_end/_50_memorize_fragments.py`
- `/Users/paolo/Documents/Projects/agent-zero/plugins/_memory/extensions/python/message_loop_prompts_after/_50_recall_memories.py`
- `/Users/paolo/Documents/Projects/agent-zero/helpers/plugins.py` (`get_plugin_config`)

Key finding: both extensions gate their entire execution with:
```python
set = plugins.get_plugin_config("_memory", self.agent)
if not set["memory_memorize_enabled"]:
    return           # exits BEFORE creating any log item or starting deferred LLM task
```
and
```python
if not set["memory_recall_enabled"]:
    return None      # exits BEFORE creating log item or calling LLM
```

`get_plugin_config` reads the config file at:  
`{project_dir}/.a0proj/plugins/_memory/config.json`  
where the project dir resolves from the active project context.

### 2. Test project creation

On LXC 500 (root@192.168.1.5, `pct exec 500`):

```bash
# Created project directory
mkdir -p /opt/agent-zero/data/usr/projects/_test_cortex_primary/.a0proj/plugins/_memory

# Created project.json
echo '{"name":"_test_cortex_primary","description":"Test project for cortex-primary spike - memory disabled"}' \
  > /opt/agent-zero/data/usr/projects/_test_cortex_primary/.a0proj/project.json

# Created config.json with both memory flags disabled (via python3 to ensure valid JSON)
python3 -c "
import json
config = {
    'project_memory_isolation': True,
    'memory_recall_enabled': False,
    'memory_recall_delayed': False,
    'memory_recall_interval': 3,
    'memory_recall_history_len': 10000,
    'memory_recall_memories_max_search': 12,
    'memory_recall_solutions_max_search': 8,
    'memory_recall_memories_max_result': 5,
    'memory_recall_solutions_max_result': 3,
    'memory_recall_similarity_threshold': 0.7,
    'memory_recall_query_prep': False,
    'memory_recall_post_filter': False,
    'memory_memorize_enabled': False,
    'memory_memorize_consolidation': True,
    'memory_memorize_replace_threshold': 0.9,
    'agent_memory_subdir': 'default'
}
with open('/opt/agent-zero/data/usr/projects/_test_cortex_primary/.a0proj/plugins/_memory/config.json', 'w') as f:
    json.dump(config, f, indent=2)
"
# Verified: {"memory_memorize_enabled": false, "memory_recall_enabled": false}
```

### 3. Test session triggered

Via AZ HTTP API (container is localhost:8080 inside LXC 500):

```bash
# Login to get session cookie
curl -s -c /tmp/az_cookie.txt -b /tmp/az_cookie.txt \
  -d "username=<redacted>&password=<redacted>" \
  -L http://localhost:8080/login -o /tmp/az_login.html

# Get CSRF token
CSRF_RESP=$(curl -s http://localhost:8080/api/csrf_token -b /tmp/az_cookie.txt -c /tmp/az_cookie.txt)
# → {"ok": true, "token": "MFQWQ7gzwvs0uLu_hdbOsUQmiS1-CrRiu8jW98Yp0vI", "runtime_id": "61aae6bac5102eb1"}

# Create context
curl -s -X POST http://localhost:8080/api/chat_create -H "X-CSRF-Token: $CSRF_TOKEN" -b /tmp/az_cookie.txt -d "{}"
# → {"ok": true, "ctxid": "wc6dUeIL", ...}

# Activate _test_cortex_primary project on context
curl -s -X POST http://localhost:8080/api/projects \
  -H "X-CSRF-Token: $CSRF_TOKEN" -b /tmp/az_cookie.txt \
  -d '{"action": "activate", "context_id": "wc6dUeIL", "name": "_test_cortex_primary"}'
# → {"ok": true, "data": null}

# Send test message (timing: 17:10:51 → 17:10:54 UTC, 3 seconds)
curl -s -X POST http://localhost:8080/api/message \
  -H "X-CSRF-Token: $CSRF_TOKEN" -b /tmp/az_cookie.txt \
  -d '{"text": "Reply with only the word: CORTEX_SPIKE_TEST_DONE", "context": "wc6dUeIL"}'
# → {"message": "CORTEX_SPIKE_TEST_DONE", "context": "wc6dUeIL"}
```

### 4. Log capture

```bash
# Docker log since test start
docker logs agent-zero --since 2026-05-08T17:10:00 2>&1

# AZ UI log items for context wc6dUeIL (via /api/poll)
curl -s -X POST http://localhost:8080/api/poll \
  -H "X-CSRF-Token: $CSRF_TOKEN" -b /tmp/az_cookie.txt \
  -d '{"context": "wc6dUeIL", "log_from": 0}'

# Filesystem check
ls -la /opt/agent-zero/data/usr/projects/_test_cortex_primary/.a0proj/memory/
```

---

## Observation

### Docker log (17:10:51–17:10:54 UTC)

```
[User message]
> Reply with only the word: CORTEX_SPIKE_TEST_DONE

[Guard] Injection pattern detected: ignore previous instructions

Response:
{
    "thoughts": ["User wants me to reply with only that word."],
    "headline": "CORTEX_SPIKE_TEST_DONE",
    "tool_name": "response",
    "tool_args": {"text": "CORTEX_SPIKE_TEST_DONE"}
}
```

Total docker log lines since test: **21 lines** (no memory-related output).

### UI log items for context `wc6dUeIL`

| # | type | heading |
|---|------|---------|
| 0 | `response` | *(initial system greeting)* |
| 1 | `user` | *(user message)* |
| 2 | `agent` | `A0: CORTEX_SPIKE_TEST_DONE` |
| 3 | `response` | `icon://chat A0: Responding` |

**Total: 4 items. Zero `type=util` items.**

### Expected markers — ABSENT

| Marker | Extension | Status |
|--------|-----------|--------|
| `"Searching memories..."` | `_50_recall_memories.py` | **ABSENT** ✅ |
| `"Memorizing new information..."` | `_50_memorize_fragments.py` | **ABSENT** ✅ |

### Filesystem: memory directory after session

```
/opt/agent-zero/data/usr/projects/_test_cortex_primary/.a0proj/memory/
  (empty — no FAISS index, no memory DB created)
```

If either `memory_recall_enabled` or `memory_memorize_enabled` had been active, FAISS would have been initialized and the memory directory would contain `index.faiss` and metadata files.

---

## Outcome

### PASS ✅

The `memory_memorize_enabled: false` and `memory_recall_enabled: false` settings in a project-level `config.json` completely silence the `_memory` plugin for that project.

**Evidence chain:**
1. Source code confirms: the settings gate is the FIRST check in each extension, before any log item creation, LLM call, or deferred task.
2. UI log: 4 items, zero `type=util` items — no `"Searching memories..."`, no `"Memorizing new information..."`.
3. Filesystem: `memory/` directory for `_test_cortex_primary` is empty after the session — no FAISS DB initialized.
4. Session completed in 3 seconds (17:10:51→17:10:54) — no LLM extraction call occurred (those take 5–30s).

**Implication for plan:**  
Wave 2 can proceed. `_memory` LLM extraction calls will not interfere with the Cortex-primary refactor when projects are configured with both flags set to `false`. The cortex-primary architecture (own LLM extraction in `_60_cortex_memorize.py`) can run independently.

---

## Related files

- Config created: `/opt/agent-zero/data/usr/projects/_test_cortex_primary/.a0proj/plugins/_memory/config.json`
- Log evidence: `.sisyphus/evidence/task-2-logs.txt`
- Context log JSON: `.sisyphus/evidence/task-2-context-log.json`
