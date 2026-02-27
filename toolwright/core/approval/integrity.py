"""Deterministic digest helpers for lockfile integrity checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from toolwright.utils.canonical import (
    canonical_digest,
    canonicalize,
    canonicalize_policy,
    canonicalize_tools_manifest,
    canonicalize_toolsets,
)


def _load_artifact(path: str | Path) -> dict[str, Any]:
    artifact_path = Path(path)
    if not artifact_path.exists():
        raise FileNotFoundError(f"Artifact file not found: {artifact_path}")

    suffix = artifact_path.suffix.lower()
    with open(artifact_path) as f:
        loaded = json.load(f) if suffix == ".json" else yaml.safe_load(f)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Artifact at {artifact_path} must be a mapping/object")
    return loaded


def compute_artifacts_digest(
    *,
    tools_payload: dict[str, Any] | None,
    toolsets_payload: dict[str, Any] | None,
    policy_payload: dict[str, Any] | None,
) -> str:
    """Compute canonical digest for the runtime-governed artifact set."""
    payload = {
        "tools": canonicalize_tools_manifest(tools_payload or {}),
        "toolsets": canonicalize_toolsets(toolsets_payload or {}),
        "policy": canonicalize_policy(policy_payload or {}),
    }
    return canonical_digest(payload)


def compute_artifacts_digest_from_paths(
    *,
    tools_path: str | Path,
    toolsets_path: str | Path | None = None,
    policy_path: str | Path | None = None,
) -> str:
    """Load artifacts from disk and compute canonical digest."""
    tools_payload = _load_artifact(tools_path)
    toolsets_payload = _load_artifact(toolsets_path) if toolsets_path else None
    policy_payload = _load_artifact(policy_path) if policy_path else None
    return compute_artifacts_digest(
        tools_payload=tools_payload,
        toolsets_payload=toolsets_payload,
        policy_payload=policy_payload,
    )


def compute_lockfile_digest(lockfile_payload: dict[str, Any]) -> str:
    """Compute canonical digest for lockfile payload."""
    return canonical_digest(canonicalize(lockfile_payload))
