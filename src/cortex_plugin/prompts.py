"""Load vendored prompt files with optional override hook."""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_FRAGMENT_PROMPT_FILE = "memory.memories_sum.sys.md"
_SOLUTION_PROMPT_FILE = "memory.solutions_sum.sys.md"

_cache: dict[tuple[str, str], str] = {}


def load_fragments_prompt() -> str:
    """Load the fragments prompt from vendored or override location.
    
    Returns the content of memory.memories_sum.sys.md.
    Checks CORTEX_PROMPT_DIR env var first, falls back to vendored.
    Results are cached by (CORTEX_PROMPT_DIR, filename) tuple.
    """
    return _load_prompt(_FRAGMENT_PROMPT_FILE)


def load_solutions_prompt() -> str:
    """Load the solutions prompt from vendored or override location.
    
    Returns the content of memory.solutions_sum.sys.md.
    Checks CORTEX_PROMPT_DIR env var first, falls back to vendored.
    Results are cached by (CORTEX_PROMPT_DIR, filename) tuple.
    """
    return _load_prompt(_SOLUTION_PROMPT_FILE)


def _load_prompt(filename: str) -> str:
    """Load a prompt file with override and caching logic.
    
    Args:
        filename: Name of the prompt file (e.g., "memory.memories_sum.sys.md")
    
    Returns:
        Content of the prompt file as a string.
    """
    override_dir = os.environ.get("CORTEX_PROMPT_DIR", "")
    cache_key = (override_dir, filename)
    
    if cache_key in _cache:
        return _cache[cache_key]
    
    content = None
    
    if override_dir:
        try:
            override_path = Path(override_dir) / filename
            content = override_path.read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError, PermissionError, OSError) as e:
            logger.warning(
                "Failed to read override prompt %s/%s: %s. Falling back to vendored prompt.",
                override_dir, filename, e
            )
    
    if content is None:
        vendored_path = Path(__file__).parent.parent.parent / "prompts" / filename
        content = vendored_path.read_text(encoding="utf-8")
    
    _cache[cache_key] = content
    return content


def _clear_cache_for_tests() -> None:
    """Clear the prompt cache. For testing only."""
    _cache.clear()
