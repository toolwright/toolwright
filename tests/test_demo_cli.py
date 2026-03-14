"""Tests for the `toolwright demo` command."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from toolwright.cli.main import cli


def test_demo_default_root_output_and_clean_stderr() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["demo"])

    assert result.exit_code == 0
    assert result.stderr == ""
    assert "governance in action" in result.stdout
    assert "What just happened" in result.stdout
    assert "toolwright create github" in result.stdout
    root = Path(".toolwright")
    assert root.exists()
    assert (root / "captures").exists()
    assert (root / "artifacts").exists()
    assert (root / "toolpacks").exists()


def test_demo_out_override(tmp_path: Path) -> None:
    runner = CliRunner()
    output_root = tmp_path / "demo-output"

    result = runner.invoke(cli, ["demo", "--out", str(output_root)])

    assert result.exit_code == 0
    assert result.stderr == ""
    assert "governance in action" in result.stdout
    assert output_root.exists()
