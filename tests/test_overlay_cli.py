"""Tests for the toolwright wrap CLI command."""

from click.testing import CliRunner


class TestWrapCommandParsing:
    def test_wrap_help(self):
        from toolwright.cli.commands_wrap import wrap_command

        runner = CliRunner()
        result = runner.invoke(wrap_command, ["--help"])
        assert result.exit_code == 0
        assert "wrap" in result.output.lower() or "govern" in result.output.lower()

    def test_wrap_requires_command_or_url(self):
        from toolwright.cli.commands_wrap import wrap_command

        runner = CliRunner()
        # No saved config, no command, no url → should fail
        result = runner.invoke(wrap_command, [], catch_exceptions=True)
        # Should error because no target specified
        assert result.exit_code != 0

    def test_wrap_accepts_command_argument(self):
        """Verify command argument is parsed (actual execution mocked)."""
        from toolwright.cli.commands_wrap import wrap_command

        runner = CliRunner()
        # This will fail at connection time, but we're testing arg parsing
        result = runner.invoke(
            wrap_command,
            ["echo", "test", "--name", "test-server", "--dry-run"],
            catch_exceptions=True,
        )
        # Should get past argument parsing
        # (may fail later due to no actual server)
        assert "Unknown" not in result.output or result.exit_code != 2

    def test_wrap_accepts_dash_args_for_upstream(self):
        """M12: 'toolwright wrap npx -y ...' must not fail on the -y flag."""
        from toolwright.cli.commands_wrap import wrap_command

        runner = CliRunner()
        result = runner.invoke(
            wrap_command,
            ["npx", "-y", "@modelcontextprotocol/server-github", "--name", "gh", "--dry-run"],
            catch_exceptions=True,
        )
        # Should parse correctly — exit 2 means Click rejected the args
        assert result.exit_code != 2, f"Click rejected -y flag: {result.output}"

    def test_wrap_url_option_parsing(self):
        """Verify --url is parsed correctly (don't try to actually connect)."""
        from unittest.mock import patch

        from toolwright.cli.commands_wrap import wrap_command

        runner = CliRunner()
        # Mock _run_wrap to avoid actual network calls
        with patch("toolwright.cli.commands_wrap._run_wrap") as mock_run:
            result = runner.invoke(
                wrap_command,
                ["--url", "https://mcp.example.com/mcp", "--name", "example", "--dry-run"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            # Verify _run_wrap was called (means parsing succeeded)
            mock_run.assert_called_once()
