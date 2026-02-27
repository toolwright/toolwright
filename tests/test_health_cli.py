"""Tests for the `toolwright health` CLI command.

Probes endpoint health for all tools in a manifest and reports results.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from toolwright.cli.main import cli


@pytest.fixture
def tools_manifest(tmp_path: Path) -> Path:
    """Create a tools manifest with two actions."""
    manifest = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "name": "Health Test Tools",
        "allowed_hosts": ["api.example.com"],
        "actions": [
            {
                "name": "get_user",
                "method": "GET",
                "path": "/api/users/{user_id}",
                "host": "api.example.com",
            },
            {
                "name": "create_user",
                "method": "POST",
                "path": "/api/users",
                "host": "api.example.com",
            },
        ],
    }
    p = tmp_path / "tools.json"
    p.write_text(json.dumps(manifest))
    return p


class TestHealthCommand:
    """Tests for `toolwright health --tools <path>`."""

    def test_health_command_exists(self):
        """The `health` command should be registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["health", "--help"])
        assert result.exit_code == 0
        assert "health" in result.output.lower()

    def test_health_all_healthy(self, tools_manifest: Path):
        """When all endpoints return 200, exit 0 and show healthy."""
        with patch(
            "toolwright.core.health.checker.HealthChecker._send_probe",
            new_callable=AsyncMock,
            return_value=(200, 25.0, None),
        ):
            runner = CliRunner()
            result = runner.invoke(cli, ["health", "--tools", str(tools_manifest)])
        assert result.exit_code == 0
        assert "get_user" in result.output
        assert "create_user" in result.output

    def test_health_unhealthy_exits_1(self, tools_manifest: Path):
        """When any endpoint fails, exit code is 1."""
        with patch(
            "toolwright.core.health.checker.HealthChecker._send_probe",
            new_callable=AsyncMock,
            return_value=(500, 100.0, None),
        ):
            runner = CliRunner()
            result = runner.invoke(cli, ["health", "--tools", str(tools_manifest)])
        assert result.exit_code == 1

    def test_health_shows_failure_class(self, tools_manifest: Path):
        """Failure class should appear in output."""
        with patch(
            "toolwright.core.health.checker.HealthChecker._send_probe",
            new_callable=AsyncMock,
            return_value=(401, 50.0, None),
        ):
            runner = CliRunner()
            result = runner.invoke(cli, ["health", "--tools", str(tools_manifest)])
        assert "auth_expired" in result.output.lower()

    def test_health_requires_tools(self):
        """health command requires --tools argument."""
        runner = CliRunner()
        result = runner.invoke(cli, ["health"])
        assert result.exit_code != 0
