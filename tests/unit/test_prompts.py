"""Tests for cortex_plugin.prompts module."""
from __future__ import annotations

import os

from cortex_plugin.prompts import (
    load_fragments_prompt,
    load_solutions_prompt,
    _clear_cache_for_tests,
)


class TestLoadFragmentsPrompt:
    """Test load_fragments_prompt() function."""

    def test_returns_string_starting_with_assistants_job(self):
        """load_fragments_prompt() returns string starting with '# Assistant's job'."""
        _clear_cache_for_tests()
        result = load_fragments_prompt()
        assert isinstance(result, str)
        assert result.startswith("# Assistant's job")

    def test_returns_cached_same_object_on_second_call(self):
        """load_fragments_prompt() returns same object (cached) on second call."""
        _clear_cache_for_tests()
        first = load_fragments_prompt()
        second = load_fragments_prompt()
        assert id(first) == id(second), "Expected cached object (same id)"

    def test_override_with_cortex_prompt_dir(self, tmp_path):
        """When CORTEX_PROMPT_DIR set and file exists, returns override content."""
        _clear_cache_for_tests()
        override_dir = tmp_path / "prompts"
        override_dir.mkdir()
        override_file = override_dir / "memory.memories_sum.sys.md"
        override_file.write_text("OVERRIDE_FRAGMENTS", encoding="utf-8")

        old_env = os.environ.get("CORTEX_PROMPT_DIR")
        try:
            os.environ["CORTEX_PROMPT_DIR"] = str(override_dir)
            _clear_cache_for_tests()
            result = load_fragments_prompt()
            assert result == "OVERRIDE_FRAGMENTS"
        finally:
            if old_env is None:
                os.environ.pop("CORTEX_PROMPT_DIR", None)
            else:
                os.environ["CORTEX_PROMPT_DIR"] = old_env

    def test_fallback_to_vendored_when_override_missing(self, tmp_path):
        """When override dir doesn't have file, falls back to vendored."""
        _clear_cache_for_tests()
        override_dir = tmp_path / "prompts"
        override_dir.mkdir()

        old_env = os.environ.get("CORTEX_PROMPT_DIR")
        try:
            os.environ["CORTEX_PROMPT_DIR"] = str(override_dir)
            _clear_cache_for_tests()
            result = load_fragments_prompt()
            assert result.startswith("# Assistant's job")
        finally:
            if old_env is None:
                os.environ.pop("CORTEX_PROMPT_DIR", None)
            else:
                os.environ["CORTEX_PROMPT_DIR"] = old_env

    def test_fallback_when_override_path_invalid(self):
        """When override path is invalid/unreadable, falls back to vendored and logs warning."""
        _clear_cache_for_tests()
        old_env = os.environ.get("CORTEX_PROMPT_DIR")
        try:
            os.environ["CORTEX_PROMPT_DIR"] = "/nonexistent/path/that/does/not/exist"
            _clear_cache_for_tests()
            result = load_fragments_prompt()
            assert result.startswith("# Assistant's job")
        finally:
            if old_env is None:
                os.environ.pop("CORTEX_PROMPT_DIR", None)
            else:
                os.environ["CORTEX_PROMPT_DIR"] = old_env


class TestLoadSolutionsPrompt:
    """Test load_solutions_prompt() function."""

    def test_returns_string_mentioning_successful_technical_solutions(self):
        """load_solutions_prompt() returns string mentioning 'successful technical solutions'."""
        _clear_cache_for_tests()
        result = load_solutions_prompt()
        assert isinstance(result, str)
        assert "successful technical solutions" in result.lower() or "successful solutions" in result.lower()

    def test_returns_cached_same_object_on_second_call(self):
        """load_solutions_prompt() returns same object (cached) on second call."""
        _clear_cache_for_tests()
        first = load_solutions_prompt()
        second = load_solutions_prompt()
        assert id(first) == id(second), "Expected cached object (same id)"
