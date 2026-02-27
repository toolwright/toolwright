"""Tests for --allowed-hosts guidance when omitted."""

from __future__ import annotations

from click.testing import CliRunner

from toolwright.cli.main import cli


class TestCaptureAllowedHostsHelp:
    """When --allowed-hosts is missing, capture should give helpful guidance."""

    def test_capture_import_without_hosts_gives_guidance(self) -> None:
        """Missing -a should explain what the flag is for with examples."""
        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "import", "traffic.har"])
        assert result.exit_code != 0
        assert "--allowed-hosts" in result.output or "-a" in result.output
        assert "api.example.com" in result.output

    def test_capture_record_without_hosts_gives_guidance(self) -> None:
        """Missing -a for record should also explain."""
        runner = CliRunner()
        result = runner.invoke(cli, ["capture", "record", "https://example.com"])
        assert result.exit_code != 0
        assert "--allowed-hosts" in result.output or "-a" in result.output
