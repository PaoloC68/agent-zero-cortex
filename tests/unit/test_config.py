from __future__ import annotations

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
    def test_load_config_returns_namedtuple(self):
        cfg = load_config({})
        assert isinstance(cfg, CortexConfig)

    def test_default_url(self):
        cfg = load_config({})
        assert cfg.url == "http://192.168.1.12:8001"

    def test_default_api_key_empty(self):
        cfg = load_config({})
        assert cfg.api_key == ""

    def test_default_enabled_true(self):
        cfg = load_config({})
        assert cfg.enabled is True

    def test_default_recall_limit(self):
        cfg = load_config({})
        assert cfg.recall_limit == 5

    def test_default_recall_threshold(self):
        cfg = load_config({})
        assert cfg.recall_threshold == 0.02

    def test_default_recall_legacy_rank_false(self):
        cfg = load_config({})
        assert cfg.recall_legacy_rank is False

    def test_default_prompt_dir_none(self):
        cfg = load_config({})
        assert cfg.prompt_dir is None


class TestLoadConfigDictValues:
    def test_cortex_url_from_dict(self):
        cfg = load_config({"cortex_url": "http://custom.local:9000"})
        assert cfg.url == "http://custom.local:9000"

    def test_cortex_api_key_from_dict(self):
        cfg = load_config({"cortex_api_key": "secret123"})
        assert cfg.api_key == "secret123"

    def test_cortex_enabled_false(self):
        cfg = load_config({"cortex_enabled": False})
        assert cfg.enabled is False

    def test_cortex_enabled_true(self):
        cfg = load_config({"cortex_enabled": True})
        assert cfg.enabled is True

    def test_cortex_recall_limit_int(self):
        cfg = load_config({"cortex_recall_limit": 10})
        assert cfg.recall_limit == 10
        assert isinstance(cfg.recall_limit, int)

    def test_cortex_recall_threshold_float(self):
        cfg = load_config({"cortex_recall_threshold": 0.5})
        assert cfg.recall_threshold == 0.5
        assert isinstance(cfg.recall_threshold, float)

    def test_cortex_recall_legacy_rank_true(self):
        cfg = load_config({"cortex_recall_legacy_rank": True})
        assert cfg.recall_legacy_rank is True

    def test_cortex_recall_legacy_rank_false(self):
        cfg = load_config({"cortex_recall_legacy_rank": False})
        assert cfg.recall_legacy_rank is False


class TestPromptDir:
    def test_prompt_dir_from_dict(self):
        cfg = load_config({"cortex_prompt_dir": "/custom/prompts"})
        assert cfg.prompt_dir == "/custom/prompts"

    def test_prompt_dir_absent_is_none(self):
        cfg = load_config({})
        assert cfg.prompt_dir is None

    def test_prompt_dir_empty_string_is_none(self):
        cfg = load_config({"cortex_prompt_dir": ""})
        assert cfg.prompt_dir is None


class TestHardcodedConstants:
    def test_extraction_timeout_sec(self):
        assert EXTRACTION_TIMEOUT_SEC == 5

    def test_posting_timeout_sec(self):
        assert POSTING_TIMEOUT_SEC == 10

    def test_http_timeout_sec(self):
        assert HTTP_TIMEOUT_SEC == 10

    def test_recall_candidate_multiplier(self):
        assert RECALL_CANDIDATE_MULTIPLIER == 5

    def test_recall_candidate_floor(self):
        assert RECALL_CANDIDATE_FLOOR == 30

    def test_fragment_importance(self):
        assert FRAGMENT_IMPORTANCE == 0.5

    def test_solution_importance(self):
        assert SOLUTION_IMPORTANCE == 0.7

    def test_retry_attempts(self):
        assert RETRY_ATTEMPTS == 2

    def test_recall_query_min_chars(self):
        assert RECALL_QUERY_MIN_CHARS == 3

    def test_max_history_chars(self):
        assert MAX_HISTORY_CHARS == 80000
