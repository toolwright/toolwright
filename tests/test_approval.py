"""Tests for approval workflow and lockfile management."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tests.helpers import write_demo_toolpack
from toolwright.core.approval import ApprovalStatus, LockfileManager, ToolApproval
from toolwright.core.approval.snapshot import materialize_snapshot


class TestToolApproval:
    """Tests for ToolApproval model."""

    def test_create_pending_tool(self) -> None:
        """Test creating a pending tool approval."""
        tool = ToolApproval(
            tool_id="get_users",
            signature_id="abc123",
            name="get_users",
            method="GET",
            path="/api/users",
            host="api.example.com",
        )
        assert tool.status == ApprovalStatus.PENDING
        assert tool.tool_version == 1
        assert tool.approved_at is None
        assert tool.approved_by is None

    def test_create_with_risk_tier(self) -> None:
        """Test creating tool with risk tier."""
        tool = ToolApproval(
            tool_id="delete_user",
            signature_id="xyz789",
            name="delete_user",
            method="DELETE",
            path="/api/users/{id}",
            host="api.example.com",
            risk_tier="high",
        )
        assert tool.risk_tier == "high"


class TestLockfileManager:
    """Tests for LockfileManager."""

    @pytest.fixture
    def tmp_lockfile(self, tmp_path: Path) -> Path:
        """Create a temp lockfile path."""
        return tmp_path / "toolwright.lock.yaml"

    @pytest.fixture
    def sample_manifest(self) -> dict:
        """Sample tools manifest."""
        return {
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

    @pytest.fixture
    def sample_toolsets(self) -> dict:
        """Sample toolsets artifact payload."""
        return {
            "schema_version": "1.0",
            "toolsets": {
                "readonly": {
                    "actions": ["get_users"],
                },
                "operator": {
                    "actions": ["get_users", "create_user", "delete_user"],
                },
            },
        }

    def test_init_default_path(self) -> None:
        """Test default lockfile path."""
        manager = LockfileManager()
        assert manager.lockfile_path.name == "toolwright.lock.yaml"

    def test_init_custom_path(self, tmp_lockfile: Path) -> None:
        """Test custom lockfile path."""
        manager = LockfileManager(tmp_lockfile)
        assert manager.lockfile_path == tmp_lockfile

    def test_load_nonexistent(self, tmp_lockfile: Path) -> None:
        """Test loading when lockfile doesn't exist."""
        manager = LockfileManager(tmp_lockfile)
        lockfile = manager.load()
        assert lockfile is not None
        assert len(lockfile.tools) == 0

    def test_save_and_load(self, tmp_lockfile: Path) -> None:
        """Test saving and loading lockfile."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()

        # Add a tool
        manager.lockfile.tools["sig123"] = ToolApproval(
            tool_id="test_tool",
            signature_id="sig123",
            name="test_tool",
            method="GET",
            path="/test",
            host="api.example.com",
        )

        manager.save()

        # Load in new manager
        manager2 = LockfileManager(tmp_lockfile)
        manager2.load()
        assert "sig123" in manager2.lockfile.tools
        assert manager2.lockfile.tools["sig123"].signature_id == "sig123"
        assert manager2.lockfile.schema_version == "1.0"

    def test_sync_generated_at_never_epoch_zero(
        self, tmp_lockfile: Path, sample_manifest: dict
    ) -> None:
        """M16: generated_at must never be epoch zero, even with deterministic=True."""
        from datetime import UTC, datetime

        manager = LockfileManager(tmp_lockfile)
        manager.load()

        manager.sync_from_manifest(sample_manifest, deterministic=True)

        epoch_zero = datetime(1970, 1, 1, tzinfo=UTC)
        assert manager.lockfile.generated_at != epoch_zero, (
            "Lockfile generated_at should be a real timestamp, not epoch zero"
        )
        # Should be recent (within last minute)
        now = datetime.now(UTC)
        delta = (now - manager.lockfile.generated_at).total_seconds()
        assert delta < 60, f"generated_at is {delta}s old, expected recent"

    def test_sync_from_manifest_new_tools(
        self, tmp_lockfile: Path, sample_manifest: dict
    ) -> None:
        """Test syncing new tools from manifest."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()

        changes = manager.sync_from_manifest(sample_manifest)

        assert len(changes["new"]) == 3
        assert "get_users" in changes["new"]
        assert "create_user" in changes["new"]
        assert "delete_user" in changes["new"]
        assert len(changes["modified"]) == 0
        assert len(changes["removed"]) == 0

        # All should be pending
        for tool in manager.lockfile.tools.values():
            assert tool.status == ApprovalStatus.PENDING

    def test_sync_keys_lockfile_by_signature_id(
        self, tmp_lockfile: Path, sample_manifest: dict
    ) -> None:
        """Lockfile stores tools keyed by signature_id when available."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()
        manager.sync_from_manifest(sample_manifest)

        assert set(manager.lockfile.tools.keys()) == {
            "sig_get_users",
            "sig_create_user",
            "sig_delete_user",
        }

    def test_sync_from_manifest_modified_tool(
        self, tmp_lockfile: Path, sample_manifest: dict
    ) -> None:
        """Test syncing when tool signature changes."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()

        # First sync
        manager.sync_from_manifest(sample_manifest)
        manager.approve("get_users", "admin")

        # Modify signature
        sample_manifest["actions"][0]["signature_id"] = "new_signature"
        changes = manager.sync_from_manifest(sample_manifest)

        assert "get_users" in changes["modified"]
        tool = manager.get_tool("get_users")
        assert tool is not None
        assert tool.status == ApprovalStatus.PENDING
        assert tool.previous_signature == "sig_get_users"
        assert tool.tool_version == 2

    def test_sync_keeps_graphql_operation_split_distinct(
        self,
        tmp_lockfile: Path,
    ) -> None:
        """Distinct GraphQL operation tools sharing endpoint_id must not collapse."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()

        manifest = {
            "actions": [
                {
                    "name": "query_recently_viewed_products",
                    "signature_id": "sig_graphql_query",
                    "tool_id": "sig_graphql_query",
                    "endpoint_id": "ep_graphql_shared",
                    "method": "POST",
                    "path": "/api/graphql",
                    "host": "stockx.com",
                    "risk_tier": "low",
                },
                {
                    "name": "mutate_update_bid",
                    "signature_id": "sig_graphql_mutation",
                    "tool_id": "sig_graphql_mutation",
                    "endpoint_id": "ep_graphql_shared",
                    "method": "POST",
                    "path": "/api/graphql",
                    "host": "stockx.com",
                    "risk_tier": "high",
                },
            ]
        }

        changes = manager.sync_from_manifest(manifest)

        assert len(changes["new"]) == 2
        assert manager.lockfile is not None
        assert len(manager.lockfile.tools) == 2
        assert manager.get_tool("query_recently_viewed_products") is not None
        assert manager.get_tool("mutate_update_bid") is not None

    def test_sync_records_toolset_membership(
        self,
        tmp_lockfile: Path,
        sample_manifest: dict,
        sample_toolsets: dict,
    ) -> None:
        """Sync should persist toolset membership on each tool."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()

        manager.sync_from_manifest(sample_manifest, toolsets=sample_toolsets)

        get_users = manager.get_tool("get_users")
        create_user = manager.get_tool("create_user")
        assert get_users is not None
        assert create_user is not None
        assert get_users.toolsets == ["operator", "readonly"]
        assert create_user.toolsets == ["operator"]

    def test_sync_from_manifest_risk_escalation(
        self, tmp_lockfile: Path, sample_manifest: dict
    ) -> None:
        """Test syncing when risk tier escalates."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()

        # First sync
        manager.sync_from_manifest(sample_manifest)
        manager.approve("get_users", "admin")

        # Escalate risk
        sample_manifest["actions"][0]["risk_tier"] = "high"
        changes = manager.sync_from_manifest(sample_manifest)

        assert "get_users" in changes["modified"]
        tool = manager.get_tool("get_users")
        assert tool is not None
        assert tool.status == ApprovalStatus.PENDING
        assert tool.change_type == "risk_changed"

    def test_sync_from_manifest_removed_tool(
        self, tmp_lockfile: Path, sample_manifest: dict
    ) -> None:
        """Test syncing when tool is removed from manifest."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()

        # First sync
        manager.sync_from_manifest(sample_manifest)

        # Remove a tool
        sample_manifest["actions"] = [
            a for a in sample_manifest["actions"] if a["name"] != "delete_user"
        ]
        changes = manager.sync_from_manifest(sample_manifest)

        assert "delete_user" in changes["removed"]
        # Tool should still exist in lockfile
        assert manager.get_tool("delete_user") is not None

    def test_sync_from_manifest_prune_removed_deletes_tool(
        self, tmp_lockfile: Path, sample_manifest: dict
    ) -> None:
        """Sync with prune_removed should delete removed tools from the lockfile."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()

        # First sync
        manager.sync_from_manifest(sample_manifest)

        # Remove a tool
        next_manifest = {
            "actions": [
                action
                for action in sample_manifest["actions"]
                if action["name"] != "delete_user"
            ]
        }
        changes = manager.sync_from_manifest(next_manifest, prune_removed=True)

        assert "delete_user" in changes["removed"]
        assert manager.get_tool("delete_user") is None

    def test_sync_from_manifest_stable_tool_order(
        self, tmp_lockfile: Path, sample_manifest: dict
    ) -> None:
        """Sync/save writes tools in deterministic sorted order."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()

        shuffled_manifest = {
            "actions": list(reversed(sample_manifest["actions"])),
        }
        manager.sync_from_manifest(shuffled_manifest)
        manager.save()

        saved = yaml.safe_load(tmp_lockfile.read_text())
        tool_ids = list(saved["tools"].keys())

        assert tool_ids == sorted(tool_ids)

    def test_approve_tool(self, tmp_lockfile: Path, sample_manifest: dict) -> None:
        """Test approving a tool."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()
        manager.sync_from_manifest(sample_manifest)

        result = manager.approve("get_users", "security@example.com")
        assert result is True

        tool = manager.get_tool("get_users")
        assert tool is not None
        assert tool.status == ApprovalStatus.APPROVED
        assert tool.approved_by == "security@example.com"
        assert tool.approved_at is not None

    def test_approve_nonexistent_tool(self, tmp_lockfile: Path) -> None:
        """Test approving a tool that doesn't exist."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()

        result = manager.approve("nonexistent")
        assert result is False

    def test_approve_all(self, tmp_lockfile: Path, sample_manifest: dict) -> None:
        """Test approving all pending tools."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()
        manager.sync_from_manifest(sample_manifest)

        count = manager.approve_all("admin")
        assert count == 3

        for tool in manager.lockfile.tools.values():
            assert tool.status == ApprovalStatus.APPROVED

    def test_approve_toolset_scoped(
        self,
        tmp_lockfile: Path,
        sample_manifest: dict,
        sample_toolsets: dict,
    ) -> None:
        """Scoped approval should mark only selected toolset approvals."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()
        manager.sync_from_manifest(sample_manifest, toolsets=sample_toolsets)

        approved = manager.approve("get_users", "security@example.com", toolset="readonly")
        assert approved is True

        tool = manager.get_tool("get_users")
        assert tool is not None
        assert tool.approved_toolsets == ["readonly"]
        # Not globally approved until all memberships are approved.
        assert tool.status == ApprovalStatus.PENDING

    def test_reject_tool(self, tmp_lockfile: Path, sample_manifest: dict) -> None:
        """Test rejecting a tool."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()
        manager.sync_from_manifest(sample_manifest)

        result = manager.reject("delete_user", "Too dangerous for production")
        assert result is True

        tool = manager.get_tool("delete_user")
        assert tool is not None
        assert tool.status == ApprovalStatus.REJECTED
        assert tool.rejection_reason == "Too dangerous for production"

    def test_get_pending(self, tmp_lockfile: Path, sample_manifest: dict) -> None:
        """Test getting pending tools."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()
        manager.sync_from_manifest(sample_manifest)

        pending = manager.get_pending()
        assert len(pending) == 3

        # Approve one
        manager.approve("get_users")
        pending = manager.get_pending()
        assert len(pending) == 2

    def test_get_approved(self, tmp_lockfile: Path, sample_manifest: dict) -> None:
        """Test getting approved tools."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()
        manager.sync_from_manifest(sample_manifest)

        approved = manager.get_approved()
        assert len(approved) == 0

        manager.approve("get_users")
        manager.approve("create_user")

        approved = manager.get_approved()
        assert len(approved) == 2

    def test_has_pending(self, tmp_lockfile: Path, sample_manifest: dict) -> None:
        """Test checking for pending tools."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()

        assert not manager.has_pending()

        manager.sync_from_manifest(sample_manifest)
        assert manager.has_pending()

        manager.approve_all()
        assert not manager.has_pending()

    def test_check_ci_all_approved(self, tmp_path: Path) -> None:
        """Test CI check with all tools approved and snapshot present."""
        toolpack_file = write_demo_toolpack(tmp_path)
        lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"
        manager = LockfileManager(lockfile_path)
        manager.load()
        manager.approve_all()
        result = materialize_snapshot(lockfile_path)
        relative_dir = result.snapshot_dir.relative_to(toolpack_file.parent)
        manager.set_baseline_snapshot(str(relative_dir), result.digest)
        manager.save()

        passed, message = manager.check_ci()
        assert passed is True
        assert "verified baseline snapshot" in message

    def test_check_ci_pending(
        self, tmp_lockfile: Path, sample_manifest: dict
    ) -> None:
        """Test CI check with pending tools."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()
        manager.sync_from_manifest(sample_manifest)

        passed, message = manager.check_ci()
        assert passed is False
        assert "Pending approval" in message

    def test_check_ci_toolset_scoped(self, tmp_path: Path) -> None:
        """Toolset CI checks should only evaluate selected toolset approvals."""
        toolpack_file = write_demo_toolpack(tmp_path)
        lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"
        manager = LockfileManager(lockfile_path)
        manager.load()

        passed, message = manager.check_ci(toolset="readonly")
        assert passed is False
        assert "Pending approval in 'readonly'" in message

        manager.approve("get_users", "security@example.com", toolset="readonly")
        result = materialize_snapshot(lockfile_path)
        relative_dir = result.snapshot_dir.relative_to(toolpack_file.parent)
        manager.set_baseline_snapshot(str(relative_dir), result.digest)
        manager.save()

        passed, message = manager.check_ci(toolset="readonly")
        assert passed is True
        assert "All tools approved in 'readonly'" in message

    def test_check_ci_rejected(
        self, tmp_lockfile: Path, sample_manifest: dict
    ) -> None:
        """Test CI check with rejected tools."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()
        manager.sync_from_manifest(sample_manifest)
        manager.approve("get_users")
        manager.approve("create_user")
        manager.reject("delete_user")

        passed, message = manager.check_ci()
        assert passed is False
        assert "Rejected tools" in message

    def test_to_yaml(self, tmp_lockfile: Path, sample_manifest: dict) -> None:
        """Test serializing lockfile to YAML."""
        manager = LockfileManager(tmp_lockfile)
        manager.load()
        manager.sync_from_manifest(sample_manifest)

        yaml_str = manager.to_yaml()
        data = yaml.safe_load(yaml_str)

        assert "version" in data
        assert data["schema_version"] == "1.0"
        assert "tools" in data
        assert len(data["tools"]) == 3

    def test_load_rejects_unsupported_schema_version(self, tmp_lockfile: Path) -> None:
        """Loading fails on unsupported lockfile schema_version."""
        tmp_lockfile.write_text(
            "version: 1.0.0\n"
            "schema_version: 999.0\n"
            "tools: {}\n"
        )

        manager = LockfileManager(tmp_lockfile)
        with pytest.raises(ValueError, match="Unsupported lockfile schema_version"):
            manager.load()


