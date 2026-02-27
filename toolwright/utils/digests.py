"""Deterministic digest helpers for artifact snapshots."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from toolwright.utils.canonical import canonical_json


def canonical_json_bytes(payload: Any) -> bytes:
    """Return canonical JSON bytes for a payload."""
    return canonical_json(payload).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Return sha256 hex digest for data."""
    return hashlib.sha256(data).hexdigest()


def load_artifact_payload(path: Path) -> dict[str, Any]:
    """Load a JSON or YAML artifact payload."""
    suffix = path.suffix.lower()
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle) if suffix == ".json" else yaml.safe_load(handle)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"Artifact at {path} must be a mapping/object")
    return payload


def canonical_file_digest(path: Path) -> tuple[str, int]:
    """Compute deterministic digest for a JSON/YAML artifact file."""
    payload = load_artifact_payload(path)
    data = canonical_json_bytes(payload)
    return sha256_hex(data), len(data)


def normalize_relative_path(path: Path) -> str:
    """Normalize relative paths with forward slashes."""
    return str(path.as_posix())


def build_digests_payload(files: dict[str, Path]) -> dict[str, Any]:
    """Build digests.json payload from relative paths to artifact files."""
    digest_entries: dict[str, dict[str, Any]] = {}
    for relative_path, file_path in sorted(files.items(), key=lambda item: item[0]):
        digest, size = canonical_file_digest(file_path)
        digest_entries[relative_path] = {"sha256": digest, "bytes": size}
    return {"version": "1", "files": digest_entries}


def digest_digests_payload(payload: dict[str, Any]) -> str:
    """Compute digest for digests.json payload."""
    data = canonical_json_bytes(payload)
    return sha256_hex(data)
