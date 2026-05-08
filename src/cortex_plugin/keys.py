"""Deterministic key generation for Cortex memory deduplication.

This module provides idempotency key generation that matches Cortex's server-side
dedup_key format, enabling safe replay of memory writes without creating duplicates.
"""
from __future__ import annotations

import hashlib


def idempotency_key(session_id: str, area: str, content: str) -> str:
    """Generate a deterministic SHA256-based idempotency key.

    Matches Cortex's server-side dedup_key format:
    sha256(source_session_id|area|content) UTF-8 encoded, returned as hexdigest.

    Args:
        session_id: The Cortex session ID (e.g., "ses-abc123")
        area: Memory area (e.g., "fragments", "solutions")
        content: The memory content (byte-exact, no normalization)

    Returns:
        64-character hex string (SHA256 hexdigest)

    Example:
        >>> key = idempotency_key("ses-1", "fragments", "hello")
        >>> len(key)
        64
        >>> all(c in "0123456789abcdef" for c in key)
        True
    """
    message = f"{session_id}|{area}|{content}"
    return hashlib.sha256(message.encode("utf-8")).hexdigest()
