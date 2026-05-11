from __future__ import annotations

from typing import Any, NamedTuple

# Hardcoded constants (NOT configurable)
EXTRACTION_TIMEOUT_SEC = 30
POSTING_TIMEOUT_SEC = 60
HTTP_TIMEOUT_SEC = 10
RECALL_CANDIDATE_MULTIPLIER = 5
RECALL_CANDIDATE_FLOOR = 30
FRAGMENT_IMPORTANCE = 0.5
SOLUTION_IMPORTANCE = 0.7
RETRY_ATTEMPTS = 2
RECALL_QUERY_MIN_CHARS = 3
MAX_HISTORY_CHARS = 80000
COMPOSITE_SCORE_THRESHOLD = 0.10


class CortexConfig(NamedTuple):
    url: str
    api_key: str
    enabled: bool
    recall_limit: int
    recall_threshold: float
    recall_legacy_rank: bool
    prompt_dir: str | None


def load_config(cfg: dict[str, Any]) -> CortexConfig:
    url = str(cfg.get("cortex_url", "http://192.168.1.12:8001"))
    api_key = str(cfg.get("cortex_api_key", ""))
    enabled = bool(cfg.get("cortex_enabled", True))
    recall_limit = int(cfg.get("cortex_recall_limit", 5))  # type: ignore[arg-type]
    recall_threshold = float(cfg.get("cortex_recall_threshold", 0.01))  # type: ignore[arg-type]
    recall_legacy_rank = bool(cfg.get("cortex_recall_legacy_rank", False))
    prompt_dir_raw = cfg.get("cortex_prompt_dir")
    prompt_dir = str(prompt_dir_raw) if prompt_dir_raw else None

    return CortexConfig(
        url=url,
        api_key=api_key,
        enabled=enabled,
        recall_limit=recall_limit,
        recall_threshold=recall_threshold,
        recall_legacy_rank=recall_legacy_rank,
        prompt_dir=prompt_dir,
    )
