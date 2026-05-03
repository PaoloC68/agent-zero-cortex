# SKILL: Migrate FAISS Memory to Cortex

Procedure for migrating a project's FAISS memory into Cortex. Run once per project.
Idempotent: re-running produces no duplicate memories (Idempotency-Key headers).

## Preconditions

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
