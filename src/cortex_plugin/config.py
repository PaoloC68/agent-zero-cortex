"""Configuration module for Cortex plugin.

Reads environment variables and exposes hardcoded constants.
Re-reads env vars on every call — no caching.
"""
from __future__ import annotations

import os
from typing import NamedTuple

# Hardcoded constants (NOT env-configurable)
EXTRACTION_TIMEOUT_SEC = 5
POSTING_TIMEOUT_SEC = 10
HTTP_TIMEOUT_SEC = 10
RECALL_CANDIDATE_MULTIPLIER = 5
RECALL_CANDIDATE_FLOOR = 30
FRAGMENT_IMPORTANCE = 0.5
SOLUTION_IMPORTANCE = 0.7
RETRY_ATTEMPTS = 2
RECALL_QUERY_MIN_CHARS = 3
MAX_HISTORY_CHARS = 80000


class CortexConfig(NamedTuple):
    """Configuration derived from environment variables.

    Attributes:
        url: Cortex API base URL
        api_key: Bearer token for Cortex API
        enabled: Master switch to enable/disable all extensions
        recall_limit: Max memories returned per recall query
        recall_threshold: Minimum RRF score to include a memory (0–1).
            Calibration-dependent; lower = more results, less precise.
        recall_legacy_rank: Forward-compat escape hatch for ranking algorithm.
            If True, uses legacy ranking; if False, uses current algorithm.
        prompt_dir: Optional path to custom prompt templates (None = vendored)
    """

    url: str
    api_key: str
    enabled: bool
    recall_limit: int
    recall_threshold: float
    recall_legacy_rank: bool
    prompt_dir: str | None


def _parse_bool(value: str) -> bool:
    """Parse a boolean value leniently.

    Accepts: "true", "True", "1", "yes" → True
    Rejects: "false", "False", "0", "no", "", invalid → False (no exception)
    """
    return value.lower() in ("true", "1", "yes")


def load_config() -> CortexConfig:
    """Load configuration from environment variables.

    Returns:
        CortexConfig with all 7 env-derived fields.
        Re-reads env vars on every call (no caching).
    """
    url = os.environ.get("CORTEX_URL", "http://192.168.1.12:8001")
    api_key = os.environ.get("CORTEX_API_KEY", "")
    enabled_str = os.environ.get("CORTEX_ENABLED", "true")
    enabled = not (enabled_str.lower() in ("false", "0"))
    recall_limit = int(os.environ.get("CORTEX_RECALL_LIMIT", "5"))
    recall_threshold = float(os.environ.get("CORTEX_RECALL_THRESHOLD", "0.02"))
    recall_legacy_rank_str = os.environ.get("CORTEX_RECALL_LEGACY_RANK", "")
    recall_legacy_rank = _parse_bool(recall_legacy_rank_str)
    prompt_dir = os.environ.get("CORTEX_PROMPT_DIR", None)

    return CortexConfig(
        url=url,
        api_key=api_key,
        enabled=enabled,
        recall_limit=recall_limit,
        recall_threshold=recall_threshold,
        recall_legacy_rank=recall_legacy_rank,
        prompt_dir=prompt_dir,
    )
