"""Tests for gate allow --all handling of rejected tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from toolwright.core.approval import ApprovalStatus, LockfileManager


@pytest.fixture
def setup_env_with_rejected(tmp_path: Path) -> tuple[Path, Path]:
    """Set up test environment with some pending and some rejected tools."""
    tools_path = tmp_path / "tools.json"
    lockfile_path = tmp_path / "toolwright.lock.yaml"

    manifest = {
        "actions": [
            {
                "name": "get_users",
                "signature_id": "sig_get_users",
                "method": "GET",
                "path": "/api/users",
                "host": "api.example.com",
                "risk_tier": "low",
            },
            {
                "name": "create_user",
                "signature_id": "sig_create_user",
                "method": "POST",
                "path": "/api/users",
                "host": "api.example.com",
                "risk_tier": "medium",
            },
            {
                "name": "delete_user",
                "signature_id": "sig_delete_user",
                "method": "DELETE",
                "path": "/api/users/{id}",
                "host": "api.example.com",
                "risk_tier": "high",
            },
        ]
    }

    with open(tools_path, "w") as f:
        json.dump(manifest, f)

    # Sync and reject one tool
    manager = LockfileManager(lockfile_path)
    manager.load()
    manager.sync_from_manifest(manifest)
    manager.reject("delete_user", "Too dangerous")
    manager.save()

    return tools_path, lockfile_path


class TestGateAllowAllWithRejected:
    """Tests for gate allow --all behavior when rejected tools exist."""

    def test_get_rejected_returns_rejected_tools(
        self, setup_env_with_rejected: tuple[Path, Path]
    ) -> None:
        """LockfileManager.get_rejected() should return rejected tools."""
        _tools_path, lockfile_path = setup_env_with_rejected
        manager = LockfileManager(lockfile_path)
        manager.load()

        rejected = manager.get_rejected()
        assert len(rejected) == 1
        assert rejected[0].name == "delete_user"
        assert rejected[0].rejection_reason == "Too dangerous"

    def test_allow_all_with_rejected_warns(
        self, setup_env_with_rejected: tuple[Path, Path]
    ) -> None:
        """gate allow --all --yes should warn when rejected tools exist."""
        from click.testing import CliRunner
        from toolwright.cli.main import cli

        _tools_path, lockfile_path = setup_env_with_rejected
        runner = CliRunner()

        result = runner.invoke(
            cli,
            ["gate", "allow", "--all", "--yes", "--lockfile", str(lockfile_path)],
        )

        # Should warn about rejected tools
        assert "delete_user" in result.output
        assert "rejected" in result.output.lower()

    def test_allow_all_include_rejected_approves_everything(
        self, setup_env_with_rejected: tuple[Path, Path]
    ) -> None:
        """gate allow --all --include-rejected should approve all including rejected."""
        from click.testing import CliRunner
        from toolwright.cli.main import cli

        _tools_path, lockfile_path = setup_env_with_rejected
        runner = CliRunner()

        result = runner.invoke(
            cli,
            [
                "gate", "allow", "--all", "--yes",
                "--include-rejected",
                "--lockfile", str(lockfile_path),
            ],
        )

        assert result.exit_code == 0

        # Verify all tools are now approved
        manager = LockfileManager(lockfile_path)
        manager.load()
        for tool in manager.lockfile.tools.values():
            assert tool.status == ApprovalStatus.APPROVED

    def test_allow_all_noninteractive_with_rejected_exits_1(
        self, setup_env_with_rejected: tuple[Path, Path]
    ) -> None:
        """gate allow --all --yes with rejected tools (no --include-rejected) should exit 1."""
        from click.testing import CliRunner
        from toolwright.cli.main import cli

        _tools_path, lockfile_path = setup_env_with_rejected
        runner = CliRunner()

        result = runner.invoke(
            cli,
            ["gate", "allow", "--all", "--yes", "--lockfile", str(lockfile_path)],
        )

        # Should exit non-zero due to remaining rejected tools
        assert result.exit_code == 1
        assert "rejected" in result.output.lower()
