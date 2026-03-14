"""Tests for toolwright bundle command."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from click.testing import CliRunner

from tests.helpers import write_demo_toolpack
from toolwright.cli.main import cli
from toolwright.core.approval import LockfileManager


def test_bundle_contains_expected_files(tmp_path: Path) -> None:
    toolpack_file = write_demo_toolpack(tmp_path)
    lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"

    manager = LockfileManager(lockfile_path)
    manager.load()
    manager.approve_all()
    manager.save()

    runner = CliRunner()
    snapshot_result = runner.invoke(
        cli,
        ["gate", "snapshot", "--lockfile", str(lockfile_path)],
    )
    assert snapshot_result.exit_code == 0

    bundle_path = tmp_path / "bundle.zip"
    result = runner.invoke(
        cli,
        ["bundle", "--toolpack", str(toolpack_file), "--out", str(bundle_path)],
    )

    assert result.exit_code == 0
    assert result.stdout == ""
    assert bundle_path.exists()

    with zipfile.ZipFile(bundle_path, "r") as zf:
        names = zf.namelist()
    assert "toolpack.yaml" in names
    assert "plan.json" in names
    assert "plan.md" in names
    assert "client-config.json" in names
    assert "RUN.md" in names
    assert not any(name.startswith(".toolwright/reports") for name in names)


def test_bundle_client_config_has_portable_paths(tmp_path: Path) -> None:
    """Bundle client-config.json must not have absolute paths from the build machine.

    The --toolpack and --root args should be relative so bundles work
    when extracted to a different location (F-006).
    """
    toolpack_file = write_demo_toolpack(tmp_path)
    lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"

    manager = LockfileManager(lockfile_path)
    manager.load()
    manager.approve_all()
    manager.save()

    runner = CliRunner()
    runner.invoke(cli, ["gate", "snapshot", "--lockfile", str(lockfile_path)])

    bundle_path = tmp_path / "bundle.zip"
    result = runner.invoke(
        cli,
        ["bundle", "--toolpack", str(toolpack_file), "--out", str(bundle_path)],
    )
    assert result.exit_code == 0

    with zipfile.ZipFile(bundle_path, "r") as zf:
        config_text = zf.read("client-config.json").decode("utf-8")

    config = json.loads(config_text)
    servers = config.get("mcpServers", {})
    assert len(servers) >= 1

    for _name, server in servers.items():
        args = server.get("args", [])
        for arg in args:
            assert not arg.startswith("/"), (
                f"Bundle client-config.json contains absolute path: {arg}. "
                f"Paths should be relative for portability."
            )
