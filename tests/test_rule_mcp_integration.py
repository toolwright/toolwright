"""Tests for behavioral rule engine integration with MCP server.

Tests that the CORRECT pillar's RuleEngine is wired into the MCP server
call_tool flow, blocking tool calls when rules are violated and recording
session history on successful calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolwright.core.correct.engine import RuleEngine
from toolwright.core.correct.session import SessionHistory
from toolwright.mcp.server import ToolwrightMCPServer
from toolwright.models.decision import ReasonCode
from toolwright.models.rule import RuleEvaluation, RuleKind, RuleViolation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_tools_manifest() -> dict:
    return {
        "version": "1.0.0",
        "schema_version": "1.0",
        "name": "Test Tools",
        "allowed_hosts": ["api.example.com"],
        "actions": [
            {
                "name": "get_user",
                "description": "Get user by ID",
                "method": "GET",
                "path": "/api/users/{user_id}",
                "host": "api.example.com",
                "risk_tier": "low",
                "input_schema": {
                    "type": "object",
                    "properties": {"user_id": {"type": "string"}},
                },
            },
            {
                "name": "update_user",
                "description": "Update a user",
                "method": "PUT",
                "path": "/api/users/{user_id}",
                "host": "api.example.com",
                "risk_tier": "medium",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "role": {"type": "string"},
                    },
                },
            },
            {
                "name": "delete_user",
                "description": "Delete a user",
                "method": "DELETE",
                "path": "/api/users/{user_id}",
                "host": "api.example.com",
                "risk_tier": "high",
                "input_schema": {
                    "type": "object",
                    "properties": {"user_id": {"type": "string"}},
                },
            },
        ],
    }


@pytest.fixture
def tools_file(sample_tools_manifest: dict, tmp_path: Path) -> Path:
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(json.dumps(sample_tools_manifest))
    return tools_path


def _write_rules(path: Path, rules: list[dict]) -> None:
    path.write_text(json.dumps(rules, indent=2, default=str))


def _make_server(tools_file: Path, rules_path: Path | None = None) -> ToolwrightMCPServer:
    return ToolwrightMCPServer(
        tools_path=tools_file,
        rules_path=rules_path,
    )


# ---------------------------------------------------------------------------
# Tests: server initialization with rules
# ---------------------------------------------------------------------------


class TestServerInitWithRules:
    """Test that the server initializes rule engine when rules_path provided."""

    def test_server_init_without_rules_path(self, tools_file: Path):
        """Server should work normally without rules_path (backward compatible)."""
        server = _make_server(tools_file)
        assert server.rule_engine is None
        assert server.session_history is None

    def test_server_init_with_rules_path(self, tools_file: Path, tmp_path: Path):
        """Server should initialize rule engine when rules_path provided."""
        rules_path = tmp_path / "rules.json"
        server = _make_server(tools_file, rules_path=rules_path)
        assert server.rule_engine is not None
        assert server.session_history is not None

    def test_server_init_creates_rules_file(self, tools_file: Path, tmp_path: Path):
        """rules.json should be created if it doesn't exist."""
        rules_path = tmp_path / "rules.json"
        assert not rules_path.exists()
        _make_server(tools_file, rules_path=rules_path)
        assert rules_path.exists()

    def test_server_loads_rules_from_file(self, tools_file: Path, tmp_path: Path):
        """Server should load existing rules from the rules file."""
        rules_path = tmp_path / "rules.json"
        _write_rules(rules_path, [
            {
                "rule_id": "test_rule",
                "kind": "prohibition",
                "description": "No deletes",
                "target_tool_ids": ["delete_user"],
                "config": {"always": True},
            }
        ])
        server = _make_server(tools_file, rules_path=rules_path)
        assert len(server.rule_engine.list_rules()) == 1


# ---------------------------------------------------------------------------
# Tests: rule engine integration (unit-level via direct evaluate)
# ---------------------------------------------------------------------------


