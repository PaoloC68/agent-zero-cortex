from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

import dirtyjson

from cortex_plugin.config import FRAGMENT_IMPORTANCE, SOLUTION_IMPORTANCE, MAX_HISTORY_CHARS, RETRY_ATTEMPTS
from cortex_plugin.keys import idempotency_key

logger = logging.getLogger(__name__)
_REQUIRED_SOLUTION_KEYS = {"problem", "solution"}


class ExtractionParseError(Exception):
    pass


def _strip_markdown_fence(raw: str) -> str:
    stripped = raw.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.split("\n")
    inner_lines = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
    return "\n".join(inner_lines).strip()


def parse_fragments(raw: str) -> list[str]:
    text = _strip_markdown_fence(raw)
    try:
        parsed = dirtyjson.loads(text)
    except Exception as exc:
        raise ExtractionParseError(f"dirtyjson failed: {exc}") from exc

    if isinstance(parsed, str):
        return [parsed]
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, str)]
    raise ExtractionParseError(f"expected list or string, got {type(parsed).__name__}")


def parse_solutions(raw: str) -> list[dict[str, str]]:
    text = _strip_markdown_fence(raw)
    try:
        parsed = dirtyjson.loads(text)
    except Exception as exc:
        logger.warning("parse_solutions: dirtyjson failed: %s", exc)
        return []

    if not isinstance(parsed, list):
        parsed = [parsed]

    result = []
    for item in parsed:
        if isinstance(item, dict) and _REQUIRED_SOLUTION_KEYS.issubset(item.keys()):
            result.append({"problem": str(item["problem"]), "solution": str(item["solution"])})
        else:
            logger.warning("parse_solutions: dropping item missing required keys: %s", item)
    return result


async def _call_with_retry(
    utility_call: Callable[[str, str], Awaitable[str]],
    history: str,
    prompt: str,
    parser: Callable,
    label: str,
) -> list:
    for attempt in range(RETRY_ATTEMPTS):
        try:
            raw = await utility_call(history, prompt)
            return parser(raw)
        except ExtractionParseError as exc:
            if attempt == 1:
                logger.warning("extraction: %s failed after retry: %s", label, exc)
                return []
        except Exception as exc:
            logger.warning("extraction: %s unexpected error on attempt %d: %s", label, attempt, exc)
            return []
    return []


async def extract_fragments_and_solutions(
    history: str,
    utility_call: Callable[[str, str], Awaitable[str]],
    fragments_prompt: str,
    solutions_prompt: str,
    *,
    timeout_sec: int = 5,
) -> tuple[list[str], list[dict]]:
    if len(history) > MAX_HISTORY_CHARS:
        history = history[-MAX_HISTORY_CHARS:]

    fragments_coro = _call_with_retry(utility_call, history, fragments_prompt, parse_fragments, "fragments")
    solutions_coro = _call_with_retry(utility_call, history, solutions_prompt, parse_solutions, "solutions")

    try:
        results = await asyncio.wait_for(
            asyncio.gather(fragments_coro, solutions_coro, return_exceptions=True),
            timeout=timeout_sec,
        )
    except asyncio.TimeoutError:
        logger.warning("extraction: timed out after %ds", timeout_sec)
        return [], []

    fragments, solutions = results

    if isinstance(fragments, Exception):
        logger.warning("extraction: fragments gather error: %s", fragments)
        fragments = []
    if isinstance(solutions, Exception):
        logger.warning("extraction: solutions gather error: %s", solutions)
        solutions = []

    return fragments, solutions


def _build_memory_body(
    content: str,
    kind: str,
    area: str,
    session_id: str,
    project_slug: str | None,
    importance: float,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "content": content,
        "kind": kind,
        "area": area,
        "source_session_id": session_id,
        "importance": importance,
    }
    if project_slug is not None:
        body["source_project"] = project_slug
    return body


async def write_memories_to_cortex(
    session_id: str,
    project_slug: str | None,
    fragments: list[str],
    solutions: list[dict],
    http_post: Callable,
    *,
    posting_timeout_sec: int = 10,
) -> dict[str, Any]:
    posts: list[tuple[dict, str]] = []

    for fragment in fragments:
        body = _build_memory_body(
            content=fragment,
            kind="fragment",
            area="fragments",
            session_id=session_id,
            project_slug=project_slug,
            importance=FRAGMENT_IMPORTANCE,
        )
        posts.append((body, idempotency_key(session_id, "fragments", fragment)))

    for sol in solutions:
        problem_body = _build_memory_body(
            content=sol["problem"],
            kind="solution-problem",
            area="fragments",
            session_id=session_id,
            project_slug=project_slug,
            importance=SOLUTION_IMPORTANCE,
        )
        posts.append((problem_body, idempotency_key(session_id, "fragments", sol["problem"])))

        solution_body = _build_memory_body(
            content=sol["solution"],
            kind="solution-step",
            area="solutions",
            session_id=session_id,
            project_slug=project_slug,
            importance=SOLUTION_IMPORTANCE,
        )
        posts.append((solution_body, idempotency_key(session_id, "solutions", sol["solution"])))

    written = 0
    failed = 0
    start = time.monotonic()

    for body, ikey in posts:
        elapsed = time.monotonic() - start
        if elapsed >= posting_timeout_sec:
            return {"written": written, "failed": failed, "timed_out": True}

        try:
            await http_post(body, headers={"Idempotency-Key": ikey})
            written += 1
        except Exception as exc:
            logger.warning("write_memories_to_cortex: POST failed: %s", exc)
            failed += 1

    return {"written": written, "failed": failed, "timed_out": False}
