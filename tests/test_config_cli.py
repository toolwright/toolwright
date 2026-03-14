"""Tests for toolwright config command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tests.helpers import write_demo_toolpack
from toolwright.cli.main import cli


def test_config_outputs_snippet_to_stdout(tmp_path: Path) -> None:
    toolpack_file = write_demo_toolpack(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["config", "--toolpack", str(toolpack_file), "--format", "json"],
    )

    assert result.exit_code == 0
    # stderr may contain helpful context (target file path, restart hint)
    payload = json.loads(result.stdout)
    # _derive_server_name uses origin.start_url → "app-example-com"
    server = payload["mcpServers"]["app-example-com"]
    assert str(server["command"]).endswith(("toolwright", "toolwright"))
    assert server["args"][0] == "--root"
    assert "--toolpack" in server["args"]


def test_config_outputs_codex_toml(tmp_path: Path) -> None:
    toolpack_file = write_demo_toolpack(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["config", "--toolpack", str(toolpack_file), "--format", "codex"],
    )

    assert result.exit_code == 0
    # stderr may contain helpful context (target file path, restart hint)
    stdout = result.stdout
    assert "[mcp_servers.app-example-com]" in stdout
    assert "enabled = true" in stdout
    assert "--toolpack" in stdout
    assert str(toolpack_file.resolve()) in stdout
    assert str((toolpack_file.parent / ".toolwright").resolve()) in stdout


def test_config_outputs_codex_toml_with_name_override(tmp_path: Path) -> None:
    toolpack_file = write_demo_toolpack(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "config",
            "--toolpack",
            str(toolpack_file),
            "--format",
            "codex",
            "--name",
            "dummyjson",
        ],
    )

    assert result.exit_code == 0
    # stderr may contain helpful context (target file path, restart hint)
    assert "[mcp_servers.dummyjson]" in result.stdout


def test_config_respects_top_level_root_for_auto_resolution(tmp_path: Path) -> None:
    toolpack_file = write_demo_toolpack(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["--root", str(tmp_path), "config", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    server = payload["mcpServers"]["app-example-com"]
    assert server["args"][0] == "--root"
    assert str((toolpack_file.parent / ".toolwright").resolve()) in server["args"]
    assert str(toolpack_file.resolve()) in server["args"]
