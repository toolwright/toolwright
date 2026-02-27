"""Edge case tests for reconciliation robustness.

Tests failure modes, concurrent operations, and graceful degradation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers (borrowed from test_toolpack_versioner)
# ---------------------------------------------------------------------------


def _write_toolpack_files(tp_dir: Path) -> Path:
    """Write a minimal set of toolpack files and return toolpack.yaml path."""
    tp_dir.mkdir(parents=True, exist_ok=True)
    artifact = tp_dir / "artifact"
    artifact.mkdir(exist_ok=True)
    lockfile = tp_dir / "lockfile"
    lockfile.mkdir(exist_ok=True)

    (artifact / "tools.json").write_text(
        json.dumps({"actions": [{"name": "get_users"}]})
    )
    (artifact / "toolsets.yaml").write_text(yaml.safe_dump({"toolsets": []}))
    (artifact / "policy.yaml").write_text(
        yaml.safe_dump({"version": "1.0", "rules": []})
    )
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
# 1. WatchConfig edge cases
# ===========================================================================


class TestWatchConfigEdgeCases:
    """WatchConfig.from_yaml handles missing, empty, invalid, and partial YAML."""

    def test_missing_yaml_returns_defaults(self, tmp_path: Path) -> None:
        from toolwright.models.reconcile import AutoHealPolicy, WatchConfig

        cfg = WatchConfig.from_yaml(str(tmp_path / "nonexistent.yaml"))
        assert cfg.auto_heal == AutoHealPolicy.SAFE
        assert cfg.max_concurrent_probes == 5
        assert cfg.snapshot_before_repair is True

    def test_empty_yaml_returns_defaults(self, tmp_path: Path) -> None:
        from toolwright.models.reconcile import AutoHealPolicy, WatchConfig

        empty_file = tmp_path / "empty.yaml"
        empty_file.write_text("")
        cfg = WatchConfig.from_yaml(str(empty_file))
        assert cfg.auto_heal == AutoHealPolicy.SAFE
        assert cfg.max_concurrent_probes == 5

    def test_invalid_yaml_returns_defaults(self, tmp_path: Path) -> None:
        from toolwright.models.reconcile import AutoHealPolicy, WatchConfig

        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text(":::not valid yaml:::\n  - [unbalanced")
        cfg = WatchConfig.from_yaml(str(bad_file))
        assert cfg.auto_heal == AutoHealPolicy.SAFE
        assert cfg.max_concurrent_probes == 5

    def test_partial_yaml_uses_defaults_for_missing(self, tmp_path: Path) -> None:
        from toolwright.models.reconcile import AutoHealPolicy, WatchConfig

        partial_file = tmp_path / "partial.yaml"
        partial_file.write_text("auto_heal: all\n")
        cfg = WatchConfig.from_yaml(str(partial_file))
        assert cfg.auto_heal == AutoHealPolicy.ALL
        # Other fields should have their defaults
        assert cfg.max_concurrent_probes == 5
        assert cfg.snapshot_before_repair is True
        assert cfg.unhealthy_backoff_multiplier == 2.0


# ===========================================================================
# 2. ReconcileEventLog edge cases
# ===========================================================================


class TestReconcileEventLogEdgeCases:
    """ReconcileEventLog handles missing dirs, empty logs, and unknown tools."""

    def test_record_to_nonexistent_dir_creates_it(self, tmp_path: Path) -> None:
        from toolwright.core.reconcile.event_log import ReconcileEventLog
        from toolwright.models.reconcile import EventKind, ReconcileEvent

        project_root = tmp_path / "deep" / "nested" / "project"
        log = ReconcileEventLog(str(project_root))

        event = ReconcileEvent(
            kind=EventKind.PROBE_HEALTHY,
            tool_id="tool_1",
            description="Tool is healthy",
        )
        log.record(event)

        assert log.log_path.exists()
        lines = log.log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["tool_id"] == "tool_1"

    def test_recent_with_empty_log(self, tmp_path: Path) -> None:
        from toolwright.core.reconcile.event_log import ReconcileEventLog

        log = ReconcileEventLog(str(tmp_path))
        # Log file does not exist yet
        result = log.recent()
        assert result == []

    def test_events_for_unknown_tool(self, tmp_path: Path) -> None:
        from toolwright.core.reconcile.event_log import ReconcileEventLog
        from toolwright.models.reconcile import EventKind, ReconcileEvent

        log = ReconcileEventLog(str(tmp_path))
        # Record an event for tool_a
        event = ReconcileEvent(
            kind=EventKind.DRIFT_DETECTED,
            tool_id="tool_a",
            description="Drift found",
        )
        log.record(event)

        # Query for a tool that has no events
        result = log.events_for_tool("unknown_tool")
        assert result == []


# ===========================================================================
# 3. ToolpackVersioner edge cases
# ===========================================================================


class TestToolpackVersionerEdgeCases:
    """ToolpackVersioner handles missing files, bad snapshots, and corrupt manifests."""

    def test_snapshot_with_missing_files(self, tmp_path: Path) -> None:
        """Some toolpack files don't exist -- snapshot still creates with what's there."""
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        tp_dir = tmp_path / "sparse_toolpack"
        tp_dir.mkdir(parents=True)

        # Write only toolpack.yaml referencing files that don't exist
        toolpack = {
            "version": "1.0.0",
            "toolpack_id": "tp_sparse",
            "paths": {
                "tools": "tools.json",
                "policy": "policy.yaml",
            },
        }
        (tp_dir / "toolpack.yaml").write_text(yaml.safe_dump(toolpack))
        # Only create one of the referenced files
        (tp_dir / "tools.json").write_text(json.dumps({"actions": []}))
        # policy.yaml intentionally missing

        v = ToolpackVersioner(tp_dir)
        snap_id = v.snapshot(label="sparse")

        snap_dir = tp_dir / ".toolwright" / "snapshots" / snap_id
        assert snap_dir.is_dir()
        # toolpack.yaml and tools.json should be copied
        assert (snap_dir / "toolpack.yaml").exists()
        assert (snap_dir / "tools.json").exists()
        # policy.yaml was missing, so it should not be in the snapshot
        assert not (snap_dir / "policy.yaml").exists()
        # manifest should still be created
        manifest = json.loads((snap_dir / "manifest.json").read_text())
        assert manifest["snapshot_id"] == snap_id

    def test_rollback_nonexistent_snapshot(self, tp_dir: Path) -> None:
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir)
        with pytest.raises(FileNotFoundError, match="Snapshot not found"):
            v.rollback("fake_snapshot_id_that_does_not_exist")

    def test_list_snapshots_with_corrupt_manifest(self, tp_dir: Path) -> None:
        """Invalid manifest.json in a snapshot dir is skipped gracefully."""
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        v = ToolpackVersioner(tp_dir)
        # Create a valid snapshot first
        good_id = v.snapshot(label="good")

        # Create a corrupt snapshot directory manually
        corrupt_dir = tp_dir / ".toolwright" / "snapshots" / "corrupt_snap"
        corrupt_dir.mkdir(parents=True, exist_ok=True)
        (corrupt_dir / "manifest.json").write_text("NOT VALID JSON {{{")

        snapshots = v.list_snapshots()
        # Only the good snapshot should appear
        ids = [s["snapshot_id"] for s in snapshots]
        assert good_id in ids
        assert "corrupt_snap" not in ids


# ===========================================================================
# 4. RepairApplier edge cases
# ===========================================================================


class TestRepairApplierEdgeCases:
    """RepairApplier handles empty plans, unknown actions, and OFF policy."""

    def test_empty_plan_returns_no_results(self, tmp_path: Path) -> None:
        from toolwright.core.repair.applier import ApplyResult, RepairApplier
        from toolwright.models.repair import RepairPatchPlan

        applier = RepairApplier(tmp_path)
        plan = RepairPatchPlan(
            total_patches=0,
            safe_count=0,
            approval_required_count=0,
            manual_count=0,
            patches=[],
        )
        result = applier.apply_plan(plan)
        assert isinstance(result, ApplyResult)
        assert result.total == 0
        assert result.applied_count == 0
        assert result.skipped_count == 0
        assert result.results == []

    def test_unknown_patch_action_treated_as_manual(self, tmp_path: Path) -> None:
        """A patch with an action not in SAFE or APPROVAL sets is skipped (manual)."""
        from toolwright.core.repair.applier import RepairApplier
        from toolwright.models.reconcile import AutoHealPolicy
        from toolwright.models.repair import PatchAction, PatchItem, PatchKind, RepairPatchPlan

        # INVESTIGATE is a MANUAL action -- it should be skipped even under ALL policy
        patch = PatchItem(
            id="p1",
            diagnosis_id="d1",
            kind=PatchKind.MANUAL,
            action=PatchAction.INVESTIGATE,
            cli_command="toolwright investigate",
            title="Investigate issue",
            description="Look into it",
            reason="Unknown root cause",
        )
        plan = RepairPatchPlan(
            total_patches=1,
            manual_count=1,
            patches=[patch],
        )

        applier = RepairApplier(tmp_path, auto_heal=AutoHealPolicy.ALL)
        result = applier.apply_plan(plan)
        assert result.total == 1
        assert result.applied_count == 0
        assert result.skipped_count == 1
        assert result.results[0].applied is False
        assert "manual" in result.results[0].reason.lower()

    def test_off_policy_skips_all(self, tmp_path: Path) -> None:
        from toolwright.core.repair.applier import RepairApplier
        from toolwright.models.reconcile import AutoHealPolicy
        from toolwright.models.repair import PatchAction, PatchItem, PatchKind, RepairPatchPlan

        safe_patch = PatchItem(
            id="p_safe",
            diagnosis_id="d1",
            kind=PatchKind.SAFE,
            action=PatchAction.VERIFY_CONTRACTS,
            cli_command="toolwright verify",
            title="Verify contracts",
            description="Re-verify contracts",
            reason="Ensure contracts are intact",
        )
        approval_patch = PatchItem(
            id="p_approval",
            diagnosis_id="d2",
            kind=PatchKind.APPROVAL_REQUIRED,
            action=PatchAction.GATE_ALLOW,
            cli_command="toolwright approve",
            title="Allow gate",
            description="Approve gate change",
            reason="Gate needs approval",
        )
        plan = RepairPatchPlan(
            total_patches=2,
            safe_count=1,
            approval_required_count=1,
            patches=[safe_patch, approval_patch],
        )

        applier = RepairApplier(tmp_path, auto_heal=AutoHealPolicy.OFF)
        result = applier.apply_plan(plan)
        assert result.total == 2
        assert result.applied_count == 0
        assert result.skipped_count == 2
        for pr in result.results:
            assert pr.applied is False


# ===========================================================================
# 5. DraftToolpack edge cases
# ===========================================================================


class TestDraftToolpackEdgeCases:
    """DraftToolpackCreator handles empty sessions and produces unique IDs."""

    def test_empty_session_creates_empty_actions(self, tmp_path: Path) -> None:
        from toolwright.core.discover.draft_toolpack import DraftToolpackCreator
        from toolwright.models.capture import CaptureSession, CaptureSource

        drafts_root = tmp_path / "drafts"
        creator = DraftToolpackCreator(drafts_root)

        session = CaptureSession(
            id="cap_empty",
            name="Empty",
            description=None,
            created_at=datetime.now(UTC),
            source=CaptureSource.MANUAL,
            source_file=None,
            allowed_hosts=["example.com"],
            exchanges=[],
            total_requests=0,
            filtered_requests=0,
            redacted_count=0,
            warnings=[],
        )
        draft_id = creator.create(session, label="empty-draft")

        draft_dir = drafts_root / draft_id
        assert draft_dir.is_dir()

        tools_data = json.loads((draft_dir / "tools.json").read_text())
        assert tools_data["actions"] == []

        manifest = json.loads((draft_dir / "manifest.json").read_text())
        assert manifest["action_count"] == 0
        assert manifest["session_id"] == "cap_empty"

    def test_draft_id_is_unique(self, tmp_path: Path) -> None:
        from toolwright.core.discover.draft_toolpack import DraftToolpackCreator
        from toolwright.models.capture import CaptureSession, CaptureSource

        drafts_root = tmp_path / "drafts"
        creator = DraftToolpackCreator(drafts_root)

        session = CaptureSession(
            id="cap_unique",
            name="Unique",
            created_at=datetime.now(UTC),
            source=CaptureSource.MANUAL,
            allowed_hosts=["example.com"],
            exchanges=[],
        )

        id1 = creator.create(session, label="first")
        id2 = creator.create(session, label="second")
        assert id1 != id2
