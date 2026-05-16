from __future__ import annotations

import logging
import time

from helpers.extension import Extension
from helpers import projects as proj_helpers
from helpers.plugins import get_plugin_config
from cortex_plugin import config as cortex_config, http, slugs, recall as recall_lib

logger = logging.getLogger(__name__)


# Visible warning banner injected into extras["memories"] when the cycle is broken.
# Surfaces in the agent's prompt so the agent will notify the user.
_WARN_BANNER = (
    "## ⚠ Cortex Memory Cycle WARNING\n\n"
    "The normal Cortex auto-recall cycle is NOT functional for this conversation.\n"
    "Reason: {reason}\n\n"
    "**Agent action required:** notify the user that Cortex memory auto-recall is broken "
    "for this context, then fall back to manual recall via the curl command from "
    "`/a0/usr/workdir/cortex-recall.promptinclude.md` before answering.\n"
)


async def _try_create_session(cfg, ctx, project_slug):
    """Self-heal: replicate what _60_cortex_init.py does at monologue_start.

    Returns the new session_id on success, None on failure.
    """
    try:
        data = await http.cortex_post(
            cfg.url,
            "/v1/sessions",
            {
                "external_session_id": ctx.id,
                "source": "az",
                "initial_topic_slug": project_slug,
            },
            cfg.api_key,
        )
        sid = data.get("id") if isinstance(data, dict) else None
        if not sid:
            return None
        ctx.set_data("cortex_session_id", sid)
        ctx.set_data("cortex_project_slug", project_slug)
        if project_slug:
            try:
                await http.cortex_post(
                    cfg.url,
                    f"/v1/sessions/{sid}/topic",
                    {"topic": project_slug, "lock": True, "create_if_missing": True},
                    cfg.api_key,
                )
            except Exception as exc:
                logger.warning("cortex.recall.selfheal: topic-lock failed: %s", exc)
        logger.warning("cortex.recall.selfheal: created session=%s project=%s", sid, project_slug)
        return sid
    except Exception as exc:
        logger.warning("cortex.recall.selfheal: session create failed: %s", exc)
        return None


class CortexRecall(Extension):

    async def execute(self, loop_data=None, **kwargs):
        cfg_dict = get_plugin_config("agent-zero-cortex", agent=self.agent) or {}
        cfg = cortex_config.load_config(cfg_dict)
        if not cfg.enabled or not cfg.api_key:
            return

        ctx = getattr(self.agent, "context", None)
        if ctx is None or loop_data is None:
            return

        extras = getattr(loop_data, "extras_persistent", None)

        # Resolve project slug early — needed for both recall and self-heal.
        project_name = None
        try:
            project_name = proj_helpers.get_context_project_name(ctx)
        except Exception as exc:
            logger.debug("cortex.recall: get_context_project_name failed: %s", exc)
        current_project_slug, _ = slugs.project_resolve(project_name)

        session_id = (
            ctx.get_data("cortex_session_id")
            if hasattr(ctx, "get_data")
            else getattr(ctx, "_cortex_session_id", None)
        )

        # SELF-HEAL: if session_id missing, try to create one (init didn't run/succeed).
        if not session_id:
            logger.warning("cortex.recall: no cortex_session_id — attempting self-heal")
            session_id = await _try_create_session(cfg, ctx, current_project_slug)
            if not session_id and extras is not None:
                extras["memories"] = _WARN_BANNER.format(
                    reason="session_id missing and self-heal session-creation also failed (Cortex unreachable or API error)"
                )
                return
            if not session_id:
                return

        msgs = getattr(loop_data, "messages", None) or []
        query = str(getattr(msgs[-1], "content", "") or "")[:500] if msgs else ""
        if len(query.strip()) < 3:
            return

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
            logger.warning(
                "cortex.recall: results=%d after_fence=%d project=%s ms=%d",
                n, n, current_project_slug or "none", ms,
            )
        except Exception as exc:
            ms = int((time.monotonic() - t0) * 1000)
            logger.warning("cortex.recall: failed (non-fatal): %s ms=%d", exc, ms)
            # Surface as visible warning so the agent informs the user.
            extras["memories"] = _WARN_BANNER.format(
                reason=f"recall API call failed after {ms}ms: {type(exc).__name__}: {exc}"
            )
