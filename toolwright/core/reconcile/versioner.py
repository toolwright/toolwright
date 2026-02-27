"""ToolpackVersioner — snapshot/rollback for toolpack artifacts.

Creates timestamped snapshots of toolpack files (tools.json, policy,
lockfiles, toolpack.yaml) in `.toolwright/snapshots/<id>/`.
Supports rollback and pruning with safety for referenced snapshots.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

logger = logging.getLogger(__name__)

DEFAULT_MAX_SNAPSHOTS = 20


class ToolpackVersioner:
    """Manages toolpack snapshots and rollbacks.

    Snapshots are stored at:
        <toolpack_dir>/.toolwright/snapshots/<snapshot_id>/

    Each snapshot contains copies of the key toolpack files plus
    a manifest.json with metadata. Pruning respects snapshots
    referenced by pending repairs or active repair plans.
    """

    def __init__(
        self,
        toolpack_dir: Path,
        *,
        max_snapshots: int = DEFAULT_MAX_SNAPSHOTS,
    ) -> None:
        self._tp_dir = toolpack_dir
        self._max_snapshots = max_snapshots
        self._snapshots_dir = toolpack_dir / ".toolwright" / "snapshots"
        self._state_dir = toolpack_dir / ".toolwright" / "state"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot(self, label: str = "") -> str:
        """Create a snapshot of the current toolpack state.

        Returns the snapshot ID (used for rollback).
        """
        snap_id = self._make_id()
        snap_dir = self._snapshots_dir / snap_id
        snap_dir.mkdir(parents=True, exist_ok=True)

        # Copy key files
        self._copy_file("toolpack.yaml", snap_dir)
        self._copy_toolpack_artifacts(snap_dir)

        # Write manifest
        manifest = {
            "snapshot_id": snap_id,
            "label": label,
            "created_at": datetime.now(UTC).isoformat(),
        }
        (snap_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

        logger.info("Created snapshot %s (label=%s)", snap_id, label)

        # Auto-prune
        self.prune()

        return snap_id

    def rollback(self, snapshot_id: str) -> None:
        """Restore toolpack files from a snapshot."""
        snap_dir = self._snapshots_dir / snapshot_id
        if not snap_dir.is_dir():
            raise FileNotFoundError(f"Snapshot not found: {snapshot_id}")

        # Restore toolpack.yaml
        self._restore_file("toolpack.yaml", snap_dir)

        # Restore artifact files
        self._restore_toolpack_artifacts(snap_dir)

        logger.info("Rolled back to snapshot %s", snapshot_id)

    def list_snapshots(self) -> list[dict]:
        """List all snapshots, newest first."""
        if not self._snapshots_dir.exists():
            return []

        snapshots = []
        for d in self._snapshots_dir.iterdir():
            if not d.is_dir():
                continue
            manifest_path = d / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text())
                snapshots.append(manifest)
            except Exception:
                continue

        # Sort newest first
        snapshots.sort(key=lambda s: s.get("created_at", ""), reverse=True)
        return snapshots

    def prune(self) -> None:
        """Remove oldest snapshots beyond max, respecting protected ones."""
        snapshots = self.list_snapshots()
        if len(snapshots) <= self._max_snapshots:
            return

        protected = self._get_protected_snapshot_ids()

        # Snapshots are newest-first; we want to keep the newest max_snapshots
        # plus any protected ones that would otherwise be pruned.
        to_keep: set[str] = set()
        to_prune: list[str] = []

        for i, snap in enumerate(snapshots):
            sid = snap["snapshot_id"]
            if i < self._max_snapshots or sid in protected:
                to_keep.add(sid)
            else:
                to_prune.append(sid)

        for sid in to_prune:
            snap_dir = self._snapshots_dir / sid
            if snap_dir.exists():
                shutil.rmtree(snap_dir)
                logger.info("Pruned snapshot %s", sid)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_id(self) -> str:
        return datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]

    def _get_toolpack_config(self) -> dict:
        """Load toolpack.yaml to find artifact paths."""
        tp_path = self._tp_dir / "toolpack.yaml"
        if tp_path.exists():
            return yaml.safe_load(tp_path.read_text()) or {}
        return {}

    def _copy_file(self, relative: str, dest_dir: Path) -> None:
        """Copy a file from toolpack dir to snapshot dir."""
        src = self._tp_dir / relative
        if src.exists():
            shutil.copy2(src, dest_dir / src.name)

    def _copy_toolpack_artifacts(self, snap_dir: Path) -> None:
        """Copy all artifact files referenced by toolpack.yaml."""
        config = self._get_toolpack_config()
        paths = config.get("paths", {})

        # Direct artifact paths
        for key in ("tools", "toolsets", "policy", "baseline", "contracts"):
            rel = paths.get(key)
            if rel:
                src = self._tp_dir / rel
                if src.exists():
                    shutil.copy2(src, snap_dir / src.name)

        # Lockfiles
        lockfiles = paths.get("lockfiles", {})
        for _lock_key, lock_rel in lockfiles.items():
            if lock_rel:
                src = self._tp_dir / lock_rel
                if src.exists():
                    shutil.copy2(src, snap_dir / src.name)

    def _restore_file(self, relative: str, snap_dir: Path) -> None:
        """Restore a file from snapshot to its original location."""
        src = snap_dir / Path(relative).name
        if src.exists():
            dest = self._tp_dir / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    def _restore_toolpack_artifacts(self, snap_dir: Path) -> None:
        """Restore all artifact files from snapshot to their original paths."""
        config = self._get_toolpack_config()
        paths = config.get("paths", {})

        for key in ("tools", "toolsets", "policy", "baseline", "contracts"):
            rel = paths.get(key)
            if rel:
                filename = Path(rel).name
                src = snap_dir / filename
                if src.exists():
                    dest = self._tp_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)

        lockfiles = paths.get("lockfiles", {})
        for _lock_key, lock_rel in lockfiles.items():
            if lock_rel:
                filename = Path(lock_rel).name
                src = snap_dir / filename
                if src.exists():
                    dest = self._tp_dir / lock_rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)

    def _get_protected_snapshot_ids(self) -> set[str]:
        """Collect snapshot IDs that must not be pruned."""
        protected: set[str] = set()

        # 1. Check reconcile state for pending_repair references
        reconcile_path = self._state_dir / "reconcile.json"
        if reconcile_path.exists():
            try:
                state = json.loads(reconcile_path.read_text())
                for tool_state in state.get("tools", {}).values():
                    snap_ref = tool_state.get("pending_repair")
                    if snap_ref:
                        protected.add(snap_ref)
            except Exception:
                pass

        # 2. Check repair plan for snapshot_id reference
        plan_path = self._state_dir / "repair_plan.json"
        if plan_path.exists():
            try:
                plan = json.loads(plan_path.read_text())
                snap_ref = plan.get("snapshot_id")
                if snap_ref:
                    protected.add(snap_ref)
            except Exception:
                pass

        return protected
