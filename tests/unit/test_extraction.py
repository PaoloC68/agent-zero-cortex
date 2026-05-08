from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest


def test_parse_fragments_valid_json_array():
    from cortex_plugin.extraction import parse_fragments

    result = parse_fragments('["alpha", "beta", "gamma"]')
    assert result == ["alpha", "beta", "gamma"]


def test_parse_fragments_markdown_fence():
    from cortex_plugin.extraction import parse_fragments

    raw = '```json\n["foo", "bar"]\n```'
    result = parse_fragments(raw)
    assert result == ["foo", "bar"]


def test_parse_fragments_single_string_wrapped_in_list():
    from cortex_plugin.extraction import parse_fragments

    result = parse_fragments('"just one fragment"')
    assert result == ["just one fragment"]


def test_parse_fragments_empty_array():
    from cortex_plugin.extraction import parse_fragments

    result = parse_fragments("[]")
    assert result == []


def test_parse_fragments_malformed_raises_extraction_parse_error():
    from cortex_plugin.extraction import parse_fragments, ExtractionParseError

    with pytest.raises(ExtractionParseError):
        parse_fragments("garbage!!! not json at all %%##")


def test_parse_solutions_valid():
    from cortex_plugin.extraction import parse_solutions

    raw = '[{"problem": "P1", "solution": "S1"}, {"problem": "P2", "solution": "S2"}]'
    result = parse_solutions(raw)
    assert len(result) == 2
    assert result[0] == {"problem": "P1", "solution": "S1"}
    assert result[1] == {"problem": "P2", "solution": "S2"}


def test_parse_solutions_filters_missing_keys(caplog):
    from cortex_plugin.extraction import parse_solutions

    raw = '[{"problem": "P1", "solution": "S1"}, {"problem": "only-problem"}, {"solution": "only-solution"}]'
    with caplog.at_level(logging.WARNING, logger="cortex_plugin.extraction"):
        result = parse_solutions(raw)

    assert len(result) == 1
    assert result[0] == {"problem": "P1", "solution": "S1"}
    assert caplog.text.count("dropping item") >= 2


async def test_extract_fragments_and_solutions_parallel_gather():
    from cortex_plugin.extraction import extract_fragments_and_solutions

    call_log = []

    async def mock_utility(history, prompt):
        call_log.append(prompt)
        if "fragment" in prompt:
            return '["frag1"]'
        return '[{"problem": "P", "solution": "S"}]'

    fragments, solutions = await extract_fragments_and_solutions(
        history="some history",
        utility_call=mock_utility,
        fragments_prompt="extract fragment things",
        solutions_prompt="extract solution things",
        timeout_sec=5,
    )

    assert fragments == ["frag1"]
    assert solutions == [{"problem": "P", "solution": "S"}]
    assert len(call_log) == 2


async def test_extract_asymmetric_success():
    from cortex_plugin.extraction import extract_fragments_and_solutions

    async def mock_utility(history, prompt):
        if "fragment" in prompt:
            raise RuntimeError("LLM call failed")
        return '[{"problem": "P", "solution": "S"}]'

    fragments, solutions = await extract_fragments_and_solutions(
        history="history",
        utility_call=mock_utility,
        fragments_prompt="extract fragment things",
        solutions_prompt="extract solution things",
        timeout_sec=5,
    )

    assert fragments == []
    assert solutions == [{"problem": "P", "solution": "S"}]


async def test_extract_retry_once_success():
    from cortex_plugin.extraction import extract_fragments_and_solutions

    # asyncio.gather tasks run until an actual suspension point. Simple async
    # functions with no I/O don't yield, so fragments coro completes first (both
    # attempts), then solutions coro runs. Order: malformed → valid-frags → valid-solutions.
    call_responses = iter(["!!!malformed!!!", '["retried-fragment"]', "[]"])

    async def mock_utility(history, prompt):
        return next(call_responses)

    fragments, solutions = await extract_fragments_and_solutions(
        history="history",
        utility_call=mock_utility,
        fragments_prompt="fragment prompt",
        solutions_prompt="solution prompt",
        timeout_sec=5,
    )

    assert fragments == ["retried-fragment"]
    assert solutions == []


async def test_extract_two_consecutive_failures_returns_empty(caplog):
    from cortex_plugin.extraction import extract_fragments_and_solutions

    async def mock_utility(history, prompt):
        return "not json at all !!!"

    with caplog.at_level(logging.WARNING, logger="cortex_plugin.extraction"):
        fragments, solutions = await extract_fragments_and_solutions(
            history="history",
            utility_call=mock_utility,
            fragments_prompt="fragment prompt",
            solutions_prompt="solution prompt",
            timeout_sec=5,
        )

    assert fragments == []
    assert solutions == []
    assert len(caplog.records) >= 1


