"""Tests for the shell completions command."""

from __future__ import annotations

from click.testing import CliRunner

from toolwright.cli.main import cli


class TestCompletionsCommand:
    """Test the `toolwright completions` command."""

    def test_bash_completions_prints_eval_line(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["completions", "bash"])
        assert result.exit_code == 0
        assert "_TOOLWRIGHT_COMPLETE=bash_source" in result.output
        assert "eval" in result.output

    def test_zsh_completions_prints_eval_line(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["completions", "zsh"])
        assert result.exit_code == 0
        assert "_TOOLWRIGHT_COMPLETE=zsh_source" in result.output
        assert "eval" in result.output

    def test_fish_completions_prints_eval_line(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["completions", "fish"])
        assert result.exit_code == 0
        assert "_TOOLWRIGHT_COMPLETE=fish_source" in result.output

    def test_invalid_shell_rejected(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["completions", "powershell"])
        assert result.exit_code != 0

    def test_completions_visible_in_help(self) -> None:
        """Completions should appear in the Operations section."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "completions" in result.output


class TestHelpVisibility:
    """Test that command visibility changes are correct."""

    def test_wrap_visible_in_default_help(self) -> None:
        """wrap should appear in Operations, not hidden behind --help-all."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "wrap" in result.output

    def test_help_all_hint_names_notable_commands(self) -> None:
        """The --help-all hint should mention notable hidden commands."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        # Should mention at least 'init' and 'ship' by name
        assert "init" in result.output
        assert "ship" in result.output
