"""Tests for the CORRECT pillar rule engine.

Tests the RuleEngine class that evaluates behavioral rules against
tool calls, manages rule CRUD, and supports hot-reload from JSON.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from toolwright.core.correct.session import SessionHistory
from toolwright.models.rule import (
    ApprovalConfig,
    BehavioralRule,
    ParameterConfig,
    PrerequisiteConfig,
    ProhibitionConfig,
    RuleKind,
    SequenceConfig,
    SessionRateConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rule(
    rule_id: str = "r1",
    kind: RuleKind = RuleKind.PREREQUISITE,
    description: str = "test rule",
    target_tool_ids: list[str] | None = None,
    target_methods: list[str] | None = None,
    target_hosts: list[str] | None = None,
    config: dict | None = None,
    enabled: bool = True,
    priority: int = 100,
) -> BehavioralRule:
    """Build a BehavioralRule with sensible defaults."""
    if config is None:
        config = {"required_tool_ids": ["get_user"]}
    return BehavioralRule(
        rule_id=rule_id,
        kind=kind,
        description=description,
        target_tool_ids=target_tool_ids or [],
        target_methods=target_methods or [],
        target_hosts=target_hosts or [],
        config=config,
        enabled=enabled,
        priority=priority,
    )


def _write_rules(path: Path, rules: list[BehavioralRule]) -> None:
    """Serialize rules to a JSON file."""
    data = [r.model_dump(mode="json") for r in rules]
    path.write_text(json.dumps(data, indent=2, default=str))


def _engine_with_rules(tmp_path: Path, rules: list[BehavioralRule]):
    """Create a RuleEngine with the given rules persisted to tmp_path."""
    from toolwright.core.correct.engine import RuleEngine

    rules_file = tmp_path / "rules.json"
    _write_rules(rules_file, rules)
    return RuleEngine(rules_path=rules_file)


# ---------------------------------------------------------------------------
# Tests: initialization and loading
# ---------------------------------------------------------------------------


class TestRuleEngineInit:
    """Test engine initialization and rule loading."""

    def test_init_creates_empty_file_if_missing(self, tmp_path: Path):
        from toolwright.core.correct.engine import RuleEngine

        rules_file = tmp_path / "rules.json"
        engine = RuleEngine(rules_path=rules_file)
        assert rules_file.exists()
        assert engine.list_rules() == []

    def test_init_loads_existing_rules(self, tmp_path: Path):
        rule = _make_rule("r1", RuleKind.PREREQUISITE, config={"required_tool_ids": ["a"]})
        engine = _engine_with_rules(tmp_path, [rule])
        assert len(engine.list_rules()) == 1
        assert engine.list_rules()[0].rule_id == "r1"

    def test_init_loads_multiple_rules(self, tmp_path: Path):
        rules = [
            _make_rule("r1", RuleKind.PREREQUISITE, config={"required_tool_ids": ["a"]}),
            _make_rule("r2", RuleKind.PROHIBITION, config={"always": True}),
        ]
        engine = _engine_with_rules(tmp_path, rules)
        assert len(engine.list_rules()) == 2


# ---------------------------------------------------------------------------
# Tests: CRUD operations
# ---------------------------------------------------------------------------


class TestRuleEngineCRUD:
    """Test add, remove, update, get, list operations."""

    def test_add_rule(self, tmp_path: Path):
        from toolwright.core.correct.engine import RuleEngine

        rules_file = tmp_path / "rules.json"
        engine = RuleEngine(rules_path=rules_file)
        rule = _make_rule("new1", RuleKind.PROHIBITION, config={"always": True})
        engine.add_rule(rule)

        assert len(engine.list_rules()) == 1
        assert engine.get_rule("new1") is not None

    def test_add_rule_persists_to_disk(self, tmp_path: Path):
        from toolwright.core.correct.engine import RuleEngine

        rules_file = tmp_path / "rules.json"
        engine = RuleEngine(rules_path=rules_file)
        rule = _make_rule("persisted", RuleKind.PROHIBITION, config={"always": True})
        engine.add_rule(rule)

        # Reload from disk
        engine2 = RuleEngine(rules_path=rules_file)
        assert engine2.get_rule("persisted") is not None

    def test_add_duplicate_rule_id_raises(self, tmp_path: Path):
        from toolwright.core.correct.engine import RuleEngine

        rules_file = tmp_path / "rules.json"
        engine = RuleEngine(rules_path=rules_file)
        rule = _make_rule("dup", RuleKind.PROHIBITION, config={"always": True})
        engine.add_rule(rule)
        with pytest.raises(ValueError, match="already exists"):
            engine.add_rule(rule)

    def test_remove_rule(self, tmp_path: Path):
        rule = _make_rule("to_remove", RuleKind.PROHIBITION, config={"always": True})
        engine = _engine_with_rules(tmp_path, [rule])
        engine.remove_rule("to_remove")
        assert engine.get_rule("to_remove") is None
        assert len(engine.list_rules()) == 0

    def test_remove_missing_rule_raises(self, tmp_path: Path):
        from toolwright.core.correct.engine import RuleEngine

        rules_file = tmp_path / "rules.json"
        engine = RuleEngine(rules_path=rules_file)
        with pytest.raises(KeyError, match="not found"):
            engine.remove_rule("nonexistent")

    def test_update_rule(self, tmp_path: Path):
        rule = _make_rule("upd", RuleKind.PROHIBITION, config={"always": True}, description="old")
        engine = _engine_with_rules(tmp_path, [rule])
        engine.update_rule("upd", description="new desc", enabled=False)
        updated = engine.get_rule("upd")
        assert updated.description == "new desc"
        assert updated.enabled is False

    def test_update_missing_rule_raises(self, tmp_path: Path):
        from toolwright.core.correct.engine import RuleEngine

        rules_file = tmp_path / "rules.json"
        engine = RuleEngine(rules_path=rules_file)
        with pytest.raises(KeyError, match="not found"):
            engine.update_rule("ghost", description="nope")

    def test_get_rule_returns_none_for_missing(self, tmp_path: Path):
        from toolwright.core.correct.engine import RuleEngine

        rules_file = tmp_path / "rules.json"
        engine = RuleEngine(rules_path=rules_file)
        assert engine.get_rule("nope") is None

    def test_list_rules_returns_all(self, tmp_path: Path):
        rules = [
            _make_rule("a", RuleKind.PROHIBITION, config={"always": True}),
            _make_rule("b", RuleKind.PREREQUISITE, config={"required_tool_ids": ["x"]}),
            _make_rule("c", RuleKind.RATE, config={"max_calls": 5}),
        ]
        engine = _engine_with_rules(tmp_path, rules)
        assert len(engine.list_rules()) == 3


# ---------------------------------------------------------------------------
# Tests: applicable rule filtering
# ---------------------------------------------------------------------------


class TestApplicableRules:
    """Test that rules are filtered by target and sorted by priority."""

    def test_rule_matches_target_tool_id(self, tmp_path: Path):
        rule = _make_rule(
            "r1",
            RuleKind.PROHIBITION,
            config={"always": True},
            target_tool_ids=["delete_user"],
        )
        engine = _engine_with_rules(tmp_path, [rule])
        applicable = engine._applicable_rules("delete_user", "DELETE", "api.example.com")
        assert len(applicable) == 1

    def test_rule_does_not_match_wrong_tool(self, tmp_path: Path):
        rule = _make_rule(
            "r1",
            RuleKind.PROHIBITION,
            config={"always": True},
            target_tool_ids=["delete_user"],
        )
        engine = _engine_with_rules(tmp_path, [rule])
        applicable = engine._applicable_rules("get_user", "GET", "api.example.com")
        assert len(applicable) == 0

    def test_rule_with_empty_targets_matches_all(self, tmp_path: Path):
        rule = _make_rule(
            "r1",
            RuleKind.PROHIBITION,
            config={"always": True},
            target_tool_ids=[],
        )
        engine = _engine_with_rules(tmp_path, [rule])
        applicable = engine._applicable_rules("any_tool", "GET", "any.host")
        assert len(applicable) == 1

    def test_disabled_rules_excluded(self, tmp_path: Path):
        rule = _make_rule(
            "r1",
            RuleKind.PROHIBITION,
            config={"always": True},
            enabled=False,
        )
        engine = _engine_with_rules(tmp_path, [rule])
        applicable = engine._applicable_rules("any_tool", "GET", "any.host")
        assert len(applicable) == 0

    def test_rules_sorted_by_priority(self, tmp_path: Path):
        rules = [
            _make_rule("low", RuleKind.PROHIBITION, config={"always": True}, priority=200),
            _make_rule("high", RuleKind.PROHIBITION, config={"always": True}, priority=50),
            _make_rule("mid", RuleKind.PROHIBITION, config={"always": True}, priority=100),
        ]
        engine = _engine_with_rules(tmp_path, rules)
        applicable = engine._applicable_rules("any", "GET", "host")
        assert [r.rule_id for r in applicable] == ["high", "mid", "low"]

    def test_method_filter(self, tmp_path: Path):
        rule = _make_rule(
            "r1",
            RuleKind.PROHIBITION,
            config={"always": True},
            target_methods=["DELETE"],
        )
        engine = _engine_with_rules(tmp_path, [rule])
        assert len(engine._applicable_rules("tool", "DELETE", "host")) == 1
        assert len(engine._applicable_rules("tool", "GET", "host")) == 0

    def test_host_filter(self, tmp_path: Path):
        rule = _make_rule(
            "r1",
            RuleKind.PROHIBITION,
            config={"always": True},
            target_hosts=["api.prod.com"],
        )
        engine = _engine_with_rules(tmp_path, [rule])
        assert len(engine._applicable_rules("tool", "GET", "api.prod.com")) == 1
        assert len(engine._applicable_rules("tool", "GET", "api.dev.com")) == 0


# ---------------------------------------------------------------------------
# Tests: prerequisite evaluator
# ---------------------------------------------------------------------------


class TestPrerequisiteEvaluation:
    """Test prerequisite rule evaluation."""

    def test_prerequisite_passes_when_met(self, tmp_path: Path):
        rule = _make_rule(
            "prereq1",
            RuleKind.PREREQUISITE,
            description="Must call get_user before update_user",
            target_tool_ids=["update_user"],
            config={"required_tool_ids": ["get_user"]},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()
        session.record("get_user", "GET", "api.com", {}, "ok")

        result = engine.evaluate("update_user", "PUT", "api.com", {}, session)
        assert result.allowed is True
        assert len(result.violations) == 0

    def test_prerequisite_fails_when_not_met(self, tmp_path: Path):
        rule = _make_rule(
            "prereq1",
            RuleKind.PREREQUISITE,
            description="Must call get_user before update_user",
            target_tool_ids=["update_user"],
            config={"required_tool_ids": ["get_user"]},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()

        result = engine.evaluate("update_user", "PUT", "api.com", {}, session)
        assert result.allowed is False
        assert len(result.violations) == 1
        assert result.violations[0].rule_kind == RuleKind.PREREQUISITE

    def test_prerequisite_with_required_args(self, tmp_path: Path):
        rule = _make_rule(
            "prereq_args",
            RuleKind.PREREQUISITE,
            description="Must call get_user with id param",
            target_tool_ids=["update_user"],
            config={
                "required_tool_ids": ["get_user"],
                "required_args": {"user_id": "123"},
            },
        )
        engine = _engine_with_rules(tmp_path, [rule])

        # Called get_user but without the required args
        session = SessionHistory()
        session.record("get_user", "GET", "api.com", {"user_id": "999"}, "ok")
        result = engine.evaluate("update_user", "PUT", "api.com", {}, session)
        assert result.allowed is False

        # Called get_user with the required args
        session2 = SessionHistory()
        session2.record("get_user", "GET", "api.com", {"user_id": "123"}, "ok")
        result2 = engine.evaluate("update_user", "PUT", "api.com", {}, session2)
        assert result2.allowed is True

    def test_multiple_prerequisites(self, tmp_path: Path):
        rule = _make_rule(
            "prereq_multi",
            RuleKind.PREREQUISITE,
            description="Must call auth and get_user",
            target_tool_ids=["update_user"],
            config={"required_tool_ids": ["authenticate", "get_user"]},
        )
        engine = _engine_with_rules(tmp_path, [rule])

        # Only called one prerequisite
        session = SessionHistory()
        session.record("authenticate", "POST", "api.com", {}, "ok")
        result = engine.evaluate("update_user", "PUT", "api.com", {}, session)
        assert result.allowed is False

        # Called both
        session.record("get_user", "GET", "api.com", {}, "ok")
        result2 = engine.evaluate("update_user", "PUT", "api.com", {}, session)
        assert result2.allowed is True


# ---------------------------------------------------------------------------
# Tests: prohibition evaluator
# ---------------------------------------------------------------------------


class TestProhibitionEvaluation:
    """Test prohibition rule evaluation."""

    def test_always_prohibited(self, tmp_path: Path):
        rule = _make_rule(
            "no_delete",
            RuleKind.PROHIBITION,
            description="Never delete users",
            target_tool_ids=["delete_user"],
            config={"always": True},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()

        result = engine.evaluate("delete_user", "DELETE", "api.com", {}, session)
        assert result.allowed is False
        assert result.violations[0].rule_kind == RuleKind.PROHIBITION

    def test_prohibited_after_specific_tool(self, tmp_path: Path):
        rule = _make_rule(
            "no_delete_after_create",
            RuleKind.PROHIBITION,
            description="Cannot delete after create in same session",
            target_tool_ids=["delete_user"],
            config={"after_tool_ids": ["create_user"]},
        )
        engine = _engine_with_rules(tmp_path, [rule])

        # Without prior create_user: allowed
        session = SessionHistory()
        result = engine.evaluate("delete_user", "DELETE", "api.com", {}, session)
        assert result.allowed is True

        # With prior create_user: blocked
        session.record("create_user", "POST", "api.com", {}, "ok")
        result2 = engine.evaluate("delete_user", "DELETE", "api.com", {}, session)
        assert result2.allowed is False

    def test_prohibition_not_always_allows_when_no_trigger(self, tmp_path: Path):
        rule = _make_rule(
            "conditional",
            RuleKind.PROHIBITION,
            description="Conditional prohibition",
            target_tool_ids=["tool_a"],
            config={"after_tool_ids": ["trigger_tool"], "always": False},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()

        result = engine.evaluate("tool_a", "GET", "api.com", {}, session)
        assert result.allowed is True


# ---------------------------------------------------------------------------
# Tests: parameter evaluator
# ---------------------------------------------------------------------------


class TestParameterEvaluation:
    """Test parameter constraint evaluation."""

    def test_allowed_values_pass(self, tmp_path: Path):
        rule = _make_rule(
            "param_allow",
            RuleKind.PARAMETER,
            description="Status must be active or inactive",
            target_tool_ids=["update_user"],
            config={"param_name": "status", "allowed_values": ["active", "inactive"]},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()

        result = engine.evaluate("update_user", "PUT", "api.com", {"status": "active"}, session)
        assert result.allowed is True

    def test_allowed_values_fail(self, tmp_path: Path):
        rule = _make_rule(
            "param_allow",
            RuleKind.PARAMETER,
            description="Status must be active or inactive",
            target_tool_ids=["update_user"],
            config={"param_name": "status", "allowed_values": ["active", "inactive"]},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()

        result = engine.evaluate("update_user", "PUT", "api.com", {"status": "banned"}, session)
        assert result.allowed is False
        assert result.violations[0].rule_kind == RuleKind.PARAMETER

    def test_blocked_values(self, tmp_path: Path):
        rule = _make_rule(
            "param_block",
            RuleKind.PARAMETER,
            description="Cannot use admin role",
            target_tool_ids=["update_user"],
            config={"param_name": "role", "blocked_values": ["admin", "superadmin"]},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()

        result = engine.evaluate("update_user", "PUT", "api.com", {"role": "admin"}, session)
        assert result.allowed is False

        result2 = engine.evaluate("update_user", "PUT", "api.com", {"role": "user"}, session)
        assert result2.allowed is True

    def test_max_value(self, tmp_path: Path):
        rule = _make_rule(
            "param_max",
            RuleKind.PARAMETER,
            description="Limit must be <= 100",
            target_tool_ids=["search"],
            config={"param_name": "limit", "max_value": 100},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()

        result = engine.evaluate("search", "GET", "api.com", {"limit": 50}, session)
        assert result.allowed is True

        result2 = engine.evaluate("search", "GET", "api.com", {"limit": 200}, session)
        assert result2.allowed is False

    def test_min_value(self, tmp_path: Path):
        rule = _make_rule(
            "param_min",
            RuleKind.PARAMETER,
            description="Page must be >= 1",
            target_tool_ids=["search"],
            config={"param_name": "page", "min_value": 1},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()

        result = engine.evaluate("search", "GET", "api.com", {"page": 0}, session)
        assert result.allowed is False

        result2 = engine.evaluate("search", "GET", "api.com", {"page": 1}, session)
        assert result2.allowed is True

    def test_pattern(self, tmp_path: Path):
        rule = _make_rule(
            "param_regex",
            RuleKind.PARAMETER,
            description="Email must be valid format",
            target_tool_ids=["update_user"],
            config={"param_name": "email", "pattern": r"^[^@]+@[^@]+\.[^@]+$"},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()

        result = engine.evaluate(
            "update_user", "PUT", "api.com", {"email": "user@example.com"}, session
        )
        assert result.allowed is True

        result2 = engine.evaluate(
            "update_user", "PUT", "api.com", {"email": "not-an-email"}, session
        )
        assert result2.allowed is False

    def test_missing_param_passes(self, tmp_path: Path):
        """If the param isn't in the call, rule doesn't apply."""
        rule = _make_rule(
            "param_allow",
            RuleKind.PARAMETER,
            description="Status must be active or inactive",
            target_tool_ids=["update_user"],
            config={"param_name": "status", "allowed_values": ["active", "inactive"]},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()

        result = engine.evaluate("update_user", "PUT", "api.com", {"name": "Alice"}, session)
        assert result.allowed is True


# ---------------------------------------------------------------------------
# Tests: sequence evaluator
# ---------------------------------------------------------------------------


class TestSequenceEvaluation:
    """Test sequence rule evaluation."""

    def test_correct_order_passes(self, tmp_path: Path):
        rule = _make_rule(
            "seq1",
            RuleKind.SEQUENCE,
            description="Must follow auth -> get -> update order",
            target_tool_ids=["update_user"],
            config={"required_order": ["authenticate", "get_user", "update_user"]},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()
        session.record("authenticate", "POST", "api.com", {}, "ok")
        session.record("get_user", "GET", "api.com", {}, "ok")

        result = engine.evaluate("update_user", "PUT", "api.com", {}, session)
        assert result.allowed is True

    def test_wrong_order_fails(self, tmp_path: Path):
        rule = _make_rule(
            "seq1",
            RuleKind.SEQUENCE,
            description="Must follow auth -> get -> update order",
            target_tool_ids=["update_user"],
            config={"required_order": ["authenticate", "get_user", "update_user"]},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()
        # Wrong order: get_user before authenticate
        session.record("get_user", "GET", "api.com", {}, "ok")
        session.record("authenticate", "POST", "api.com", {}, "ok")

        result = engine.evaluate("update_user", "PUT", "api.com", {}, session)
        assert result.allowed is False
        assert result.violations[0].rule_kind == RuleKind.SEQUENCE

    def test_missing_step_fails(self, tmp_path: Path):
        rule = _make_rule(
            "seq1",
            RuleKind.SEQUENCE,
            description="Must follow auth -> get -> update order",
            target_tool_ids=["update_user"],
            config={"required_order": ["authenticate", "get_user", "update_user"]},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()
        session.record("authenticate", "POST", "api.com", {}, "ok")
        # Missing get_user

        result = engine.evaluate("update_user", "PUT", "api.com", {}, session)
        assert result.allowed is False

    def test_non_strict_allows_interleaved_calls(self, tmp_path: Path):
        """Non-strict sequence: other calls can appear between required ones."""
        rule = _make_rule(
            "seq_relaxed",
            RuleKind.SEQUENCE,
            description="Must do A then B (non-strict)",
            target_tool_ids=["tool_b"],
            config={"required_order": ["tool_a", "tool_b"]},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()
        session.record("tool_a", "GET", "api.com", {}, "ok")
        session.record("other_tool", "GET", "api.com", {}, "ok")  # interleaved

        result = engine.evaluate("tool_b", "GET", "api.com", {}, session)
        assert result.allowed is True


# ---------------------------------------------------------------------------
# Tests: rate evaluator
# ---------------------------------------------------------------------------


class TestRateEvaluation:
    """Test rate limit rule evaluation."""

    def test_under_limit_passes(self, tmp_path: Path):
        rule = _make_rule(
            "rate1",
            RuleKind.RATE,
            description="Max 3 calls",
            target_tool_ids=["search"],
            config={"max_calls": 3, "per_tool": True},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()
        session.record("search", "GET", "api.com", {}, "ok")
        session.record("search", "GET", "api.com", {}, "ok")

        result = engine.evaluate("search", "GET", "api.com", {}, session)
        assert result.allowed is True

    def test_at_limit_fails(self, tmp_path: Path):
        rule = _make_rule(
            "rate1",
            RuleKind.RATE,
            description="Max 3 calls",
            target_tool_ids=["search"],
            config={"max_calls": 3, "per_tool": True},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()
        session.record("search", "GET", "api.com", {}, "ok")
        session.record("search", "GET", "api.com", {}, "ok")
        session.record("search", "GET", "api.com", {}, "ok")

        result = engine.evaluate("search", "GET", "api.com", {}, session)
        assert result.allowed is False
        assert result.violations[0].rule_kind == RuleKind.RATE

    def test_global_rate_counts_all_tools(self, tmp_path: Path):
        rule = _make_rule(
            "rate_global",
            RuleKind.RATE,
            description="Max 3 calls total",
            config={"max_calls": 3, "per_tool": False},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()
        session.record("tool_a", "GET", "api.com", {}, "ok")
        session.record("tool_b", "GET", "api.com", {}, "ok")
        session.record("tool_c", "GET", "api.com", {}, "ok")

        result = engine.evaluate("tool_d", "GET", "api.com", {}, session)
        assert result.allowed is False

    def test_windowed_rate_limit(self, tmp_path: Path):
        rule = _make_rule(
            "rate_windowed",
            RuleKind.RATE,
            description="Max 2 calls in 1 second",
            target_tool_ids=["search"],
            config={"max_calls": 2, "window_seconds": 1, "per_tool": True},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()
        session.record("search", "GET", "api.com", {}, "ok")
        session.record("search", "GET", "api.com", {}, "ok")

        result = engine.evaluate("search", "GET", "api.com", {}, session)
        assert result.allowed is False


# ---------------------------------------------------------------------------
# Tests: approval evaluator
# ---------------------------------------------------------------------------


class TestApprovalEvaluation:
    """Test approval rule evaluation."""

    def test_approval_required_when_param_matches(self, tmp_path: Path):
        rule = _make_rule(
            "approval1",
            RuleKind.APPROVAL,
            description="Approval needed for admin role",
            target_tool_ids=["update_user"],
            config={
                "when_param_matches": {"role": "admin"},
                "approval_message": "Changing role to admin requires approval.",
            },
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()

        result = engine.evaluate("update_user", "PUT", "api.com", {"role": "admin"}, session)
        assert result.allowed is False
        assert result.violations[0].rule_kind == RuleKind.APPROVAL
        assert "approval" in result.violations[0].description.lower()

    def test_approval_not_needed_when_param_doesnt_match(self, tmp_path: Path):
        rule = _make_rule(
            "approval1",
            RuleKind.APPROVAL,
            description="Approval needed for admin role",
            target_tool_ids=["update_user"],
            config={
                "when_param_matches": {"role": "admin"},
                "approval_message": "Changing role to admin requires approval.",
            },
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()

        result = engine.evaluate("update_user", "PUT", "api.com", {"role": "user"}, session)
        assert result.allowed is True

    def test_approval_after_tool(self, tmp_path: Path):
        rule = _make_rule(
            "approval_after",
            RuleKind.APPROVAL,
            description="Approval needed after delete attempt",
            target_tool_ids=["create_user"],
            config={
                "when_after_tool": "delete_user",
                "approval_message": "Creating user after deletion requires approval.",
            },
        )
        engine = _engine_with_rules(tmp_path, [rule])

        session = SessionHistory()
        result = engine.evaluate("create_user", "POST", "api.com", {}, session)
        assert result.allowed is True

        session.record("delete_user", "DELETE", "api.com", {}, "ok")
        result2 = engine.evaluate("create_user", "POST", "api.com", {}, session)
        assert result2.allowed is False


# ---------------------------------------------------------------------------
# Tests: combined evaluation
# ---------------------------------------------------------------------------


class TestCombinedEvaluation:
    """Test evaluation with multiple rules."""

    def test_multiple_violations_collected(self, tmp_path: Path):
        rules = [
            _make_rule(
                "prereq",
                RuleKind.PREREQUISITE,
                description="Must call auth first",
                target_tool_ids=["update_user"],
                config={"required_tool_ids": ["authenticate"]},
            ),
            _make_rule(
                "param",
                RuleKind.PARAMETER,
                description="Role must be user or moderator",
                target_tool_ids=["update_user"],
                config={"param_name": "role", "allowed_values": ["user", "moderator"]},
            ),
        ]
        engine = _engine_with_rules(tmp_path, rules)
        session = SessionHistory()

        # Both rules violated
        result = engine.evaluate("update_user", "PUT", "api.com", {"role": "admin"}, session)
        assert result.allowed is False
        assert len(result.violations) == 2

    def test_no_rules_means_allowed(self, tmp_path: Path):
        from toolwright.core.correct.engine import RuleEngine

        rules_file = tmp_path / "rules.json"
        engine = RuleEngine(rules_path=rules_file)
        session = SessionHistory()

        result = engine.evaluate("any_tool", "GET", "api.com", {}, session)
        assert result.allowed is True
        assert len(result.violations) == 0

    def test_feedback_included_in_evaluation(self, tmp_path: Path):
        rule = _make_rule(
            "prereq",
            RuleKind.PREREQUISITE,
            description="Must call auth first",
            target_tool_ids=["update_user"],
            config={"required_tool_ids": ["authenticate"]},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()

        result = engine.evaluate("update_user", "PUT", "api.com", {}, session)
        assert result.feedback != ""
        assert "Blocked" in result.feedback

    def test_allowed_result_has_empty_feedback(self, tmp_path: Path):
        rule = _make_rule(
            "prereq",
            RuleKind.PREREQUISITE,
            description="Must call auth first",
            target_tool_ids=["update_user"],
            config={"required_tool_ids": ["authenticate"]},
        )
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()
        session.record("authenticate", "POST", "api.com", {}, "ok")

        result = engine.evaluate("update_user", "PUT", "api.com", {}, session)
        assert result.feedback == ""


# ---------------------------------------------------------------------------
# Tests: hot-reload
# ---------------------------------------------------------------------------


class TestHotReload:
    """Test that the engine detects file changes and reloads rules."""

    def test_hot_reload_detects_new_rule(self, tmp_path: Path):
        from toolwright.core.correct.engine import RuleEngine

        rules_file = tmp_path / "rules.json"
        engine = RuleEngine(rules_path=rules_file)
        assert len(engine.list_rules()) == 0

        # Write a rule to disk externally
        time.sleep(0.05)  # ensure mtime differs
        rule = _make_rule("hot1", RuleKind.PROHIBITION, config={"always": True})
        _write_rules(rules_file, [rule])

        # Engine should detect the change on next evaluate
        session = SessionHistory()
        engine.evaluate("any", "GET", "host", {}, session)
        assert len(engine.list_rules()) == 1
