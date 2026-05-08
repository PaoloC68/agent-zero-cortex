"""Slug sanitization and project name resolution utilities."""

from __future__ import annotations

import re

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

    slug = _SLUG_PATTERN.sub("_", name.lower())
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
    if project_name is None:
        return (None, None)

    if project_name == "" or project_name == "default":
        return (None, project_name)

    slug = sanitize_slug(project_name)
    return (slug, project_name)
