# Task Completion Checklist — agent-zero-cortex

When finishing any code change:

1. **Run the test suite** to confirm nothing regressed:
   ```bash
   pytest tests/unit/ tests/wrapper/ -v
   ```
   All unit and wrapper tests should pass. Integration tests require a live Cortex API and are skipped by default.

2. **Check extension non-fatal contract**: any new extension code must catch all exceptions and log a warning rather than raising.

3. **Verify idempotency keys** are included on all `POST /v1/memories` calls: `sha256(session_id|area|content)` as `Idempotency-Key` header.

4. **No `print()` calls** — use `logging` only.

5. **No type suppressions** — no `# type: ignore`, `as Any`, or similar.

6. **If extension files changed**, deploy to LXC 500 (no AZ restart needed for extension file updates):
   ```bash
   # Copy updated extension files to AZ runtime dirs
   PLUGIN=/opt/agent-zero/data/usr/plugins/agent-zero-cortex/extensions/python
   EXT=/opt/agent-zero/data/python/extensions
   cp $PLUGIN/monologue_start/_60_cortex_init.py       $EXT/monologue_start/
   cp $PLUGIN/monologue_end/_60_cortex_memorize.py     $EXT/monologue_end/
   cp $PLUGIN/message_loop_prompts_after/_60_cortex_recall.py $EXT/message_loop_prompts_after/
   ```

7. **If new env vars added**, AZ restart IS required:
   ```bash
   docker compose -f /opt/agent-zero/docker-compose.yml up -d --force-recreate
   ```

8. **Rollback**: the `pre-cortex-primary-v1` git tag marks the last commit before the primary-backend refactor. To revert to side-by-side mode, check out that tag and redeploy.
