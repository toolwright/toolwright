"""Tests for polished demo command output (governance-in-action format)."""

from __future__ import annotations

import re

from click.testing import CliRunner

from toolwright.cli.main import cli


def _run_demo() -> str:
    """Helper: invoke demo and return stdout."""
    runner = CliRunner()
    result = runner.invoke(cli, ["demo"])
    assert result.exit_code == 0, f"demo failed: {result.output}"
    return result.output


class TestDemoPolishHeader:
    def test_contains_governance_in_action(self) -> None:
        output = _run_demo()
        assert "governance in action" in output

    def test_no_equals_separator_lines(self) -> None:
        """Old format used ====== separators; new format should not."""
        output = _run_demo()
        assert "====" not in output


class TestDemoPolishNoTempPaths:
    def test_no_private_var_folders(self) -> None:
        """Output must not contain macOS temp paths."""
        output = _run_demo()
        assert "/private/var/folders" not in output

    def test_no_tmp_paths(self) -> None:
        """Output must not contain /tmp/ paths."""
        output = _run_demo()
        assert "/tmp/" not in output

    def test_no_toolwright_demo_prefix_paths(self) -> None:
        """Output must not show toolwright-demo- temp dir names."""
        output = _run_demo()
        assert "toolwright-demo-" not in output

    def test_no_next_steps_with_file_paths(self) -> None:
        """No 'Next steps' section referencing file paths."""
        output = _run_demo()
        # Old format had "Next steps:" with --lockfile /path/to/...
        assert "Next steps:" not in output


class TestDemoPolishTimings:
    def test_step_lines_have_timing_or_status(self) -> None:
        """Each step line should end with a timing or status indicator."""
        output = _run_demo()
        # Look for the characteristic step pattern: description... checkmark ... timing
        step_pattern = re.compile(r"[✓]")
        matches = step_pattern.findall(output)
        assert len(matches) >= 4, f"Expected at least 4 checkmarks in output, got {len(matches)}"


class TestDemoPolishSummaryPanel:
    def test_what_just_happened_section(self) -> None:
        output = _run_demo()
        assert "What just happened" in output

    def test_summary_mentions_compiled(self) -> None:
        output = _run_demo()
        assert "Compiled" in output or "compiled" in output

    def test_summary_mentions_blocked(self) -> None:
        output = _run_demo()
        assert "Blocked" in output or "blocked" in output

    def test_summary_mentions_drift(self) -> None:
        output = _run_demo()
        assert "drift" in output.lower()

    def test_summary_mentions_circuit_breaker(self) -> None:
        output = _run_demo()
        assert "circuit breaker" in output.lower() or "quarantine" in output.lower()

    def test_get_started_command(self) -> None:
        output = _run_demo()
        assert "toolwright create" in output

    def test_governance_tagline(self) -> None:
        output = _run_demo()
        assert "governance looks like" in output.lower()


class TestDemoPolishCleanOutput:
    def test_no_artifact_path_lines(self) -> None:
        """No 'Toolpack:', 'Pending lock:', 'Baseline:' lines with file paths."""
        output = _run_demo()
        assert "Toolpack:" not in output
        assert "Pending lock:" not in output
        assert "Baseline:" not in output

    def test_no_mcp_integration_block(self) -> None:
        """MCP integration instructions should not appear in demo output."""
        output = _run_demo()
        assert "Connect to MCP clients" not in output
        assert "claude_desktop_config" not in output

    def test_no_demo_complete_old_header(self) -> None:
        """Old 'Demo complete' header should be gone."""
        output = _run_demo()
        assert "Demo complete" not in output
