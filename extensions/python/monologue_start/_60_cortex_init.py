"""Cortex monologue_start extension — creates a Cortex session and caches the ID."""
from __future__ import annotations
import re
import os
import httpx
import logging

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9_-]")


def _sanitize_slug(name: str) -> str:
    return _SLUG_RE.sub("_", name.lower())[:64]


async def execute(agent=None, **kwargs):
    """Fire at monologue start: create Cortex session, cache ID in agent context."""
    if agent is None:
        return

    try:
        cortex_url = os.environ.get("CORTEX_URL", "http://192.168.1.12:8001")
        cortex_api_key = os.environ.get("CORTEX_API_KEY", "")
        cortex_enabled = os.environ.get("CORTEX_ENABLED", "true").lower() == "true"

        if not cortex_enabled or not cortex_api_key:
            return

        az_session_id = str(getattr(getattr(agent, "context", None), "id", "unknown"))

        project_name = None
        try:
            ctx = getattr(agent, "context", None)
            if ctx:
                project_name = getattr(ctx, "current_project", None)
                if project_name is None:
                    # helpers.projects.get_context_project_name is the AZ canonical fallback
                    try:
                        from helpers import projects as proj_helpers
                        project_name = proj_helpers.get_context_project_name(ctx)
                    except Exception:
                        pass
        except Exception:
            pass

        sanitized_slug = _sanitize_slug(project_name) if project_name else "_unknown"

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{cortex_url}/v1/sessions",
                json={
                    "external_session_id": az_session_id,
                    "source": "az",
                    "initial_topic_slug": sanitized_slug,
                },
                headers={"Authorization": f"Bearer {cortex_api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            cortex_session_id = data.get("id")

        ctx = getattr(agent, "context", None)
        if ctx and cortex_session_id:
            if hasattr(ctx, "set_data"):
                ctx.set_data("cortex_session_id", cortex_session_id)
            else:
                setattr(ctx, "_cortex_session_id", cortex_session_id)

        logger.info(f"cortex_init: session created {cortex_session_id} for project {sanitized_slug}")

    except Exception as e:
        logger.warning(f"cortex_init: failed (non-fatal): {e}")
