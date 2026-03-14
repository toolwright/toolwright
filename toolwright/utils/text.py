"""Text formatting utilities for user-facing output."""

from __future__ import annotations

import os
from pathlib import Path


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    """Return ``'{count} {word}'`` with correct singular/plural form.

    >>> pluralize(1, "tool")
    '1 tool'
    >>> pluralize(5, "tool")
    '5 tools'
    >>> pluralize(0, "entry", "entries")
    '0 entries'
    """
    if count == 1:
        return f"{count} {singular}"
    return f"{count} {plural or singular + 's'}"


def user_facing_path(path: Path | str) -> str:
    """Return a path string suitable for display to the user.

    Uses ``os.path.abspath`` instead of ``Path.resolve()`` so that
    symlinks are preserved.  On macOS ``/tmp`` is a symlink to
    ``/private/tmp``; resolving it confuses users who typed ``/tmp``.
    """
    return os.path.abspath(str(path))