class TestApprovalCLI:
    """Tests for approval CLI commands."""

    @pytest.fixture
    def setup_env(self, tmp_path: Path) -> tuple[Path, Path]:
        """Set up test environment with tools manifest and lockfile."""
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
                    "risk_tier": "high",
                },
            ]
        }

        with open(tools_path, "w") as f:
            json.dump(manifest, f)

        return tools_path, lockfile_path

    def test_sync_creates_lockfile(self, setup_env: tuple[Path, Path]) -> None:
        """Test that sync creates lockfile with pending tools."""
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        tools_path, lockfile_path = setup_env
        runner = CliRunner()

        result = runner.invoke(
            cli,
            ["gate", "sync", "--tools", str(tools_path), "--lockfile", str(lockfile_path)],
        )

        assert result.exit_code == 1  # Pending tools
        assert "Synced lockfile" in result.output
        assert "New tools: 2" in result.output
        assert "pending approval" in result.output
        assert lockfile_path.exists()

    def test_list_shows_tools(self, setup_env: tuple[Path, Path]) -> None:
        """Test that list shows tools from lockfile."""
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        tools_path, lockfile_path = setup_env
        runner = CliRunner()

        # First sync
        runner.invoke(
            cli,
            ["gate", "sync", "--tools", str(tools_path), "--lockfile", str(lockfile_path)],
        )

        # Then list
        result = runner.invoke(
            cli,
            ["gate", "status", "--lockfile", str(lockfile_path)],
        )

        assert result.exit_code == 0
        assert "get_users" in result.output
        assert "create_user" in result.output

    def test_approve_tool_changes_status(self, setup_env: tuple[Path, Path]) -> None:
        """Test that approve changes tool status."""
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        tools_path, lockfile_path = setup_env
        runner = CliRunner()

        # Sync
        runner.invoke(
            cli,
            ["gate", "sync", "--tools", str(tools_path), "--lockfile", str(lockfile_path)],
        )

        # Approve
        result = runner.invoke(
            cli,
            ["gate", "allow", "get_users", "--lockfile", str(lockfile_path)],
        )

        assert result.exit_code == 0
        assert "Approved: get_users" in result.output

        # Verify
        manager = LockfileManager(lockfile_path)
        manager.load()
        tool = manager.get_tool("get_users")
        assert tool is not None
        assert tool.status == ApprovalStatus.APPROVED

    def test_approve_all(self, setup_env: tuple[Path, Path]) -> None:
        """Test approving all pending tools."""
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        tools_path, lockfile_path = setup_env
        runner = CliRunner()

        # Sync
        runner.invoke(
            cli,
            ["gate", "sync", "--tools", str(tools_path), "--lockfile", str(lockfile_path)],
        )

        # Approve all
        result = runner.invoke(
            cli,
            ["gate", "allow", "--all", "--yes", "--lockfile", str(lockfile_path)],
        )

        assert result.exit_code == 0
        assert "Approved 2 tools" in result.output

    def test_reject_tool(self, setup_env: tuple[Path, Path]) -> None:
        """Test rejecting a tool."""
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        tools_path, lockfile_path = setup_env
        runner = CliRunner()

        # Sync
        runner.invoke(
            cli,
            ["gate", "sync", "--tools", str(tools_path), "--lockfile", str(lockfile_path)],
        )

        # Reject
        result = runner.invoke(
            cli,
            ["gate", "block", "create_user", "--lockfile", str(lockfile_path), "--reason", "Too risky"],
        )

        assert result.exit_code == 0
        assert "Blocked: create_user" in result.output

    def test_check_fails_on_pending(self, setup_env: tuple[Path, Path]) -> None:
        """Test that check fails when tools are pending."""
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        tools_path, lockfile_path = setup_env
        runner = CliRunner()

        # Sync
        runner.invoke(
            cli,
            ["gate", "sync", "--tools", str(tools_path), "--lockfile", str(lockfile_path)],
        )

        # Check
        result = runner.invoke(
            cli,
            ["gate", "check", "--lockfile", str(lockfile_path)],
        )

        assert result.exit_code == 1
        assert "pending approval" in result.output.lower()

    def test_check_passes_when_all_approved(self, tmp_path: Path) -> None:
        """Test that check passes when all tools approved with snapshot present."""
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        toolpack_file = write_demo_toolpack(tmp_path)
        lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"
        runner = CliRunner()

        runner.invoke(
            cli,
            ["gate", "allow", "--all", "--yes", "--lockfile", str(lockfile_path)],
        )

        result = runner.invoke(
            cli,
            ["gate", "check", "--lockfile", str(lockfile_path)],
        )

        assert result.exit_code == 0
        assert "verified baseline snapshot" in result.output

    def test_toolset_scoped_approval_check(self, tmp_path: Path) -> None:
        """CLI supports toolset-scoped approval/check workflow."""
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        toolpack_file = write_demo_toolpack(tmp_path)
        lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"
        runner = CliRunner()

        pending_check = runner.invoke(
            cli,
            ["gate", "check", "--lockfile", str(lockfile_path), "--toolset", "readonly"],
        )
        assert pending_check.exit_code == 1
        assert "pending approval" in pending_check.output.lower()

        approve_result = runner.invoke(
            cli,
            [
                "gate", "allow", "get_users",
                "--lockfile", str(lockfile_path),
                "--toolset", "readonly",
            ],
        )
        assert approve_result.exit_code == 0

        passed_check = runner.invoke(
            cli,
            ["gate", "check", "--lockfile", str(lockfile_path), "--toolset", "readonly"],
        )
        assert passed_check.exit_code == 0
        assert "All tools approved in 'readonly'" in passed_check.output