class TestRuleEngineIntegration:
    """Test rule engine evaluate works correctly with server's session history."""

    def test_prerequisite_blocks_without_prior_call(self, tools_file: Path, tmp_path: Path):
        """Rule engine should block update_user if get_user wasn't called."""
        rules_path = tmp_path / "rules.json"
        _write_rules(rules_path, [
            {
                "rule_id": "prereq_get_before_update",
                "kind": "prerequisite",
                "description": "Must call get_user before update_user",
                "target_tool_ids": ["update_user"],
                "config": {"required_tool_ids": ["get_user"]},
            }
        ])
        server = _make_server(tools_file, rules_path=rules_path)

        result = server.rule_engine.evaluate(
            "update_user", "PUT", "api.example.com", {"user_id": "123"}, server.session_history
        )
        assert result.allowed is False
        assert len(result.violations) == 1
        assert result.violations[0].rule_kind == RuleKind.PREREQUISITE

    def test_prerequisite_passes_after_prior_call(self, tools_file: Path, tmp_path: Path):
        """Rule engine should allow update_user after get_user was recorded."""
        rules_path = tmp_path / "rules.json"
        _write_rules(rules_path, [
            {
                "rule_id": "prereq_get_before_update",
                "kind": "prerequisite",
                "description": "Must call get_user before update_user",
                "target_tool_ids": ["update_user"],
                "config": {"required_tool_ids": ["get_user"]},
            }
        ])
        server = _make_server(tools_file, rules_path=rules_path)

        # Simulate a successful get_user call
        server.session_history.record("get_user", "GET", "api.example.com", {"user_id": "123"}, "200")

        result = server.rule_engine.evaluate(
            "update_user", "PUT", "api.example.com", {"user_id": "123"}, server.session_history
        )
        assert result.allowed is True

    def test_prohibition_always_blocks(self, tools_file: Path, tmp_path: Path):
        """Prohibition rule with always=True should always block."""
        rules_path = tmp_path / "rules.json"
        _write_rules(rules_path, [
            {
                "rule_id": "no_delete",
                "kind": "prohibition",
                "description": "Never delete users",
                "target_tool_ids": ["delete_user"],
                "config": {"always": True},
            }
        ])
        server = _make_server(tools_file, rules_path=rules_path)

        result = server.rule_engine.evaluate(
            "delete_user", "DELETE", "api.example.com", {"user_id": "123"}, server.session_history
        )
        assert result.allowed is False

    def test_no_rules_allows_everything(self, tools_file: Path, tmp_path: Path):
        """With no rules, everything should be allowed."""
        rules_path = tmp_path / "rules.json"
        _write_rules(rules_path, [])
        server = _make_server(tools_file, rules_path=rules_path)

        result = server.rule_engine.evaluate(
            "delete_user", "DELETE", "api.example.com", {"user_id": "123"}, server.session_history
        )
        assert result.allowed is True


# ---------------------------------------------------------------------------
# Tests: session history recording
# ---------------------------------------------------------------------------


class TestSessionRecording:
    """Test that session history records calls correctly."""

    def test_session_starts_empty(self, tools_file: Path, tmp_path: Path):
        rules_path = tmp_path / "rules.json"
        server = _make_server(tools_file, rules_path=rules_path)
        assert server.session_history.call_count() == 0

    def test_manual_session_recording(self, tools_file: Path, tmp_path: Path):
        """Verify session history can track calls for rule evaluation."""
        rules_path = tmp_path / "rules.json"
        server = _make_server(tools_file, rules_path=rules_path)

        server.session_history.record("get_user", "GET", "api.example.com", {"user_id": "1"}, "200")
        server.session_history.record("update_user", "PUT", "api.example.com", {"user_id": "1"}, "200")

        assert server.session_history.call_count() == 2
        assert server.session_history.has_called("get_user")
        assert server.session_history.has_called("update_user")
        assert not server.session_history.has_called("delete_user")


