"""Tests for demo command output format and content."""

from __future__ import annotations

from click.testing import CliRunner

from toolwright.cli.main import cli


def test_demo_output_contains_tool_count() -> None:
    """Demo output includes tool count in the compile step."""
    runner = CliRunner()
    result = runner.invoke(cli, ["demo"])

    assert result.exit_code == 0
    assert "8 tools" in result.stdout


def test_demo_output_contains_governance_steps() -> None:
    """Demo output shows governance enforcement steps."""
    runner = CliRunner()
    result = runner.invoke(cli, ["demo"])

    assert result.exit_code == 0
    assert "Blocking unapproved tool" in result.stdout
    assert "Signing lockfile" in result.stdout


def test_demo_output_tool_count_is_8() -> None:
    """Demo fixture produces exactly 8 tools (frozen bundled fixture)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["demo"])

    assert result.exit_code == 0
    assert "8 tools" in result.stdout


def test_demo_output_contains_summary_panel() -> None:
    """Demo output includes the 'What just happened' summary panel."""
    runner = CliRunner()
    result = runner.invoke(cli, ["demo"])

    assert result.exit_code == 0
    assert "What just happened" in result.stdout
    assert "governance looks like" in result.stdout.lower()


def test_demo_output_no_temp_path_noise() -> None:
    """Demo output should not expose temp directory paths to the user."""
    runner = CliRunner()
    result = runner.invoke(cli, ["demo"])

    assert result.exit_code == 0
    output = result.stdout
    # No raw temp paths
    assert "/private/var/folders" not in output
    assert "toolwright-demo-" not in output


def test_demo_what_happened_uses_clear_language() -> None:
    """'What just happened' section should use clear, non-jargon language."""
    runner = CliRunner()
    result = runner.invoke(cli, ["demo"])

    assert result.exit_code == 0
    output = result.stdout
    # Should use clear language about governance
    assert "governed tools" in output.lower() or "governed" in output.lower()
    assert "blocked" in output.lower() or "fail-closed" in output.lower()
