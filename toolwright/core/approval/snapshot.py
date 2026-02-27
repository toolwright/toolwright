"""Baseline snapshot materialization for approved toolpacks."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths
from toolwright.utils.canonical import canonical_json
from toolwright.utils.digests import build_digests_payload, digest_digests_payload
from toolwright.utils.files import atomic_write_text


@dataclass(frozen=True)
class SnapshotResult:
    """Snapshot materialization result."""

    snapshot_dir: Path
    digest: str
    created: bool


def resolve_toolpack_root(lockfile_path: Path) -> Path | None:
    """Walk upward from lockfile to find the toolpack root."""
    current = lockfile_path.parent
    for _ in range(10):
        candidate = current / "toolpack.yaml"
        if candidate.exists():
            return current
        if current.parent == current:
            return None
        current = current.parent
    return None


def load_snapshot_digest(snapshot_dir: Path) -> str:
    """Load digests.json from snapshot and compute digest."""
    digests_path = snapshot_dir / "digests.json"
    if not digests_path.exists():
        digests_path = snapshot_dir.parent / "digests.json"
    if not digests_path.exists():
        raise FileNotFoundError("digests.json not found for snapshot")
    payload = json.loads(digests_path.read_text(encoding="utf-8"))
    return digest_digests_payload(payload)


def materialize_snapshot(
    lockfile_path: Path,
    snapshot_dir: Path | None = None,
) -> SnapshotResult:
    """Materialize a baseline snapshot for the toolpack containing lockfile_path.

    Args:
        lockfile_path: Path to the lockfile.
        snapshot_dir: Override destination for snapshot artifacts. When ``None``
            (default), artifacts are written to ``.toolwright/approvals/…``.
    """
    toolpack_root = resolve_toolpack_root(lockfile_path)
    if toolpack_root is None:
        raise ValueError("toolpack.yaml not found for lockfile")

    toolpack_file = toolpack_root / "toolpack.yaml"
    toolpack = load_toolpack(toolpack_file)
    resolved = resolve_toolpack_paths(toolpack=toolpack, toolpack_path=toolpack_file)

    if not resolved.tools_path.exists():
        raise FileNotFoundError(f"Tools artifact missing: {resolved.tools_path}")
    if not resolved.toolsets_path.exists():
        raise FileNotFoundError(f"Toolsets artifact missing: {resolved.toolsets_path}")
    if not resolved.policy_path.exists():
        raise FileNotFoundError(f"Policy artifact missing: {resolved.policy_path}")
    if not resolved.baseline_path.exists():
        raise FileNotFoundError(f"Baseline artifact missing: {resolved.baseline_path}")

    artifacts: dict[str, Path] = {
        "tools.json": resolved.tools_path,
        "toolsets.yaml": resolved.toolsets_path,
        "policy.yaml": resolved.policy_path,
        "baseline.json": resolved.baseline_path,
    }
    if resolved.contract_yaml_path and resolved.contract_yaml_path.exists():
        artifacts["contract.yaml"] = resolved.contract_yaml_path
    if resolved.contract_json_path and resolved.contract_json_path.exists():
        artifacts["contract.json"] = resolved.contract_json_path

    digests_payload = build_digests_payload(artifacts)
    digest = digest_digests_payload(digests_payload)

    if snapshot_dir is not None:
        # User-provided snapshot directory — write there directly.
        dest_dir = snapshot_dir
        digests_path = dest_dir / "digests.json"
    else:
        # Default: .toolwright/approvals/<id>/artifacts
        snapshot_id = f"appr_{digest[:12]}"
        snapshot_root = toolpack_root / ".toolwright" / "approvals" / snapshot_id
        dest_dir = snapshot_root / "artifacts"
        digests_path = snapshot_root / "digests.json"

    if dest_dir.exists() and digests_path.exists():
        all_present = all((dest_dir / name).exists() for name in artifacts)
        if all_present:
            existing_payload = json.loads(digests_path.read_text(encoding="utf-8"))
            existing_digest = digest_digests_payload(existing_payload)
            if existing_digest == digest:
                return SnapshotResult(snapshot_dir=dest_dir, digest=digest, created=False)

    dest_dir.mkdir(parents=True, exist_ok=True)
    for relative_path, source_path in artifacts.items():
        target_path = dest_dir / relative_path
        shutil.copyfile(source_path, target_path)

    atomic_write_text(digests_path, canonical_json(digests_payload))
    return SnapshotResult(snapshot_dir=dest_dir, digest=digest, created=True)
