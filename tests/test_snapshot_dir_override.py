"""Tests for --snapshot-dir override on gate snapshot."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from toolwright.cli.main import cli
from toolwright.core.approval import LockfileManager
from tests.helpers import load_yaml, write_demo_toolpack


class TestMaterializeSnapshotOverride:
    """materialize_snapshot() with snapshot_dir parameter."""

    def test_custom_snapshot_dir_writes_to_specified_location(self, tmp_path: Path) -> None:
        """When snapshot_dir is provided, artifacts land there instead of .toolwright/."""
        toolpack_file = write_demo_toolpack(tmp_path)
        lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"

        # Approve first so snapshot can proceed
        runner = CliRunner()
        runner.invoke(cli, ["gate", "allow", "--all", "--lockfile", str(lockfile_path)])

        from toolwright.core.approval.snapshot import materialize_snapshot

        custom_dir = toolpack_file.parent / "my_snapshot"
        result = materialize_snapshot(lockfile_path, snapshot_dir=custom_dir)

        assert result.snapshot_dir == custom_dir
        assert custom_dir.exists()
        assert (custom_dir / "tools.json").exists()
        assert (custom_dir / "policy.yaml").exists()
        assert (custom_dir / "toolsets.yaml").exists()
        assert (custom_dir / "baseline.json").exists()

    def test_default_snapshot_dir_unchanged(self, tmp_path: Path) -> None:
        """Without snapshot_dir, behavior is unchanged (.toolwright/ default)."""
        toolpack_file = write_demo_toolpack(tmp_path)
        lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"

        runner = CliRunner()
        runner.invoke(cli, ["gate", "allow", "--all", "--lockfile", str(lockfile_path)])

        from toolwright.core.approval.snapshot import materialize_snapshot

        result = materialize_snapshot(lockfile_path)
        assert ".toolwright" in str(result.snapshot_dir)

    def test_custom_dir_digests_json_written(self, tmp_path: Path) -> None:
        """digests.json is written alongside the custom snapshot dir."""
        toolpack_file = write_demo_toolpack(tmp_path)
        lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"

        runner = CliRunner()
        runner.invoke(cli, ["gate", "allow", "--all", "--lockfile", str(lockfile_path)])

        from toolwright.core.approval.snapshot import materialize_snapshot

        custom_dir = toolpack_file.parent / "snapshot"
        result = materialize_snapshot(lockfile_path, snapshot_dir=custom_dir)

        # digests.json should be in parent of snapshot_dir or in snapshot_dir
        digests_in_parent = custom_dir.parent / "digests.json"
        digests_in_dir = custom_dir / "digests.json"
        assert digests_in_parent.exists() or digests_in_dir.exists()
        assert result.digest  # non-empty digest


class TestGateSnapshotCLIOverride:
    """gate snapshot --snapshot-dir CLI option."""

    def test_snapshot_dir_flag_accepted(self, tmp_path: Path) -> None:
        """gate snapshot --snapshot-dir <path> is a valid CLI option."""
        toolpack_file = write_demo_toolpack(tmp_path)
        lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"

        runner = CliRunner()
        runner.invoke(cli, ["gate", "allow", "--all", "--lockfile", str(lockfile_path)])

        approved_lockfile = toolpack_file.parent / "lockfile" / "toolwright.lock.yaml"
        custom_dir = toolpack_file.parent / "snapshot"

        result = runner.invoke(
            cli,
            ["gate", "snapshot", "--lockfile", str(approved_lockfile), "--snapshot-dir", str(custom_dir)],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"

    def test_snapshot_dir_persisted_in_lockfile(self, tmp_path: Path) -> None:
        """--snapshot-dir stores the relative path in baseline_snapshot_dir."""
        toolpack_file = write_demo_toolpack(tmp_path)
        lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"

        runner = CliRunner()
        runner.invoke(cli, ["gate", "allow", "--all", "--lockfile", str(lockfile_path)])

        approved_lockfile = toolpack_file.parent / "lockfile" / "toolwright.lock.yaml"
        custom_dir = toolpack_file.parent / "snapshot"

        runner.invoke(
            cli,
            ["gate", "snapshot", "--lockfile", str(approved_lockfile), "--snapshot-dir", str(custom_dir)],
        )

        lockfile = load_yaml(approved_lockfile)
        snapshot_dir_value = lockfile.get("baseline_snapshot_dir", "")
        # Should be a relative path NOT containing .toolwright
        assert ".toolwright" not in snapshot_dir_value
        assert "snapshot" in snapshot_dir_value


class TestGateSyncPreservesSnapshotDir:
    """gate sync does not overwrite user-set baseline_snapshot_dir."""

    def test_sync_preserves_custom_snapshot_dir(self, tmp_path: Path) -> None:
        """After setting a custom snapshot dir, gate sync keeps it."""
        toolpack_file = write_demo_toolpack(tmp_path)
        lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"

        runner = CliRunner()
        runner.invoke(cli, ["gate", "allow", "--all", "--lockfile", str(lockfile_path)])

        approved_lockfile = toolpack_file.parent / "lockfile" / "toolwright.lock.yaml"

        # Set a custom snapshot dir
        manager = LockfileManager(approved_lockfile)
        manager.load()
        manager.set_baseline_snapshot("snapshot", manager.lockfile.baseline_snapshot_digest)
        manager.save()

        # Run gate sync
        artifacts = toolpack_file.parent / "artifact"
        result = runner.invoke(
            cli,
            [
                "gate", "sync",
                "--tools", str(artifacts / "tools.json"),
                "--policy", str(artifacts / "policy.yaml"),
                "--lockfile", str(approved_lockfile),
            ],
        )
        assert result.exit_code == 0, f"sync failed: {result.output}"

        # Verify baseline_snapshot_dir is preserved
        lockfile = load_yaml(approved_lockfile)
        assert lockfile.get("baseline_snapshot_dir") == "snapshot"


class TestCheckCIWithCustomSnapshotDir:
    """gate check resolves custom snapshot dir correctly."""

    def test_check_passes_with_custom_snapshot_dir(self, tmp_path: Path) -> None:
        """gate check succeeds when baseline_snapshot_dir points to a non-.toolwright path."""
        toolpack_file = write_demo_toolpack(tmp_path)
        lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"

        runner = CliRunner()
        runner.invoke(cli, ["gate", "allow", "--all", "--lockfile", str(lockfile_path)])

        approved_lockfile = toolpack_file.parent / "lockfile" / "toolwright.lock.yaml"
        custom_dir = toolpack_file.parent / "snapshot"

        # Use --snapshot-dir to set up properly
        runner.invoke(
            cli,
            ["gate", "snapshot", "--lockfile", str(approved_lockfile), "--snapshot-dir", str(custom_dir)],
        )

        # Verify gate check passes
        result = runner.invoke(
            cli,
            ["gate", "check", "--lockfile", str(approved_lockfile)],
        )
        assert result.exit_code == 0, f"gate check failed: {result.output}"


class TestGitignoreWarning:
    """gate snapshot warns when snapshot dir is gitignored."""

    def test_warns_when_snapshot_dir_gitignored(self, tmp_path: Path) -> None:
        """Warning is emitted when the snapshot dir resolves to a gitignored path."""
        toolpack_file = write_demo_toolpack(tmp_path)
        lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"

        runner = CliRunner()
        runner.invoke(cli, ["gate", "allow", "--all", "--lockfile", str(lockfile_path)])

        approved_lockfile = toolpack_file.parent / "lockfile" / "toolwright.lock.yaml"

        # Mock git check-ignore to return exit code 0 (path IS ignored)
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            result = runner.invoke(
                cli,
                ["gate", "snapshot", "--lockfile", str(approved_lockfile)],
            )

        assert "gitignored" in result.output.lower() or "git" in result.output.lower()

    def test_no_warning_when_not_gitignored(self, tmp_path: Path) -> None:
        """No warning when snapshot dir is NOT gitignored."""
        toolpack_file = write_demo_toolpack(tmp_path)
        lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"

        runner = CliRunner()
        runner.invoke(cli, ["gate", "allow", "--all", "--lockfile", str(lockfile_path)])

        approved_lockfile = toolpack_file.parent / "lockfile" / "toolwright.lock.yaml"
        custom_dir = toolpack_file.parent / "snapshot"

        # Mock git check-ignore to return exit code 1 (path NOT ignored)
        mock_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            result = runner.invoke(
                cli,
                ["gate", "snapshot", "--lockfile", str(approved_lockfile), "--snapshot-dir", str(custom_dir)],
            )

        assert "gitignored" not in result.output.lower()
