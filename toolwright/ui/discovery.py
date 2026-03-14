"""Bounded path discovery and human-friendly labels for TUI selections.

Scans only within the Toolwright root — never walks above root or follows
symlinks outside root.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


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


def toolpack_labels(toolpacks: list[Path], *, root: Path | None = None) -> list[str]:
    """Return human-friendly labels for toolpack selectors."""
    infos = [_toolpack_identity(path) for path in toolpacks]
    name_counts = Counter(name for name, _stable_id in infos)

    labels: list[str] = []
    fallbacks: list[str] = []
    for path, (name, stable_id) in zip(toolpacks, infos, strict=False):
        label = name
        if name_counts[name] > 1:
            suffix = stable_id if stable_id and stable_id != name else path.parent.name
            if suffix and suffix != name:
                label = f"{name} [{suffix}]"
        labels.append(label)
        fallbacks.append(_relative_hint(path.parent, root=root))
    return _dedupe_labels(labels, fallbacks)


def lockfile_labels(lockfiles: list[Path], *, root: Path | None = None) -> list[str]:
    """Return human-friendly labels for lockfile selectors."""
    records: list[tuple[str, str, str]] = []
    for path in lockfiles:
        toolpack_file = _find_toolpack_file(path, root=root)
        name, stable_id = _toolpack_identity(toolpack_file)
        state = "pending" if "pending" in path.name else "approved"
        records.append((name, stable_id, state))

    label_counts = Counter((name, state) for name, _stable_id, state in records)
    labels: list[str] = []
    fallbacks: list[str] = []
    for path, (name, stable_id, state) in zip(lockfiles, records, strict=False):
        label = f"{name} {state} lockfile"
        if label_counts[(name, state)] > 1:
            if stable_id and stable_id != name:
                label = f"{name} [{stable_id}] {state} lockfile"
            else:
                label = f"{label} ({_relative_hint(path, root=root)})"
        labels.append(label)
        fallbacks.append(_relative_hint(path, root=root))
    return _dedupe_labels(labels, fallbacks)


def _dedupe_labels(labels: list[str], fallbacks: list[str]) -> list[str]:
    """Append a short fallback hint only when labels still collide."""
    counts = Counter(labels)
    result: list[str] = []
    for label, fallback in zip(labels, fallbacks, strict=False):
        if counts[label] > 1 and fallback and fallback not in label:
            result.append(f"{label} ({fallback})")
        else:
            result.append(label)
    return result


def _toolpack_identity(toolpack_file: Path | None) -> tuple[str, str]:
    """Return the best display name plus a stable identifier fallback."""
    if toolpack_file is None:
        return ("unknown", "")

    payload = _load_yaml_dict(toolpack_file)
    stable_id = _first_non_empty(
        payload.get("toolpack_id"),
        toolpack_file.parent.name,
    )
    display_name = _first_non_empty(
        payload.get("display_name"),
        _origin_name(payload),
        _host_slug_from_payload(payload),
        stable_id,
    )
    return (display_name or "unknown", stable_id or toolpack_file.parent.name)


def _load_yaml_dict(path: Path) -> dict[str, Any]:
    """Load a small YAML mapping, falling back to an empty dict on errors."""
    try:
        payload = yaml.safe_load(path.read_text()) or {}
    except OSError:
        return {}
    except yaml.YAMLError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _origin_name(payload: dict[str, Any]) -> str:
    origin = payload.get("origin")
    if isinstance(origin, dict):
        return _first_non_empty(origin.get("name"))
    return ""


def _host_slug_from_payload(payload: dict[str, Any]) -> str:
    hosts = payload.get("allowed_hosts")
    if isinstance(hosts, list):
        for host in hosts:
            if isinstance(host, str) and host.strip():
                return _host_to_slug(host.strip())

    origin = payload.get("origin")
    if isinstance(origin, dict):
        start_url = origin.get("start_url")
        if isinstance(start_url, str):
            host = urlparse(start_url).hostname
            if host:
                return _host_to_slug(host)
    return ""


def _host_to_slug(host: str) -> str:
    host = host.split(":")[0]
    parts = [part for part in host.split(".") if part]
    strip = {"api", "www", "rest", "v1", "v2", "com", "org", "net", "io", "dev", "co"}
    meaningful = [part for part in parts if part.lower() not in strip]
    if meaningful:
        return meaningful[0]
    if parts:
        return parts[0]
    return host


def _find_toolpack_file(lockfile_path: Path, *, root: Path | None = None) -> Path | None:
    """Walk upward from a lockfile until its owning toolpack is found."""
    current = lockfile_path.parent
    resolved_root = root.resolve() if root is not None else None

    for _ in range(4):
        candidate = current / "toolpack.yaml"
        if candidate.is_file():
            return candidate.resolve()
        if resolved_root is not None:
            try:
                current.resolve().relative_to(resolved_root)
            except ValueError:
                break
        if current.parent == current:
            break
        current = current.parent
    return None


def _relative_hint(path: Path, *, root: Path | None = None) -> str:
    if root is not None:
        try:
            return str(path.resolve().relative_to(root.resolve()))
        except (OSError, ValueError):
            pass
    parts = path.parts[-3:]
    return str(Path(*parts)) if parts else path.name


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return ""
