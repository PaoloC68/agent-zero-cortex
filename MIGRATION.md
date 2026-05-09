# FAISS → Cortex Migration

> **Why this file exists**: The FAISS-to-Cortex migration was a one-time event in May 2026. The script below is preserved for historical and forensic purposes only. The migration has already run. Do not run it again.

---

## Rollback Procedure

Use this if you need to revert to the pre-refactor FAISS-based setup.

```bash
# 1. Stop Agent Zero
docker compose -f /opt/agent-zero/docker-compose.yml stop

# 2. Check out the pre-refactor tag
git checkout pre-cortex-primary-v1

# 3. Uninstall the cortex plugin package from the AZ container
docker exec agent-zero pip uninstall -y agent-zero-cortex

# 4. Re-deploy the old extension files (from the pre-refactor README)
PLUGIN=/opt/agent-zero/data/usr/plugins/agent-zero-cortex/extensions/python
EXT=/opt/agent-zero/data/extensions/python
cp $PLUGIN/monologue_start/_60_cortex_init.py       $EXT/monologue_start/
cp $PLUGIN/monologue_end/_60_cortex_memorize.py     $EXT/monologue_end/
cp $PLUGIN/message_loop_prompts_after/_60_cortex_recall.py $EXT/message_loop_prompts_after/

# 5. Start Agent Zero
docker compose -f /opt/agent-zero/docker-compose.yml up -d

# 6. Verify rollback
docker exec agent-zero ls /a0/python/extensions/monologue_end/_60_cortex_memorize.py
# Expected: prints the file path

docker exec agent-zero python -c "import cortex_plugin"
# Expected: ModuleNotFoundError — this is correct post-rollback
```

The `pre-cortex-primary-v1` tag marks the last commit before Cortex became the primary backend. After rollback, FAISS handles all memory operations and Cortex is unreachable from AZ.

---

## Cortex Version Compatibility & Calibration

Cortex's scoring algorithm changed significantly at v1.1. The default `CORTEX_RECALL_THRESHOLD` of `0.02` is calibrated for MVP (RRF) scoring. After any Cortex upgrade, run the calibration script and update your threshold.

### Version matrix

| Cortex version | Scoring algorithm | Score range | Recommended `CORTEX_RECALL_THRESHOLD` | `CORTEX_RECALL_LEGACY_RANK` |
|----------------|-------------------|-------------|---------------------------------------|------------------------------|
| MVP (current) | RRF (k=60) | ~0.01–0.05 | `0.02` | `false` |
| v1.1 cognitive | Composite (vector + BM25 + recency) | ~0.10–0.95 | `0.30`–`0.50` | `false` (default) |
| v2.0 substrate | Same as v1.1 (PG18 + TimescaleDB + MCP, no scoring change) | ~0.10–0.95 | `0.30`–`0.50` | `false` |
| v2.1 scale | Same as v1.1 (DiskANN tuning is index-internal) | ~0.10–0.95 | `0.30`–`0.50` | `false` |

### Calibration procedure

Run this after every Cortex version upgrade:

```bash
bash scripts/calibrate-recall-threshold.sh
```

The script queries Cortex with a set of known-good and known-bad queries, prints the score distribution as JSON, and suggests a threshold. The output looks like:

```json
{
  "p10": 0.03,
  "p50": 0.18,
  "p90": 0.72,
  "suggested_threshold": 0.35,
  "notes": "Score range shifted — likely v1.1+ composite scoring"
}
```

Take the `suggested_threshold` value and update `CORTEX_RECALL_THRESHOLD` in `/opt/agent-zero/.env`. No restart needed.

### Emergency rollback for recall quality

If recall quality degrades immediately after a Cortex upgrade and you can't calibrate right away:

```bash
# Force legacy RRF ordering regardless of Cortex version
sed -i 's/^CORTEX_RECALL_LEGACY_RANK=.*/CORTEX_RECALL_LEGACY_RANK=true/' /opt/agent-zero/.env
# No restart needed
```

Setting `CORTEX_RECALL_LEGACY_RANK=true` forces Cortex v1.1+ to return pre-v1.1 RRF ordering. Revert to `false` once you've run the calibration script.

