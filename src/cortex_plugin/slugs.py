"""Slug sanitization and project name resolution utilities."""

from __future__ import annotations

import re

# Regex pattern: replace anything that's not lowercase letter, digit, underscore, or hyphen with underscore
_SLUG_PATTERN = re.compile(r"[^a-z0-9_-]")


def sanitize_slug(name: str) -> str:
    """Sanitize a name into a URL-safe slug.

    Converts to lowercase, replaces non-alphanumeric characters (except _ and -) with underscores,
    and truncates to 64 characters.

    Args:
        name: The name to sanitize.

    Returns:
        A sanitized slug string, max 64 characters.

    Raises:
        TypeError: If name is not a string.
    """
    if not isinstance(name, str):
        raise TypeError(f"Expected str, got {type(name).__name__}")

    # Lowercase and replace invalid characters
    slug = _SLUG_PATTERN.sub("_", name.lower())

    # Truncate to 64 characters
    return slug[:64]


def project_resolve(project_name: str | None) -> tuple[str | None, str | None]:
    """Resolve a project name to a slug and preserve the original.

    Sentinel values (None, empty string, "default") return (None, original).
    All other names are slugified.

    Args:
        project_name: The project name to resolve, or None.

    Returns:
        A tuple of (slug, original) where:
        - slug is the sanitized slug (or None for sentinels)
        - original is the input project_name unchanged
    """
    # Sentinel: None returns (None, None)
    if project_name is None:
        return (None, None)

    # Sentinel: empty string or "default" returns (None, original)
    if project_name == "" or project_name == "default":
        return (None, project_name)

    # Normal case: slugify and return both
    slug = sanitize_slug(project_name)
    return (slug, project_name)
