from __future__ import annotations

import logging
import sys
from pathlib import Path

_CORTEX_HELPERS = next(
    (p / "helpers" for p in Path(__file__).resolve().parents
     if (p / "helpers" / "dependencies.py").exists()),
    None,
)
if _CORTEX_HELPERS:
    sys.path.insert(0, str(_CORTEX_HELPERS))
    from dependencies import ensure_dependencies
    ensure_dependencies()

from cortex_plugin import config as cortex_config, http, slugs
from helpers.extension import Extension
from helpers import projects as proj_helpers
from helpers.plugins import get_plugin_config

logger = logging.getLogger(__name__)


class CortexInit(Extension):

    async def execute(self, **kwargs):
        try:
            cfg_dict = get_plugin_config("agent-zero-cortex", agent=self.agent) or {}
            cfg = cortex_config.load_config(cfg_dict)
            if not cfg.enabled or not cfg.api_key:
                return

            ctx = self.agent.context

            try:
                project_name = proj_helpers.get_context_project_name(ctx)
            except Exception:
                project_name = getattr(ctx, "current_project", None)

            slug, original = slugs.project_resolve(project_name)

            data = await http.cortex_post(
                cfg.url,
                "/v1/sessions",
                {
                    "external_session_id": ctx.id,
                    "source": "az",
                    "initial_topic_slug": slug,
                },
                cfg.api_key,
            )

            session_id = data.get("id")
            ctx.set_data("cortex_session_id", session_id)
            ctx.set_data("cortex_project_slug", slug)
            ctx.set_data("cortex_project_name", original)

            if slug:
                await http.cortex_post(
                    cfg.url,
                    f"/v1/sessions/{session_id}/topic",
                    {"topic": slug, "lock": True, "create_if_missing": True},
                    cfg.api_key,
                )

            logger.warning("cortex.init: session=%s project=%s", session_id, slug)

        except Exception as e:
            logger.warning("cortex.init: failed (non-fatal): %s", e)