### Reflector Mutation Notice (Cortex v1.1+)

Starting with Cortex v1.1, the **Reflector** runs nightly at 3 AM UTC. It:
- Merges near-duplicate memories with cosine similarity >= 0.95
- Applies importance decay (×0.99 per night) to older memories
- Supersedes stale memories when a newer, higher-importance version exists

Memories you wrote yesterday may appear differently in recall today. The content returned is the canonical post-merge version. This is intended Cortex behavior, not a bug.

Our plugin holds no memory IDs across calls, so we tolerate Reflector mutations transparently. There's nothing to fix on the plugin side when this happens.

Practical implications:
- Don't rely on exact memory content matching across sessions
- If a memory seems "combined" with another, the Reflector merged them
- Importance scores drift downward over time — very old memories may fall below threshold

### Post-upgrade smoke test

After every Cortex version upgrade, run:

```bash
pytest tests/integration/test_forward_compat.py -v -m integration
```

This confirms the plugin still communicates correctly with the new Cortex API. If the test suite isn't available locally, run it from inside the AZ container:

```bash
docker exec agent-zero bash -c "cd /opt/agent-zero/data/usr/plugins/agent-zero-cortex && pytest tests/integration/test_forward_compat.py -v -m integration"
```

---

## FAISS Migration Script

> **doc-only — DO NOT RE-RUN**
>
> This script ran once in May 2026 to seed Cortex with existing FAISS memories. Re-running it will attempt to re-post all memories. The idempotency keys will prevent duplicates, but it wastes time and API calls. The script is kept here for forensic reference only.

### Preconditions

- Cortex API running and reachable at `$CORTEX_URL` (default: `http://192.168.1.12:8001`)
- `agent-zero-cortex` plugin enabled in Agent Zero
- FAISS plugin still active (side-by-side migration)
- Project name known (e.g., `homelab`)
- `CORTEX_API_KEY` env var set

## Read FAISS Index

```python
import os
from langchain_community.vectorstores import FAISS

project = "homelab"  # Replace with actual project name
faiss_path = f"/opt/agent-zero/data/usr/projects/{project}/.a0proj/memory"
db = FAISS.load_local(faiss_path, embeddings=None, allow_dangerous_deserialization=True)
```

## Enumerate Documents

```python
doc_ids = list(db.docstore._dict.keys())
documents = [(doc_id, db.docstore.search(doc_id)) for doc_id in doc_ids]
```

## For Each Document

```python
import hashlib, httpx, os

cortex_url = os.environ.get("CORTEX_URL", "http://192.168.1.12:8001")
cortex_api_key = os.environ.get("CORTEX_API_KEY", "")
project_slug = project.lower().replace(" ", "_")[:64]

async def migrate_document(doc_id, doc):
    content = doc.page_content
    metadata = doc.metadata or {}
    idem_key = hashlib.sha256(f"{project_slug}|{doc_id}".encode()).hexdigest()

    async with httpx.AsyncClient(timeout=30.0) as client:
        await client.post(
            f"{cortex_url}/v1/memories",
            json={
                "content": content,
                "kind": metadata.get("area", "main"),
                "area": metadata.get("area", "main"),
                "source_session_id": metadata.get("session_id"),
                "source_project": project_slug,
                "importance": 0.5,
            },
            headers={
                "Authorization": f"Bearer {cortex_api_key}",
                "Idempotency-Key": idem_key,
            },
        )
```

## Verify

After migration, verify count matches:

```bash
# FAISS count
python3 -c "
from langchain_community.vectorstores import FAISS
db = FAISS.load_local('/opt/agent-zero/data/usr/projects/homelab/.a0proj/memory', embeddings=None, allow_dangerous_deserialization=True)
print(len(db.docstore._dict))
"

# Cortex count
curl -s -H "Authorization: Bearer $CORTEX_API_KEY" \
  "http://192.168.1.12:8001/v1/topics" | jq '.[] | select(.slug=="homelab") | .memory_count'
```

## (Optional) Disable FAISS for This Project

Set per-project config override in Agent Zero:
```yaml
_memory.memory_recall_enabled: false
_memory.memory_memorize_enabled: false
```