# ---------------------------------------------------------------------------
# Tests: ReasonCode enum
# ---------------------------------------------------------------------------


class TestReasonCodeEnum:
    """Test that DENIED_BEHAVIORAL_RULE exists in ReasonCode."""

    def test_denied_behavioral_rule_exists(self):
        assert hasattr(ReasonCode, "DENIED_BEHAVIORAL_RULE")
        assert ReasonCode.DENIED_BEHAVIORAL_RULE == "denied_behavioral_rule"

    def test_reason_code_is_string_enum(self):
        assert isinstance(ReasonCode.DENIED_BEHAVIORAL_RULE, str)


# ---------------------------------------------------------------------------
# Tests: end-to-end flow simulation
# ---------------------------------------------------------------------------


class TestEndToEndFlow:
    """Simulate the full flow of rule enforcement as it would happen in handle_call_tool."""

    def test_full_flow_prerequisite_enforced(self, tools_file: Path, tmp_path: Path):
        """Simulate: policy allows -> rule engine blocks -> returns violation feedback."""
        rules_path = tmp_path / "rules.json"
        _write_rules(rules_path, [
            {
                "rule_id": "prereq",
                "kind": "prerequisite",
                "description": "Must call get_user before update_user",
                "target_tool_ids": ["update_user"],
                "config": {"required_tool_ids": ["get_user"]},
            }
        ])
        server = _make_server(tools_file, rules_path=rules_path)

        # Simulate handle_call_tool flow:
        # 1. Decision engine says ALLOW
        # 2. Rule engine evaluates
        tool_id = "update_user"
        method = "PUT"
        host = "api.example.com"
        params = {"user_id": "123"}

        rule_eval = server.rule_engine.evaluate(
            tool_id, method, host, params, server.session_history
        )

        # Should be blocked
        assert not rule_eval.allowed
        assert "Blocked" in rule_eval.feedback
        assert len(rule_eval.violations) == 1

        # Now simulate get_user success
        server.session_history.record("get_user", "GET", host, {"user_id": "123"}, "200")

        # Re-evaluate: should pass now
        rule_eval2 = server.rule_engine.evaluate(
            tool_id, method, host, params, server.session_history
        )
        assert rule_eval2.allowed
        assert rule_eval2.feedback == ""

    def test_full_flow_multiple_rules(self, tools_file: Path, tmp_path: Path):
        """Test with multiple rules: prerequisite + parameter constraint."""
        rules_path = tmp_path / "rules.json"
        _write_rules(rules_path, [
            {
                "rule_id": "prereq",
                "kind": "prerequisite",
                "description": "Must call get_user first",
                "target_tool_ids": ["update_user"],
                "config": {"required_tool_ids": ["get_user"]},
            },
            {
                "rule_id": "param",
                "kind": "parameter",
                "description": "Role must be user or moderator",
                "target_tool_ids": ["update_user"],
                "config": {"param_name": "role", "allowed_values": ["user", "moderator"]},
            },
        ])
        server = _make_server(tools_file, rules_path=rules_path)

        # Both violations
        result = server.rule_engine.evaluate(
            "update_user", "PUT", "api.example.com",
            {"user_id": "123", "role": "admin"},
            server.session_history,
        )
        assert not result.allowed
        assert len(result.violations) == 2

        # Fix prerequisite, still bad param
        server.session_history.record("get_user", "GET", "api.example.com", {}, "200")
        result2 = server.rule_engine.evaluate(
            "update_user", "PUT", "api.example.com",
            {"user_id": "123", "role": "admin"},
            server.session_history,
        )
        assert not result2.allowed
        assert len(result2.violations) == 1
        assert result2.violations[0].rule_kind == RuleKind.PARAMETER

        # Fix both
        result3 = server.rule_engine.evaluate(
            "update_user", "PUT", "api.example.com",
            {"user_id": "123", "role": "user"},
            server.session_history,
        )
        assert result3.allowed
