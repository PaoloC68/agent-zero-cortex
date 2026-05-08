"""Unit tests for cortex_plugin.slugs module."""

import pytest
from cortex_plugin.slugs import sanitize_slug, project_resolve


class TestSanitizeSlug:
    """Tests for sanitize_slug function."""

    def test_sanitize_slug_simple_lowercase(self):
        """Simple lowercase input should pass through unchanged."""
        assert sanitize_slug("homelab") == "homelab"

    def test_sanitize_slug_mixed_case_and_special_chars(self):
        """Mixed case and special characters should be lowercased and sanitized."""
        assert sanitize_slug("Foo Bar/Baz!") == "foo_bar_baz_"

    def test_sanitize_slug_truncate_to_64_chars(self):
        """Input longer than 64 chars should be truncated."""
        long_input = "a" * 100
        result = sanitize_slug(long_input)
        assert len(result) == 64
        assert result == "a" * 64

    def test_sanitize_slug_empty_string(self):
        """Empty string should return empty string."""
        assert sanitize_slug("") == ""

    def test_sanitize_slug_none_raises_type_error(self):
        """None input should raise TypeError."""
        with pytest.raises(TypeError):
            sanitize_slug(None)


class TestProjectResolve:
    """Tests for project_resolve function."""

    def test_project_resolve_none_returns_none_none(self):
        """None input should return (None, None)."""
        slug, original = project_resolve(None)
        assert slug is None
        assert original is None

    def test_project_resolve_empty_string_returns_none_empty(self):
        """Empty string should return (None, '')."""
        slug, original = project_resolve("")
        assert slug is None
        assert original == ""

    def test_project_resolve_default_sentinel_returns_none_default(self):
        """'default' sentinel should return (None, 'default')."""
        slug, original = project_resolve("default")
        assert slug is None
        assert original == "default"

    def test_project_resolve_mixed_case_project(self):
        """Mixed case project name should be slugified and original preserved."""
        slug, original = project_resolve("HomeLab")
        assert slug == "homelab"
        assert original == "HomeLab"

    def test_project_resolve_spaces_to_underscores(self):
        """Spaces should be converted to underscores."""
        slug, original = project_resolve("Foo Bar")
        assert slug == "foo_bar"
        assert original == "Foo Bar"
