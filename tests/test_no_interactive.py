"""Tests for --no-interactive flag behavior.

H1: --no-interactive must work when placed after the subcommand name.
H2: --no-interactive must suppress ALL interactive prompts, including
    those in deep call paths (e.g. prompt_auth_setup_if_missing).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestNoInteractiveAfterSubcommand:
    """H1: --no-interactive works when placed after the command name."""

    def test_no_interactive_before_subcommand(self, runner: CliRunner) -> None:
        """toolwright --no-interactive <cmd> already works — baseline."""
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["--no-interactive"])
        assert result.exit_code == 0
        # Non-interactive mode shows help, not wizard
        assert "Usage" in result.output or "Commands" in result.output

    def test_no_interactive_after_subcommand_kill(self, runner: CliRunner) -> None:
        """toolwright kill --no-interactive <tool> must not error on unknown option."""
        from toolwright.cli.main import cli

        # We expect it to fail on missing tool_id, NOT on unknown --no-interactive
        result = runner.invoke(cli, ["kill", "--no-interactive", "fake-tool", "--yes"])
        # Should NOT contain "No such option: --no-interactive"
        assert "No such option" not in (result.output + (result.stderr or ""))

    def test_no_interactive_after_subcommand_rules_remove(self, runner: CliRunner) -> None:
        """toolwright rules remove --no-interactive must be accepted."""
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["rules", "remove", "--no-interactive", "fake-rule", "--yes"])
        assert "No such option" not in (result.output + (result.stderr or ""))


class TestNoInteractiveSuppressesAllPrompts:
    """H2: --no-interactive suppresses prompts that only check isatty()."""

    def test_prompt_auth_setup_skipped_when_no_interactive(self) -> None:
        """prompt_auth_setup_if_missing must not prompt when no_interactive=True."""
        from toolwright.mcp.runtime import prompt_auth_setup_if_missing

        with patch("toolwright.mcp.runtime.warn_missing_auth", return_value=["Missing API_KEY"]):
            # Even if stdin is a tty, no_interactive=True should skip the prompt
            with patch("sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = True
                with patch("toolwright.mcp.runtime.click") as mock_click:
                    prompt_auth_setup_if_missing(
                        tools_path="tools.json",
                        auth_header=None,
                        root=Path("."),
                        no_interactive=True,
                    )
                    # confirm should NOT have been called
                    mock_click.confirm.assert_not_called()

    def test_prompt_auth_setup_prompts_when_interactive(self) -> None:
        """prompt_auth_setup_if_missing prompts normally when no_interactive=False."""
        from toolwright.mcp.runtime import prompt_auth_setup_if_missing

        with patch("toolwright.mcp.runtime.warn_missing_auth", return_value=["Missing API_KEY"]):
            with patch("sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = True
                with patch("toolwright.mcp.runtime.click") as mock_click:
                    mock_click.confirm.return_value = False
                    prompt_auth_setup_if_missing(
                        tools_path="tools.json",
                        auth_header=None,
                        root=Path("."),
                        no_interactive=False,
                    )
                    # confirm SHOULD have been called
                    mock_click.confirm.assert_called_once()