async def test_solution_creates_two_memories():
    from cortex_plugin.extraction import write_memories_to_cortex

    http_post = AsyncMock(return_value={"id": "mem-1"})

    await write_memories_to_cortex(
        session_id="ses-1",
        project_slug="my-project",
        fragments=[],
        solutions=[{"problem": "P1", "solution": "S1"}],
        http_post=http_post,
        posting_timeout_sec=10,
    )

    assert http_post.call_count == 2
    body1 = http_post.call_args_list[0][0][0]
    body2 = http_post.call_args_list[1][0][0]

    assert body1["area"] == "fragments"
    assert body1["kind"] == "solution-problem"
    assert body1["content"] == "P1"
    assert "metadata" not in body1

    assert body2["area"] == "solutions"
    assert body2["kind"] == "solution-step"
    assert body2["content"] == "S1"
    assert "metadata" not in body2


async def test_no_source_project_when_projectless():
    from cortex_plugin.extraction import write_memories_to_cortex

    http_post = AsyncMock(return_value={"id": "mem-1"})

    await write_memories_to_cortex(
        session_id="ses-1",
        project_slug=None,
        fragments=["some fragment"],
        solutions=[],
        http_post=http_post,
        posting_timeout_sec=10,
    )

    assert http_post.call_count == 1
    body = http_post.call_args_list[0][0][0]
    assert "source_project" not in body


async def test_write_failure_partial_counts():
    from cortex_plugin.extraction import write_memories_to_cortex

    call_count = 0

    async def http_post_side_effect(body, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise RuntimeError("network error")
        return {"id": f"mem-{call_count}"}

    result = await write_memories_to_cortex(
        session_id="ses-1",
        project_slug="proj",
        fragments=["f1", "f2", "f3", "f4", "f5"],
        solutions=[],
        http_post=http_post_side_effect,
        posting_timeout_sec=10,
    )

    assert result["written"] == 4
    assert result["failed"] == 1
    assert result["timed_out"] is False


async def test_posting_timeout_partial():
    from cortex_plugin.extraction import write_memories_to_cortex

    http_post = AsyncMock(return_value={"id": "mem-1"})
    fragments = [f"frag-{i}" for i in range(15)]

    time_values = [0.0, 2.0, 4.0, 6.0] + [8.0] * 20

    with patch("cortex_plugin.extraction.time") as mock_time:
        mock_time.monotonic.side_effect = time_values
        result = await write_memories_to_cortex(
            session_id="ses-1",
            project_slug="proj",
            fragments=fragments,
            solutions=[],
            http_post=http_post,
            posting_timeout_sec=5,
        )

    assert result["timed_out"] is True
    assert result["written"] < 15


async def test_write_returns_timed_out_false_on_success():
    from cortex_plugin.extraction import write_memories_to_cortex

    http_post = AsyncMock(return_value={"id": "mem-1"})

    result = await write_memories_to_cortex(
        session_id="ses-1",
        project_slug="proj",
        fragments=["only one"],
        solutions=[],
        http_post=http_post,
        posting_timeout_sec=10,
    )

    assert result["timed_out"] is False
    assert result["written"] == 1
    assert result["failed"] == 0


async def test_write_with_project_slug_includes_source_project():
    from cortex_plugin.extraction import write_memories_to_cortex

    http_post = AsyncMock(return_value={"id": "mem-1"})

    await write_memories_to_cortex(
        session_id="ses-1",
        project_slug="homelab",
        fragments=["frag"],
        solutions=[],
        http_post=http_post,
        posting_timeout_sec=10,
    )

    body = http_post.call_args_list[0][0][0]
    assert body["source_project"] == "homelab"


async def test_write_idempotency_key_header_sent():
    from cortex_plugin.extraction import write_memories_to_cortex

    http_post = AsyncMock(return_value={"id": "mem-1"})

    await write_memories_to_cortex(
        session_id="ses-1",
        project_slug="proj",
        fragments=["frag"],
        solutions=[],
        http_post=http_post,
        posting_timeout_sec=10,
    )

    _, kwargs = http_post.call_args_list[0]
    assert "headers" in kwargs
    assert "Idempotency-Key" in kwargs["headers"]
    assert len(kwargs["headers"]["Idempotency-Key"]) == 64


async def test_write_fragment_has_correct_area_and_kind():
    from cortex_plugin.extraction import write_memories_to_cortex

    http_post = AsyncMock(return_value={"id": "mem-1"})

    await write_memories_to_cortex(
        session_id="ses-1",
        project_slug=None,
        fragments=["some fragment text"],
        solutions=[],
        http_post=http_post,
        posting_timeout_sec=10,
    )

    body = http_post.call_args_list[0][0][0]
    assert body["area"] == "fragments"
    assert body["kind"] == "fragment"
    assert body["content"] == "some fragment text"
