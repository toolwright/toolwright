"""Focused tests for v1 contract hardening."""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from tests.helpers import write_demo_toolpack
from toolwright.cli.main import cli
from toolwright.cli.mcp import run_mcp_serve
from toolwright.core.approval import LockfileManager


def test_cli_surfaces_core_commands() -> None:
    runner = CliRunner()
    top_help = runner.invoke(cli, ["--help"])
    assert top_help.exit_code == 0
    # Quick Start commands
    assert "create" in top_help.stdout
    assert "serve" in top_help.stdout
    assert "gate" in top_help.stdout
    assert "status" in top_help.stdout
    assert "drift" in top_help.stdout
    assert "repair" in top_help.stdout
    # Operations commands
    assert "mint" in top_help.stdout
    assert "config" in top_help.stdout
    assert "diff" in top_help.stdout
    assert "verify" in top_help.stdout


def test_default_help_hides_advanced_commands_but_help_all_shows_them() -> None:
    runner = CliRunner()

    default_help = runner.invoke(cli, ["--help"])
    assert default_help.exit_code == 0
    default_lines = default_help.stdout.splitlines()
    # Quick Start commands should be visible
    assert any(line.strip().startswith("create") for line in default_lines)
    assert any(line.strip().startswith("serve") for line in default_lines)
    assert any(line.strip().startswith("gate") for line in default_lines)
    assert any(line.strip().startswith("status") for line in default_lines)
    assert any(line.strip().startswith("drift") for line in default_lines)
    assert any(line.strip().startswith("repair") for line in default_lines)
    # Operations commands should be visible
    assert any(line.strip().startswith("mint") for line in default_lines)
    assert any(line.strip().startswith("config") for line in default_lines)
    assert any(line.strip().startswith("verify") for line in default_lines)
    # Advanced commands should be hidden
    assert not any(line.strip().startswith("compile") for line in default_lines)
    assert not any(line.strip().startswith("bundle") for line in default_lines)
    assert not any(line.strip().startswith("lint") for line in default_lines)
    assert not any(line.strip().startswith("doctor") for line in default_lines)
    assert not any(line.strip().startswith("enforce") for line in default_lines)
    assert not any(line.strip().startswith("init") for line in default_lines)
    assert not any(line.strip().startswith("demo") for line in default_lines)
    assert not any(line.strip().startswith("run") for line in default_lines)

    help_all = runner.invoke(cli, ["--help-all"])
    assert help_all.exit_code == 0
    assert "mint" in help_all.stdout
    assert "diff" in help_all.stdout
    assert "gate" in help_all.stdout
    assert "run" in help_all.stdout
    assert "drift" in help_all.stdout
    assert "verify" in help_all.stdout
    assert "serve" in help_all.stdout
    assert "capture" in help_all.stdout
    assert "compile" in help_all.stdout
    assert "doctor" in help_all.stdout
    assert "bundle" in help_all.stdout
    assert "init" in help_all.stdout
    assert "demo" in help_all.stdout


def test_diff_invokes_plan_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toolpack = write_demo_toolpack(tmp_path)
    calls: list[dict[str, object]] = []

    def _capture_run_plan(**kwargs):  # noqa: ANN003
        calls.append(kwargs)

    monkeypatch.setattr("toolwright.cli.plan.run_plan", _capture_run_plan)
    runner = CliRunner()

    diff_result = runner.invoke(cli, ["diff", "--toolpack", str(toolpack)])

    assert diff_result.exit_code == 0
    assert len(calls) == 1


def test_runtime_fails_closed_without_approved_lockfile(tmp_path: Path) -> None:
    toolpack = write_demo_toolpack(tmp_path)
    with pytest.raises(SystemExit) as exc:
        run_mcp_serve(
            tools_path=None,
            toolpack_path=str(toolpack),
            toolsets_path=None,
            toolset_name=None,
            policy_path=None,
            lockfile_path=None,
            base_url=None,
            auth_header=None,
            audit_log=None,
            dry_run=True,
            confirmation_store_path=str(tmp_path / "confirm.db"),
            allow_private_cidrs=[],
            allow_redirects=False,
            verbose=False,
            unsafe_no_lockfile=False,
        )
    assert exc.value.code == 1


def test_runtime_can_run_in_explicit_unsafe_mode(tmp_path: Path) -> None:
    toolpack = write_demo_toolpack(tmp_path)
    with patch("toolwright.mcp.server.run_mcp_server") as mock_run:
        run_mcp_serve(
            tools_path=None,
            toolpack_path=str(toolpack),
            toolsets_path=None,
            toolset_name=None,
            policy_path=None,
            lockfile_path=None,
            base_url=None,
            auth_header=None,
            audit_log=None,
            dry_run=True,
            confirmation_store_path=str(tmp_path / "confirm.db"),
            allow_private_cidrs=[],
            allow_redirects=False,
            verbose=False,
            unsafe_no_lockfile=True,
        )
    assert mock_run.call_count == 1


def test_bundle_excludes_sensitive_runtime_state(tmp_path: Path) -> None:
    toolpack_file = write_demo_toolpack(tmp_path)
    root = toolpack_file.parent
    lockfile = root / "lockfile" / "toolwright.lock.pending.yaml"
    manager = LockfileManager(lockfile)
    manager.load()
    manager.approve_all("tests")
    manager.save()

    (root / "auth").mkdir(parents=True, exist_ok=True)
    (root / "auth" / "storage_state.json").write_text('{"cookies":[]}')
    (root / ".toolwright").mkdir(parents=True, exist_ok=True)
    (root / ".toolwright" / "state").mkdir(parents=True, exist_ok=True)
    (root / ".toolwright" / "state" / "approval_signing.key").write_text("secret")
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "confirmations.db").write_text("secret")

    bundle_path = tmp_path / "bundle.zip"
    runner = CliRunner()
    snapshot = runner.invoke(
        cli,
        ["gate", "snapshot", "--lockfile", str(lockfile)],
    )
    assert snapshot.exit_code == 0

    result = runner.invoke(
        cli,
        ["bundle", "--toolpack", str(toolpack_file), "--out", str(bundle_path)],
    )
    assert result.exit_code == 0

    with zipfile.ZipFile(bundle_path, "r") as zf:
        names = set(zf.namelist())
    assert "BUNDLE_MANIFEST.json" in names
    assert "auth/storage_state.json" not in names
    assert "state/confirmations.db" not in names
    assert ".toolwright/state/approval_signing.key" not in names
