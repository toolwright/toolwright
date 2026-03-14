"""Tests for mint UX improvements: capture message, example tool, auto-approve, default rules."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from toolwright.core.approval import ApprovalStatus, LockfileManager

# ---------------------------------------------------------------------------
# Helper: create a realistic lockfile with tools at various risk tiers
# ---------------------------------------------------------------------------

def _create_lockfile_with_risk_tiers(lockfile_path: Path) -> LockfileManager:
    """Create a lockfile containing tools at low, medium, high, and critical risk."""
    manager = LockfileManager(lockfile_path)
    manager.load()
    assert manager.lockfile is not None

    tools = {
        "sig_list_users": {
            "tool_id": "sig_list_users",
            "tool_version": 1,
            "signature_id": "sig_list_users",
            "name": "list_users",
            "method": "GET",
            "path": "/api/users",
            "host": "api.example.com",
            "risk_tier": "low",
            "toolsets": ["readonly"],
            "approved_toolsets": [],
            "status": "pending",
        },
        "sig_get_user": {
            "tool_id": "sig_get_user",
            "tool_version": 1,
            "signature_id": "sig_get_user",
            "name": "get_user",
            "method": "GET",
            "path": "/api/users/{id}",
            "host": "api.example.com",
            "risk_tier": "medium",
            "toolsets": ["readonly"],
            "approved_toolsets": [],
            "status": "pending",
        },
        "sig_update_user": {
            "tool_id": "sig_update_user",
            "tool_version": 1,
            "signature_id": "sig_update_user",
            "name": "update_user",
            "method": "PUT",
            "path": "/api/users/{id}",
            "host": "api.example.com",
            "risk_tier": "high",
            "toolsets": ["write"],
            "approved_toolsets": [],
            "status": "pending",
        },
        "sig_delete_user": {
            "tool_id": "sig_delete_user",
            "tool_version": 1,
            "signature_id": "sig_delete_user",
            "name": "delete_user",
            "method": "DELETE",
            "path": "/api/users/{id}",
            "host": "api.example.com",
            "risk_tier": "critical",
            "toolsets": ["write"],
            "approved_toolsets": [],
            "status": "pending",
        },
    }

    lockfile_data = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "tools": tools,
    }
    lockfile_path.parent.mkdir(parents=True, exist_ok=True)
    lockfile_path.write_text(yaml.dump(lockfile_data, default_flow_style=False, sort_keys=False))

    manager = LockfileManager(lockfile_path)
    manager.load()
    return manager


# ---------------------------------------------------------------------------
# Tests: auto-approve via smart gate
# ---------------------------------------------------------------------------

class TestAutoApproveLockfile:
    """Test the auto_approve_lockfile helper that uses smart gate classification."""

    def test_low_and_medium_auto_approved(self, tmp_path: Path) -> None:
        """Low and medium risk tools should be auto-approved."""
        from toolwright.cli.mint import auto_approve_lockfile

        lockfile_path = tmp_path / "toolwright.lock.pending.yaml"
        manager = _create_lockfile_with_risk_tiers(lockfile_path)

        result = auto_approve_lockfile(lockfile_path)

        # Reload and check
        manager = LockfileManager(lockfile_path)
        manager.load()
        assert manager.lockfile is not None

        list_users = manager.get_tool("sig_list_users")
        get_user = manager.get_tool("sig_get_user")
        assert list_users is not None
        assert get_user is not None
        assert list_users.status == ApprovalStatus.APPROVED
        assert list_users.approved_by == "risk_policy:low"
        assert get_user.status == ApprovalStatus.APPROVED
        assert get_user.approved_by == "risk_policy:medium"

        assert result.approved_count == 2

    def test_high_and_critical_remain_pending(self, tmp_path: Path) -> None:
        """High and critical risk tools should NOT be auto-approved."""
        from toolwright.cli.mint import auto_approve_lockfile

        lockfile_path = tmp_path / "toolwright.lock.pending.yaml"
        _create_lockfile_with_risk_tiers(lockfile_path)

        auto_approve_lockfile(lockfile_path)

        manager = LockfileManager(lockfile_path)
        manager.load()
        assert manager.lockfile is not None

        update_user = manager.get_tool("sig_update_user")
        delete_user = manager.get_tool("sig_delete_user")
        assert update_user is not None
        assert delete_user is not None
        assert update_user.status == ApprovalStatus.PENDING
        assert delete_user.status == ApprovalStatus.PENDING

    def test_auto_approve_returns_counts(self, tmp_path: Path) -> None:
        """auto_approve_lockfile should return approved and pending counts."""
        from toolwright.cli.mint import auto_approve_lockfile

        lockfile_path = tmp_path / "toolwright.lock.pending.yaml"
        _create_lockfile_with_risk_tiers(lockfile_path)

        result = auto_approve_lockfile(lockfile_path)

        assert result.approved_count == 2
        assert result.pending_count == 2


# ---------------------------------------------------------------------------
# Tests: default rules application
# ---------------------------------------------------------------------------

class TestDefaultRulesApplication:
    """Test that crud-safety rules are applied by default after mint."""

    def test_crud_safety_applied_by_default(self, tmp_path: Path) -> None:
        """apply_default_rules should create crud-safety rules."""
        from toolwright.cli.mint import apply_default_rules

        rules_path = tmp_path / "rules.json"
        result = apply_default_rules(rules_path=rules_path)

        assert rules_path.exists()
        rules = json.loads(rules_path.read_text())
        assert len(rules) > 0
        assert result.rule_count > 0
        assert result.template_name == "crud-safety"

    def test_rules_not_applied_when_disabled(self, tmp_path: Path) -> None:
        """When apply_rules=False, no rules should be created."""
        from toolwright.cli.mint import apply_default_rules

        rules_path = tmp_path / "rules.json"
        result = apply_default_rules(rules_path=rules_path, apply_rules=False)

        assert not rules_path.exists()
        assert result.rule_count == 0


# ---------------------------------------------------------------------------
# Tests: example tool display
# ---------------------------------------------------------------------------

class TestExampleToolDisplay:
    """Test that post-mint output shows an example tool."""

    def test_format_example_tool(self) -> None:
        """format_example_tool should produce readable output from a tool action."""
        from toolwright.cli.mint import format_example_tool

        tool = {
            "name": "list_repos",
            "method": "GET",
            "path": "/user/repos",
            "host": "api.github.com",
            "input_schema": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "Filter by repo type"},
                    "sort": {"type": "string", "description": "Sort field"},
                },
            },
        }

        output = format_example_tool(tool)
        assert "list_repos" in output
        assert "GET" in output
        assert "/user/repos" in output
        assert "type" in output
        assert "sort" in output

    def test_format_example_tool_no_params(self) -> None:
        """format_example_tool should work with tools that have no parameters."""
        from toolwright.cli.mint import format_example_tool

        tool = {
            "name": "get_status",
            "method": "GET",
            "path": "/status",
            "host": "api.example.com",
            "input_schema": {"type": "object", "properties": {}},
        }

        output = format_example_tool(tool)
        assert "get_status" in output
        assert "GET" in output


# ---------------------------------------------------------------------------
# Tests: capture message
# ---------------------------------------------------------------------------

class TestCaptureMessage:
    """Test that the capture message sets proper expectations."""

    def test_capture_message_includes_host(self) -> None:
        """format_capture_message should include the host being captured."""
        from toolwright.cli.mint import format_capture_message

        msg = format_capture_message(["api.github.com"])
        assert "api.github.com" in msg
        assert "Browse normally" in msg

    def test_capture_message_multiple_hosts(self) -> None:
        """format_capture_message should list all hosts."""
        from toolwright.cli.mint import format_capture_message

        msg = format_capture_message(["api.github.com", "auth.github.com"])
        assert "api.github.com" in msg
        assert "auth.github.com" in msg
