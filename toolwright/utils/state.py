"""Shared filesystem state path helpers."""

from __future__ import annotations

import sys
from pathlib import Path

DEFAULT_ROOT = Path(".toolwright")


def resolve_root(root: str | Path | None = None) -> Path:
    """Resolve the canonical state root path."""
    if root is None:
        return DEFAULT_ROOT
    return Path(root)


def root_path(root: str | Path | None, *parts: str) -> Path:
    """Resolve a child path within the canonical state root."""
    resolved = resolve_root(root)
    for part in parts:
        resolved = resolved / part
    return resolved


def confirmation_store_path(root: str | Path | None) -> Path:
    """Return default confirmation store path for a root."""
    return root_path(root, "state", "confirmations.db")


def runtime_lock_path(root: str | Path | None) -> Path:
    """Return default command lock path for a root."""
    return root_path(root, "state", "lock")


# Directories that Claude Desktop's macOS sandbox restricts access to.
_SANDBOXED_DIRS = ("Documents", "Desktop", "Downloads")


def warn_if_sandboxed_path(path: Path, platform: str | None = None) -> None:
    """Emit a warning if *path* is inside a macOS-sandboxed directory.

    Claude Desktop on macOS sandboxes MCP server processes. Toolpacks
    stored under ~/Documents, ~/Desktop, or ~/Downloads will fail with
    opaque permission errors at runtime.

    Args:
        path: Filesystem path to check (resolved to absolute).
        platform: Override for ``sys.platform`` (for testing on Linux CI).
    """
    if (platform or sys.platform) != "darwin":
        return

    import click

    resolved = path.resolve()
    home = Path.home()

    for dirname in _SANDBOXED_DIRS:
        sandboxed = home / dirname
        try:
            resolved.relative_to(sandboxed)
        except ValueError:
            continue
        click.echo(
            f"Warning: path is inside ~/{dirname} which is sandboxed on macOS.\n"
            "Claude Desktop cannot access files in this directory.\n"
            "Move your toolpack to a path outside ~/Documents, ~/Desktop, "
            "and ~/Downloads (e.g. ~/projects/).",
            err=True,
        )
        return
