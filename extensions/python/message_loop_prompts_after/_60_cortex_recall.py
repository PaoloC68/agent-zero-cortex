from __future__ import annotations

import logging
import time

from helpers.extension import Extension
from helpers import projects as proj_helpers
from cortex_plugin import config, http, slugs, recall as recall_lib

logger = logging.getLogger(__name__)


class CortexRecall(Extension):

    async def execute(self, loop_data=None, **kwargs):
        cfg = config.load_config()
        if not cfg.enabled or not cfg.api_key:
            return

        ctx = getattr(self.agent, "context", None)
        if ctx is None or loop_data is None:
            return

        session_id = (
            ctx.get_data("cortex_session_id")
            if hasattr(ctx, "get_data")
            else getattr(ctx, "_cortex_session_id", None)
        )
        if not session_id:
            logger.warning("cortex.recall: no cortex_session_id — skipping")
            return

        msgs = getattr(loop_data, "messages", None) or []
        query = str(getattr(msgs[-1], "content", "") or "")[:500] if msgs else ""
        if len(query.strip()) < 3:
            return

        project_name = None
        try:
            project_name = proj_helpers.get_context_project_name(ctx)
        except Exception:
            pass
        current_project_slug, _ = slugs.project_resolve(project_name)

        extras = getattr(loop_data, "extras_persistent", None)
        if extras is None:
            return

        t0 = time.monotonic()
        try:
            result = await recall_lib.recall_and_format(
                query,
                session_id,
                current_project_slug,
                http.cortex_post,
                url=cfg.url,
                api_key=cfg.api_key,
                recall_limit=cfg.recall_limit,
                threshold=cfg.recall_threshold,
                legacy_rank=cfg.recall_legacy_rank,
            )
            extras["memories"] = result
            ms = int((time.monotonic() - t0) * 1000)
            n = result.count("---") + 1 if result else 0
            logger.info(
                "cortex.recall: results=%d after_fence=%d project=%s ms=%d",
                n, n, current_project_slug or "none", ms,
            )
        except Exception as exc:
            ms = int((time.monotonic() - t0) * 1000)
            logger.warning("cortex.recall: failed (non-fatal): %s ms=%d", exc, ms)
