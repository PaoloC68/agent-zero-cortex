from __future__ import annotations

import functools
import logging
import sys
import time
from pathlib import Path

_CORTEX_PLUGIN_DIR = Path("/a0/usr/plugins/agent-zero-cortex")
sys.path.insert(0, str(_CORTEX_PLUGIN_DIR / "helpers"))
from dependencies import ensure_dependencies  # noqa: E402
ensure_dependencies()

import cortex_plugin.config as cortex_config
import cortex_plugin.extraction as extraction
import cortex_plugin.http as http
import cortex_plugin.prompts as prompts
from cortex_plugin.slugs import project_resolve
from helpers import projects as proj_helpers
from helpers.extension import Extension
from helpers.plugins import get_plugin_config

logger = logging.getLogger(__name__)


class CortexMemorize(Extension):

    async def execute(self, loop_data=None, **kwargs):
        try:
            cfg_dict = get_plugin_config("agent-zero-cortex", agent=self.agent) or {}
            cfg = cortex_config.load_config(cfg_dict)
            if not cfg.enabled or not cfg.api_key:
                return

            ctx = getattr(self.agent, "context", None)
            session_id = ctx.get_data("cortex_session_id") if ctx else None
            if not session_id:
                logger.warning("cortex.memorize: no cortex_session_id in context")
                return

            stored_slug = ctx.get_data("cortex_project_slug") if ctx else None
            try:
                fresh_name = proj_helpers.get_context_project_name(ctx)
                fresh_slug, _ = project_resolve(fresh_name)
            except Exception:
                fresh_slug = stored_slug

            project_slug = stored_slug
            if fresh_slug != stored_slug:
                logger.warning(
                    "cortex.memorize: project changed mid-session: %s → %s",
                    stored_slug,
                    fresh_slug,
                )
                project_slug = fresh_slug

            messages_str = self.agent.concat_messages(self.agent.history)
            frag_prompt = prompts.load_fragments_prompt()
            sol_prompt = prompts.load_solutions_prompt()

            fragments, solutions = await extraction.extract_fragments_and_solutions(
                messages_str,
                self.agent.call_utility_model,
                frag_prompt,
                sol_prompt,
                timeout_sec=cortex_config.EXTRACTION_TIMEOUT_SEC,
            )

            http_post = functools.partial(
                http.cortex_post, cfg.url, "/v1/memories", api_key=cfg.api_key
            )

            t0 = time.monotonic()
            result = await extraction.write_memories_to_cortex(
                session_id,
                project_slug,
                fragments,
                solutions,
                http_post,
                posting_timeout_sec=cortex_config.POSTING_TIMEOUT_SEC,
            )
            ms = int((time.monotonic() - t0) * 1000)

            logger.warning(
                "cortex.memorize: written=%d failed=%d timed_out=%s ms=%d",
                result["written"],
                result["failed"],
                result["timed_out"],
                ms,
            )

        except Exception as exc:
            logger.warning("cortex.memorize: unhandled exception (non-fatal): %s", exc)
