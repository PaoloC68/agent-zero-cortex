"""Tests for cortex_plugin.keys module — idempotency_key function."""
from __future__ import annotations

import hashlib
import pytest


def test_idempotency_key_returns_64_char_hex():
    """idempotency_key returns a 64-character hex string (SHA256)."""
    from cortex_plugin.keys import idempotency_key

    result = idempotency_key("ses-1", "fragments", "hello")
    assert isinstance(result, str)
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_idempotency_key_is_deterministic():
    """Same inputs always produce the same key."""
    from cortex_plugin.keys import idempotency_key

    key1 = idempotency_key("ses-1", "fragments", "hello")
    key2 = idempotency_key("ses-1", "fragments", "hello")
    assert key1 == key2


def test_idempotency_key_different_content():
    """Different content produces different key."""
    from cortex_plugin.keys import idempotency_key

    key1 = idempotency_key("ses-1", "fragments", "hello")
    key2 = idempotency_key("ses-1", "fragments", "world")
    assert key1 != key2


def test_idempotency_key_different_area():
    """Different area produces different key."""
    from cortex_plugin.keys import idempotency_key

    key1 = idempotency_key("ses-1", "fragments", "hello")
    key2 = idempotency_key("ses-1", "solutions", "hello")
    assert key1 != key2


def test_idempotency_key_different_session():
    """Different session_id produces different key."""
    from cortex_plugin.keys import idempotency_key

    key1 = idempotency_key("ses-1", "fragments", "hello")
    key2 = idempotency_key("ses-2", "fragments", "hello")
    assert key1 != key2


def test_idempotency_key_empty_content():
    """Empty content is allowed and produces valid hex string."""
    from cortex_plugin.keys import idempotency_key

    result = idempotency_key("ses-1", "fragments", "")
    assert isinstance(result, str)
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_idempotency_key_unicode_content():
    """Unicode content (€100, 日本語) is handled correctly via UTF-8 encoding."""
    from cortex_plugin.keys import idempotency_key

    # Test with Euro symbol
    key_euro = idempotency_key("ses-1", "fragments", "€100")
    assert isinstance(key_euro, str)
    assert len(key_euro) == 64

    # Test with Japanese
    key_jp = idempotency_key("ses-1", "fragments", "日本語")
    assert isinstance(key_jp, str)
    assert len(key_jp) == 64

    # Different unicode content should produce different keys
    assert key_euro != key_jp


def test_idempotency_key_matches_sha256_format():
    """Verify the key matches the expected SHA256 format: sha256(session_id|area|content).hexdigest()."""
    from cortex_plugin.keys import idempotency_key

    session_id = "ses-1"
    area = "fragments"
    content = "hello"

    # Compute expected value manually
    expected = hashlib.sha256(
        f"{session_id}|{area}|{content}".encode("utf-8")
    ).hexdigest()

    # Get actual value from function
    actual = idempotency_key(session_id, area, content)

    assert actual == expected
