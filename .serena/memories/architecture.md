# Architecture — agent-zero-cortex

## Extension Load Order
AZ loads extensions by filename prefix. Built-in `_memory` plugin uses `_50_*`. This plugin uses `_60_*` to always run **after** the built-in hooks. FAISS is permanently disabled — its hooks still fire but produce no output.

```
AZ session start  → monologue_start
  _60_cortex_init.py   → POST /v1/sessions → stores cortex_session_id in agent.context

AZ message loop   → message_loop_prompts_after (each iteration)
  _60_cortex_recall.py → POST /v1/recall → fence_rerank → REPLACES extras["memories"] block

AZ session end    → monologue_end
  _60_cortex_memorize.py → call_utility_model (extract) → POST /v1/memories × N (idempotent)
```

## Session ID Flow
`_60_cortex_init.py` stores the Cortex session ID via `agent.context.set_data("cortex_session_id", ...)`.
`_60_cortex_memorize.py` and `_60_cortex_recall.py` read it via `agent.context.get_data("cortex_session_id")`.
If init failed (Cortex unreachable), session_id is None and the other extensions skip gracefully.

## Memory Extraction
`_60_cortex_memorize.py` calls `agent.call_utility_model` with vendored prompts (from `prompts/`) to independently extract fragments and solutions from the conversation history (up to 80,000 chars). It does NOT read from FAISS.

Two-tier timeout: 5 seconds for the LLM extraction phase, 10 seconds for each HTTP post to Cortex.

## Memory Areas
- `loop_data.fragments` → area `"fragments"`, importance `0.5`
- `loop_data.solutions` → area `"solutions"`, importance `0.7`

## Recall Strategy
`_60_cortex_recall.py` uses fence-strategy rerank: fetches `limit × 5` candidates (floor 30), prioritizes memories from the current project, then fills remaining slots from cross-project results.

The result **replaces** `loop_data.extras_persistent["memories"]` with a `## Cortex memories` markdown block. Full replacement, not append.

## Cortex Storage
PostgreSQL with hybrid retrieval: vector + BM25 + trigram. Scores depend on the Cortex version — see MIGRATION.md for the compatibility matrix.

## Pure-Function Library
`src/cortex_plugin/` contains zero AZ-runtime imports:
- `http.py` — async HTTP helpers (`post_memory`, `post_recall`, `post_session`)
- `keys.py` — `idempotency_key`: `sha256(session_id|area|content)`
- `prompts.py` — `load_fragments_prompt` / `load_solutions_prompt` (vendored + override)
- `recall.py` — `fence_rerank`: same-project pool first, fill from cross-project
- `slug.py` — `sanitize_slug`: project name → `[a-z0-9_-]`
