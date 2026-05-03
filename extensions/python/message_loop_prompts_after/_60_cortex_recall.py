"""Cortex recall extension — appends Cortex memories to AZ prompt extras."""
from __future__ import annotations
import os
import logging

from helpers.extension import Extension

logger = logging.getLogger(__name__)


def _get_cortex_session_id(agent) -> str | None:
    ctx = getattr(agent, "context", None)
    if ctx is None:
        return None
    if hasattr(ctx, "get_data"):
        return ctx.get_data("cortex_session_id")
    return getattr(ctx, "_cortex_session_id", None)


class CortexRecall(Extension):

    def execute(self, loop_data=None, **kwargs):
        """Fire after FAISS recall: append Cortex memories to extras (append-only)."""
        return self._run(loop_data)

    async def _run(self, loop_data):
        import httpx

        try:
            cortex_url = os.environ.get("CORTEX_URL", "http://192.168.1.12:8001")
            cortex_api_key = os.environ.get("CORTEX_API_KEY", "")
            cortex_enabled = os.environ.get("CORTEX_ENABLED", "true").lower() == "true"
            merge_strategy = os.environ.get("CORTEX_MERGE_STRATEGY", "append")
            recall_limit = int(os.environ.get("CORTEX_RECALL_LIMIT", "5"))
            recall_threshold = float(os.environ.get("CORTEX_RECALL_THRESHOLD", "0.7"))

            if not cortex_enabled or not cortex_api_key or merge_strategy == "off":
                return

            agent = self.agent
            if agent is None or loop_data is None:
                return

            cortex_session_id = _get_cortex_session_id(agent)
            if not cortex_session_id:
                return

            query = ""
            try:
                msgs = getattr(loop_data, "messages", None) or []
                if msgs:
                    last_msg = msgs[-1]
                    query = str(getattr(last_msg, "content", "") or "")[:500]
            except Exception:
                pass

            if not query:
                return

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{cortex_url}/v1/recall",
                    json={
                        "query": query,
                        "session_id": cortex_session_id,
                        "limit": recall_limit,
                        "threshold": recall_threshold,
                    },
                    headers={"Authorization": f"Bearer {cortex_api_key}"},
                )
                resp.raise_for_status()
                results = resp.json()

            if not results:
                return

            items = "\n\n---\n\n".join(r.get("content", "") for r in results if r.get("content"))
            if not items:
                return

            cortex_block = f"\n\n## Cortex memories (additional)\n\n{items}"

            extras = getattr(loop_data, "extras_persistent", None)
            if extras is None:
                return

            existing_memories = extras.get("memories", "") or ""
            extras["memories"] = existing_memories + cortex_block

            logger.info(f"cortex_recall: appended {len(results)} memories to extras")

        except Exception as e:
            logger.warning(f"cortex_recall: failed (non-fatal): {e}")
