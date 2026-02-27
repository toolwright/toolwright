"""Bounded path discovery for toolpacks and lockfiles.

Scans only within the Toolwright root — never walks above root or follows
symlinks outside root.
"""

from __future__ import annotations

from pathlib import Path


def find_toolpacks(root: Path) -> list[Path]:
    """Find toolpack.yaml files under ``root/toolpacks/`` (1 level deep).

    Returns absolute paths sorted by name.
    """
    toolpacks_dir = root / "toolpacks"
    if not toolpacks_dir.is_dir():
        return []

    results: list[Path] = []
    for child in sorted(toolpacks_dir.iterdir()):
        if not child.is_dir():
            continue
        candidate = child / "toolpack.yaml"
        if candidate.is_file():
            results.append(candidate.resolve())
    return results


def find_lockfiles(root: Path) -> list[Path]:
    """Find toolwright.lock*.yaml files within *root* (max depth 3).

    Returns absolute paths sorted by name.  Never walks above root.
    """
    results: list[Path] = []
    _scan_lockfiles(root, results, depth=0, max_depth=3)
    return sorted(results)


def _scan_lockfiles(
    directory: Path,
    results: list[Path],
    depth: int,
    max_depth: int,
) -> None:
    """Recursive bounded scan for lockfiles."""
    if depth > max_depth:
        return
    if not directory.is_dir():
        return

    try:
        entries = list(directory.iterdir())
    except PermissionError:
        return

    for entry in entries:
        if entry.is_file() and entry.name.startswith("toolwright.lock") and entry.name.endswith(".yaml"):
            results.append(entry.resolve())
        elif entry.is_dir() and not entry.is_symlink():
            _scan_lockfiles(entry, results, depth + 1, max_depth)
