"""Unit tests for cortex_plugin.config module."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from cortex_plugin.config import (
    EXTRACTION_TIMEOUT_SEC,
    FRAGMENT_IMPORTANCE,
    HTTP_TIMEOUT_SEC,
    MAX_HISTORY_CHARS,
    POSTING_TIMEOUT_SEC,
    RECALL_CANDIDATE_FLOOR,
    RECALL_CANDIDATE_MULTIPLIER,
    RECALL_QUERY_MIN_CHARS,
    RETRY_ATTEMPTS,
    SOLUTION_IMPORTANCE,
    CortexConfig,
    load_config,
)


class TestLoadConfigDefaults:
    """Test load_config() with no env vars set."""

    def test_load_config_returns_namedtuple(self):
        """load_config() returns a CortexConfig NamedTuple."""
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config()
            assert isinstance(cfg, CortexConfig)

    def test_default_url(self):
        """Default CORTEX_URL is http://192.168.1.12:8001."""
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config()
            assert cfg.url == "http://192.168.1.12:8001"

    def test_default_api_key_empty(self):
        """Default CORTEX_API_KEY is empty string."""
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config()
            assert cfg.api_key == ""

    def test_default_enabled_true(self):
        """Default CORTEX_ENABLED is True."""
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config()
            assert cfg.enabled is True

    def test_default_recall_limit(self):
        """Default CORTEX_RECALL_LIMIT is 5."""
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config()
            assert cfg.recall_limit == 5

    def test_default_recall_threshold(self):
        """Default CORTEX_RECALL_THRESHOLD is 0.02."""
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config()
            assert cfg.recall_threshold == 0.02

    def test_default_recall_legacy_rank_false(self):
        """Default CORTEX_RECALL_LEGACY_RANK is False."""
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config()
            assert cfg.recall_legacy_rank is False

    def test_default_prompt_dir_none(self):
        """Default CORTEX_PROMPT_DIR is None."""
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config()
            assert cfg.prompt_dir is None


class TestLoadConfigEnvVars:
    """Test load_config() with env vars set."""

    def test_cortex_url_from_env(self):
        """CORTEX_URL is read from env."""
        with patch.dict(os.environ, {"CORTEX_URL": "http://custom.local:9000"}):
            cfg = load_config()
            assert cfg.url == "http://custom.local:9000"

    def test_cortex_api_key_from_env(self):
        """CORTEX_API_KEY is read from env."""
        with patch.dict(os.environ, {"CORTEX_API_KEY": "secret123"}):
            cfg = load_config()
            assert cfg.api_key == "secret123"

    def test_cortex_enabled_false_lowercase(self):
        """CORTEX_ENABLED=false (lowercase) → False."""
        with patch.dict(os.environ, {"CORTEX_ENABLED": "false"}):
            cfg = load_config()
            assert cfg.enabled is False

    def test_cortex_enabled_false_uppercase(self):
        """CORTEX_ENABLED=False (uppercase) → False."""
        with patch.dict(os.environ, {"CORTEX_ENABLED": "False"}):
            cfg = load_config()
            assert cfg.enabled is False

    def test_cortex_enabled_true_explicit(self):
        """CORTEX_ENABLED=true → True."""
        with patch.dict(os.environ, {"CORTEX_ENABLED": "true"}):
            cfg = load_config()
            assert cfg.enabled is True

    def test_cortex_enabled_arbitrary_string_is_true(self):
        """CORTEX_ENABLED=anything_else → True (lenient parsing)."""
        with patch.dict(os.environ, {"CORTEX_ENABLED": "yes"}):
            cfg = load_config()
            assert cfg.enabled is True

    def test_cortex_recall_limit_coerced_to_int(self):
        """CORTEX_RECALL_LIMIT is coerced to int."""
        with patch.dict(os.environ, {"CORTEX_RECALL_LIMIT": "10"}):
            cfg = load_config()
            assert cfg.recall_limit == 10
            assert isinstance(cfg.recall_limit, int)

    def test_cortex_recall_threshold_coerced_to_float(self):
        """CORTEX_RECALL_THRESHOLD is coerced to float."""
        with patch.dict(os.environ, {"CORTEX_RECALL_THRESHOLD": "0.5"}):
            cfg = load_config()
            assert cfg.recall_threshold == 0.5
            assert isinstance(cfg.recall_threshold, float)


