"""Tests for demo command output format and content."""

from __future__ import annotations

from click.testing import CliRunner

from toolwright.cli.main import cli


def test_demo_output_contains_tool_table() -> None:
    """Demo output includes tool count and method/path table."""
    runner = CliRunner()
    result = runner.invoke(cli, ["demo"])

    assert result.exit_code == 0
    assert "tools compiled" in result.stdout


def test_demo_output_contains_correct_next_step_commands() -> None:
    """Demo output prints exact flag forms for gate, run, and drift."""
    runner = CliRunner()
    result = runner.invoke(cli, ["demo"])

    assert result.exit_code == 0
    assert "toolwright gate allow --all --lockfile" in result.stdout
    assert "toolwright serve --toolpack" in result.stdout
    assert "toolwright drift --baseline" in result.stdout


def test_demo_output_tool_count_is_8() -> None:
    """Demo fixture produces exactly 8 tools (frozen bundled fixture)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["demo"])

    assert result.exit_code == 0
    assert "8 tools compiled" in result.stdout


def test_demo_output_contains_artifact_paths() -> None:
    """Demo output prints Toolpack, Pending lock, and Baseline lines."""
    runner = CliRunner()
    result = runner.invoke(cli, ["demo"])

    assert result.exit_code == 0
    assert "Toolpack:" in result.stdout
    assert "Pending lock:" in result.stdout
    assert "Baseline:" in result.stdout


def test_demo_output_contains_temp_dir_disclaimer() -> None:
    """Demo output warns that artifacts are in a temp dir and suggests mint."""
    runner = CliRunner()
    result = runner.invoke(cli, ["demo"])

    assert result.exit_code == 0
    output = result.stdout.lower()
    # Should warn users about temp paths
    assert "temp" in output and "mint" in output, (
        f"Demo should include a disclaimer about temp paths and suggest mint. Got: {result.stdout!r}"
    )


def test_demo_what_happened_uses_clear_language() -> None:
    """'What just happened' section should use clear, non-jargon language."""
    runner = CliRunner()
    result = runner.invoke(cli, ["demo"])

    assert result.exit_code == 0
    output = result.stdout
    # Should NOT use jargon-heavy phrases
    assert "Parsed" not in output or "bundled HAR traffic" not in output, (
        "Demo should not use jargon like 'bundled HAR traffic'"
    )
    # Should use clearer language
    assert "approval" in output.lower() or "review" in output.lower(), (
        "Demo should explain the approval workflow in user-friendly terms"
    )
