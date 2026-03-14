"""Tests for ToolpackVersioner — snapshot/rollback with pruning safety."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_toolpack_files(tp_dir: Path) -> Path:
    """Write a minimal set of toolpack files and return toolpack.yaml path."""
    tp_dir.mkdir(parents=True, exist_ok=True)
    artifact = tp_dir / "artifact"
    artifact.mkdir(exist_ok=True)
    lockfile = tp_dir / "lockfile"
    lockfile.mkdir(exist_ok=True)

    (artifact / "tools.json").write_text(json.dumps({"actions": [{"name": "get_users"}]}))
    (artifact / "toolsets.yaml").write_text(yaml.safe_dump({"toolsets": []}))
    (artifact / "policy.yaml").write_text(yaml.safe_dump({"version": "1.0", "rules": []}))
    (artifact / "baseline.json").write_text(json.dumps({"endpoints": []}))
    (lockfile / "toolwright.lock.pending.yaml").write_text(
        yaml.safe_dump({"version": "1.0.0", "tools": {}})
    )

    toolpack = {
        "version": "1.0.0",
        "toolpack_id": "tp_test",
        "paths": {
            "tools": "artifact/tools.json",
            "toolsets": "artifact/toolsets.yaml",
            "policy": "artifact/policy.yaml",
            "baseline": "artifact/baseline.json",
            "lockfiles": {"pending": "lockfile/toolwright.lock.pending.yaml"},
        },
    }
    tp_file = tp_dir / "toolpack.yaml"
    tp_file.write_text(yaml.safe_dump(toolpack, sort_keys=False))
    return tp_file


def _write_reconcile_state(state_dir: Path, pending_repairs: dict[str, str | None]) -> None:
    """Write a reconcile state with optional pending_repair references."""
    state_dir.mkdir(parents=True, exist_ok=True)
    tools = {}
    for tool_id, snap_id in pending_repairs.items():
        tools[tool_id] = {
            "tool_id": tool_id,
            "status": "unhealthy",
            "pending_repair": snap_id,
        }
    state = {"tools": tools, "reconcile_count": 1}
    (state_dir / "reconcile.json").write_text(json.dumps(state))


def _write_repair_plan_with_snapshot(state_dir: Path, snapshot_id: str) -> None:
    """Write a repair plan that references a snapshot_id."""
    state_dir.mkdir(parents=True, exist_ok=True)
    plan = {
        "generated_at": "2026-02-20T00:00:00Z",
        "snapshot_id": snapshot_id,
        "plan": {"total_patches": 1, "patches": []},
    }
    (state_dir / "repair_plan.json").write_text(json.dumps(plan))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tp_dir(tmp_path: Path) -> Path:
    """Toolpack directory with files."""
    d = tmp_path / "toolpacks" / "tp_test"
    _write_toolpack_files(d)
    return d


# ===========================================================================
# 1. Snapshot creation
# ===========================================================================


class TestSnapshot:
    """ToolpackVersioner.snapshot() creates a snapshot."""

    def test_creates_snapshot_dir(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir)
        snap_id = v.snapshot(label="test")
        snap_dir = tp_dir / ".toolwright" / "snapshots" / snap_id
        assert snap_dir.is_dir()

    def test_copies_tools_json(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir)
        snap_id = v.snapshot(label="test")
        snap_dir = tp_dir / ".toolwright" / "snapshots" / snap_id
        assert (snap_dir / "tools.json").exists()
        data = json.loads((snap_dir / "tools.json").read_text())
        assert data["actions"][0]["name"] == "get_users"

    def test_copies_policy(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir)
        snap_id = v.snapshot(label="test")
        snap_dir = tp_dir / ".toolwright" / "snapshots" / snap_id
        assert (snap_dir / "policy.yaml").exists()

    def test_copies_lockfile(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir)
        snap_id = v.snapshot(label="test")
        snap_dir = tp_dir / ".toolwright" / "snapshots" / snap_id
        assert (snap_dir / "toolwright.lock.pending.yaml").exists()

    def test_copies_toolpack_yaml(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir)
        snap_id = v.snapshot(label="test")
        snap_dir = tp_dir / ".toolwright" / "snapshots" / snap_id
        assert (snap_dir / "toolpack.yaml").exists()

    def test_creates_manifest(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir)
        snap_id = v.snapshot(label="test")
        snap_dir = tp_dir / ".toolwright" / "snapshots" / snap_id
        manifest = json.loads((snap_dir / "manifest.json").read_text())
        assert manifest["label"] == "test"
        assert "created_at" in manifest
        assert manifest["snapshot_id"] == snap_id

    def test_returns_unique_ids(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir)
        id1 = v.snapshot(label="first")
        id2 = v.snapshot(label="second")
        assert id1 != id2


# ===========================================================================
# 2. Rollback
# ===========================================================================


class TestRollback:
    """ToolpackVersioner.rollback() restores from a snapshot."""

    def test_restores_tools_json(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir)
        snap_id = v.snapshot(label="before-change")

        # Modify tools.json
        tools_path = tp_dir / "artifact" / "tools.json"
        tools_path.write_text(json.dumps({"actions": [{"name": "CHANGED"}]}))

        v.rollback(snap_id)
        restored = json.loads(tools_path.read_text())
        assert restored["actions"][0]["name"] == "get_users"

    def test_restores_policy(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir)
        snap_id = v.snapshot(label="before-change")

        policy_path = tp_dir / "artifact" / "policy.yaml"
        policy_path.write_text("CORRUPTED")

        v.rollback(snap_id)
        data = yaml.safe_load(policy_path.read_text())
        assert data["version"] == "1.0"

    def test_restores_lockfile(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir)
        snap_id = v.snapshot(label="before-change")

        lock_path = tp_dir / "lockfile" / "toolwright.lock.pending.yaml"
        lock_path.write_text("CORRUPTED")

        v.rollback(snap_id)
        data = yaml.safe_load(lock_path.read_text())
        assert data["version"] == "1.0.0"

    def test_raises_on_invalid_snapshot_id(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir)
        with pytest.raises(FileNotFoundError):
            v.rollback("nonexistent_snapshot")


# ===========================================================================
# 3. List snapshots
# ===========================================================================


class TestListSnapshots:
    """ToolpackVersioner.list_snapshots() lists available snapshots."""

    def test_empty_when_no_snapshots(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir)
        assert v.list_snapshots() == []

    def test_returns_snapshot_info(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir)
        snap_id = v.snapshot(label="my-label")
        snapshots = v.list_snapshots()
        assert len(snapshots) == 1
        assert snapshots[0]["snapshot_id"] == snap_id
        assert snapshots[0]["label"] == "my-label"

    def test_sorted_newest_first(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir)
        id1 = v.snapshot(label="first")
        id2 = v.snapshot(label="second")
        snapshots = v.list_snapshots()
        assert len(snapshots) == 2
        assert snapshots[0]["snapshot_id"] == id2
        assert snapshots[1]["snapshot_id"] == id1


# ===========================================================================
# 4. Pruning
# ===========================================================================


class TestPruning:
    """ToolpackVersioner.prune() enforces max snapshot limit."""

    def test_prunes_oldest_beyond_max(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir, max_snapshots=3)
        ids = [v.snapshot(label=f"snap-{i}") for i in range(5)]
        v.prune()
        snapshots = v.list_snapshots()
        remaining_ids = {s["snapshot_id"] for s in snapshots}
        # Newest 3 should survive
        assert ids[-1] in remaining_ids
        assert ids[-2] in remaining_ids
        assert ids[-3] in remaining_ids
        assert len(remaining_ids) == 3

    def test_no_pruning_under_max(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir, max_snapshots=20)
        for i in range(5):
            v.snapshot(label=f"snap-{i}")
        v.prune()
        assert len(v.list_snapshots()) == 5

    def test_pruning_preserves_pending_repair_snapshots(self, tp_dir: Path) -> None:
        """Snapshots referenced by pending repairs must survive pruning."""
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        # Use high max to avoid auto-pruning during creation
        v = ToolpackVersioner(tp_dir, max_snapshots=100)

        # Create 25 snapshots
        ids = [v.snapshot(label=f"snap-{i}") for i in range(25)]

        # Mark 2 old snapshots as referenced by pending repairs
        protected_1 = ids[2]   # 3rd oldest
        protected_2 = ids[5]   # 6th oldest

        state_dir = tp_dir / ".toolwright" / "state"
        _write_reconcile_state(state_dir, {
            "tool_a": protected_1,
            "tool_b": protected_2,
        })

        # Now lower max and prune explicitly
        v._max_snapshots = 20
        v.prune()
        snapshots = v.list_snapshots()
        remaining_ids = {s["snapshot_id"] for s in snapshots}

        # Protected snapshots must survive even though they're among the oldest
        assert protected_1 in remaining_ids
        assert protected_2 in remaining_ids
        # Total may exceed max_snapshots due to exemptions
        assert len(remaining_ids) >= 20

    def test_pruning_preserves_repair_plan_snapshot(self, tp_dir: Path) -> None:
        """Snapshot referenced in active repair plan must survive pruning."""
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        # Use high max to avoid auto-pruning during creation
        v = ToolpackVersioner(tp_dir, max_snapshots=100)

        ids = [v.snapshot(label=f"snap-{i}") for i in range(5)]
        protected = ids[0]  # oldest

        state_dir = tp_dir / ".toolwright" / "state"
        _write_repair_plan_with_snapshot(state_dir, protected)

        # Now lower max and prune explicitly
        v._max_snapshots = 3
        v.prune()
        snapshots = v.list_snapshots()
        remaining_ids = {s["snapshot_id"] for s in snapshots}

        assert protected in remaining_ids

    def test_pruning_actually_deletes_directories(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir, max_snapshots=2)
        ids = [v.snapshot(label=f"snap-{i}") for i in range(4)]
        v.prune()

        # Oldest 2 should be gone from disk
        snaps_dir = tp_dir / ".toolwright" / "snapshots"
        assert not (snaps_dir / ids[0]).exists()
        assert not (snaps_dir / ids[1]).exists()
        # Newest 2 still present
        assert (snaps_dir / ids[2]).exists()
        assert (snaps_dir / ids[3]).exists()


# ===========================================================================
# 5. Snapshot auto-prunes on creation
# ===========================================================================


class TestAutoprune:
    """snapshot() auto-prunes when over limit."""

    def test_snapshot_auto_prunes(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir, max_snapshots=3)
        for i in range(5):
            v.snapshot(label=f"snap-{i}")
        # After auto-pruning, should have max_snapshots
        assert len(v.list_snapshots()) <= 3