class TestRecallLegacyRankParsing:
    """Test lenient bool parsing for CORTEX_RECALL_LEGACY_RANK."""

    def test_recall_legacy_rank_true_lowercase(self):
        """CORTEX_RECALL_LEGACY_RANK=true → True."""
        with patch.dict(os.environ, {"CORTEX_RECALL_LEGACY_RANK": "true"}):
            cfg = load_config()
            assert cfg.recall_legacy_rank is True

    def test_recall_legacy_rank_true_uppercase(self):
        """CORTEX_RECALL_LEGACY_RANK=True → True."""
        with patch.dict(os.environ, {"CORTEX_RECALL_LEGACY_RANK": "True"}):
            cfg = load_config()
            assert cfg.recall_legacy_rank is True

    def test_recall_legacy_rank_one(self):
        """CORTEX_RECALL_LEGACY_RANK=1 → True."""
        with patch.dict(os.environ, {"CORTEX_RECALL_LEGACY_RANK": "1"}):
            cfg = load_config()
            assert cfg.recall_legacy_rank is True

    def test_recall_legacy_rank_yes(self):
        """CORTEX_RECALL_LEGACY_RANK=yes → True."""
        with patch.dict(os.environ, {"CORTEX_RECALL_LEGACY_RANK": "yes"}):
            cfg = load_config()
            assert cfg.recall_legacy_rank is True

    def test_recall_legacy_rank_false_lowercase(self):
        """CORTEX_RECALL_LEGACY_RANK=false → False."""
        with patch.dict(os.environ, {"CORTEX_RECALL_LEGACY_RANK": "false"}):
            cfg = load_config()
            assert cfg.recall_legacy_rank is False

    def test_recall_legacy_rank_false_uppercase(self):
        """CORTEX_RECALL_LEGACY_RANK=False → False."""
        with patch.dict(os.environ, {"CORTEX_RECALL_LEGACY_RANK": "False"}):
            cfg = load_config()
            assert cfg.recall_legacy_rank is False

    def test_recall_legacy_rank_zero(self):
        """CORTEX_RECALL_LEGACY_RANK=0 → False."""
        with patch.dict(os.environ, {"CORTEX_RECALL_LEGACY_RANK": "0"}):
            cfg = load_config()
            assert cfg.recall_legacy_rank is False

    def test_recall_legacy_rank_no(self):
        """CORTEX_RECALL_LEGACY_RANK=no → False."""
        with patch.dict(os.environ, {"CORTEX_RECALL_LEGACY_RANK": "no"}):
            cfg = load_config()
            assert cfg.recall_legacy_rank is False

    def test_recall_legacy_rank_empty_string(self):
        """CORTEX_RECALL_LEGACY_RANK='' (empty) → False."""
        with patch.dict(os.environ, {"CORTEX_RECALL_LEGACY_RANK": ""}):
            cfg = load_config()
            assert cfg.recall_legacy_rank is False

    def test_recall_legacy_rank_invalid_value_no_exception(self):
        """CORTEX_RECALL_LEGACY_RANK=invalid → False (no exception)."""
        with patch.dict(os.environ, {"CORTEX_RECALL_LEGACY_RANK": "invalid"}):
            cfg = load_config()
            assert cfg.recall_legacy_rank is False

    def test_recall_legacy_rank_unset_defaults_to_false(self):
        """CORTEX_RECALL_LEGACY_RANK unset → False."""
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config()
            assert cfg.recall_legacy_rank is False


class TestPromptDir:
    """Test CORTEX_PROMPT_DIR env var."""

    def test_prompt_dir_from_env(self):
        """CORTEX_PROMPT_DIR is read from env."""
        with patch.dict(os.environ, {"CORTEX_PROMPT_DIR": "/custom/prompts"}):
            cfg = load_config()
            assert cfg.prompt_dir == "/custom/prompts"

    def test_prompt_dir_unset_is_none(self):
        """CORTEX_PROMPT_DIR unset → None."""
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config()
            assert cfg.prompt_dir is None


class TestHardcodedConstants:
    """Test that all hardcoded constants are exposed at module level."""

    def test_extraction_timeout_sec(self):
        """EXTRACTION_TIMEOUT_SEC = 5."""
        assert EXTRACTION_TIMEOUT_SEC == 5

    def test_posting_timeout_sec(self):
        """POSTING_TIMEOUT_SEC = 10."""
        assert POSTING_TIMEOUT_SEC == 10

    def test_http_timeout_sec(self):
        """HTTP_TIMEOUT_SEC = 10."""
        assert HTTP_TIMEOUT_SEC == 10

    def test_recall_candidate_multiplier(self):
        """RECALL_CANDIDATE_MULTIPLIER = 5."""
        assert RECALL_CANDIDATE_MULTIPLIER == 5

    def test_recall_candidate_floor(self):
        """RECALL_CANDIDATE_FLOOR = 30."""
        assert RECALL_CANDIDATE_FLOOR == 30

    def test_fragment_importance(self):
        """FRAGMENT_IMPORTANCE = 0.5."""
        assert FRAGMENT_IMPORTANCE == 0.5

    def test_solution_importance(self):
        """SOLUTION_IMPORTANCE = 0.7."""
        assert SOLUTION_IMPORTANCE == 0.7

    def test_retry_attempts(self):
        """RETRY_ATTEMPTS = 2."""
        assert RETRY_ATTEMPTS == 2

    def test_recall_query_min_chars(self):
        """RECALL_QUERY_MIN_CHARS = 3."""
        assert RECALL_QUERY_MIN_CHARS == 3

    def test_max_history_chars(self):
        """MAX_HISTORY_CHARS = 80000."""
        assert MAX_HISTORY_CHARS == 80000
