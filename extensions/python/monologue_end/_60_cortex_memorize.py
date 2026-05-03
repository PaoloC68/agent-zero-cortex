"""Cortex monologue_end extension — writes fragments and solutions to Cortex."""
from __future__ import annotations
import hashlib
import os
import logging
import httpx

logger = logging.getLogger(__name__)


def _get_cortex_session_id(agent) -> str | None:
    ctx = getattr(agent, "context", None)
    if ctx is None:
        return None
    if hasattr(ctx, "get_data"):
        return ctx.get_data("cortex_session_id")
    return getattr(ctx, "_cortex_session_id", None)


def _idempotency_key(session_id: str, area: str, content: str) -> str:
    return hashlib.sha256(f"{session_id}|{area}|{content}".encode()).hexdigest()


async def _post_memory(
    client: httpx.AsyncClient,
    cortex_url: str,
    cortex_api_key: str,
    cortex_session_id: str,
    content: str,
    kind: str,
    area: str,
    source_project: str,
    importance: float,
) -> None:
    idem_key = _idempotency_key(cortex_session_id, area, content)
    await client.post(
        f"{cortex_url}/v1/memories",
        json={
            "content": content,
            "kind": kind,
            "area": area,
            "source_session_id": cortex_session_id,
            "source_project": source_project,
            "importance": importance,
        },
        headers={
            "Authorization": f"Bearer {cortex_api_key}",
            "Idempotency-Key": idem_key,
        },
    )


async def execute(agent=None, loop_data=None, **kwargs):
    if agent is None:
        return

    try:
        cortex_url = os.environ.get("CORTEX_URL", "http://192.168.1.12:8001")
        cortex_api_key = os.environ.get("CORTEX_API_KEY", "")
        cortex_enabled = os.environ.get("CORTEX_ENABLED", "true").lower() == "true"

        if not cortex_enabled or not cortex_api_key:
            return

        cortex_session_id = _get_cortex_session_id(agent)
        if not cortex_session_id:
            logger.warning("cortex_memorize: no cortex_session_id in context, skipping")
            return

        source_project = "_unknown"
        try:
            ctx = getattr(agent, "context", None)
            if ctx:
                project_name = getattr(ctx, "current_project", None)
                if project_name:
                    import re
                    source_project = re.sub(r"[^a-z0-9_-]", "_", project_name.lower())[:64]
        except Exception:
            pass

        fragments: list[str] = []
        solutions: list[str] = []

        if loop_data is not None:
            extras = getattr(loop_data, "extras_persistent", {}) or {}
            raw_fragments = getattr(loop_data, "fragments", None) or extras.get("raw_fragments", [])
            raw_solutions = getattr(loop_data, "solutions", None) or extras.get("raw_solutions", [])

            if isinstance(raw_fragments, list):
                fragments = [str(f) for f in raw_fragments if f]
            if isinstance(raw_solutions, list):
                solutions = [str(s) for s in raw_solutions if s]

        if not fragments and not solutions:
            logger.info("cortex_memorize: no fragments/solutions to write")
            return

        faiss_mtime_before = None
        faiss_path = None
        try:
            faiss_assertion = os.environ.get("CORTEX_FAISS_ASSERTION_CHECK", "true").lower() == "true"
            if faiss_assertion and source_project != "_unknown":
                faiss_path = f"/opt/agent-zero/data/usr/projects/{source_project}/.a0proj/memory/index.faiss"
                if os.path.exists(faiss_path):
                    faiss_mtime_before = os.stat(faiss_path).st_mtime
        except Exception:
            pass

        async with httpx.AsyncClient(timeout=10.0) as client:
            for fragment in fragments:
                try:
                    await _post_memory(client, cortex_url, cortex_api_key, cortex_session_id,
                                       fragment, "fragment", "fragments", source_project, 0.5)
                except Exception as e:
                    logger.warning(f"cortex_memorize: fragment write failed: {e}")

            for solution in solutions:
                try:
                    await _post_memory(client, cortex_url, cortex_api_key, cortex_session_id,
                                       solution, "solution", "solutions", source_project, 0.7)
                except Exception as e:
                    logger.warning(f"cortex_memorize: solution write failed: {e}")

        if faiss_mtime_before is not None and faiss_path is not None:
            try:
                faiss_mtime_after = os.stat(faiss_path).st_mtime
                if faiss_mtime_after != faiss_mtime_before:
                    logger.error(
                        f"cortex_memorize: FAISS index mtime changed! "
                        f"before={faiss_mtime_before} after={faiss_mtime_after}"
                    )
            except Exception:
                pass

        logger.info(f"cortex_memorize: wrote {len(fragments)} fragments, {len(solutions)} solutions")

    except Exception as e:
        logger.warning(f"cortex_memorize: failed (non-fatal): {e}")
