"""Tests for behavioral rule models."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from toolwright.models.rule import (
    ApprovalConfig,
    BehavioralRule,
    ParameterConfig,
    PrerequisiteConfig,
    ProhibitionConfig,
    RuleConflict,
    RuleEvaluation,
    RuleKind,
    RuleStatus,
    RuleViolation,
    SequenceConfig,
    SessionRateConfig,
)

# ---------------------------------------------------------------------------
# RuleKind enum
# ---------------------------------------------------------------------------


class TestRuleKind:
    def test_all_kinds_exist(self) -> None:
        assert RuleKind.PREREQUISITE == "prerequisite"
        assert RuleKind.PROHIBITION == "prohibition"
        assert RuleKind.PARAMETER == "parameter"
        assert RuleKind.SEQUENCE == "sequence"
        assert RuleKind.RATE == "rate"
        assert RuleKind.APPROVAL == "approval"

    def test_kind_count(self) -> None:
        assert len(RuleKind) == 6


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------


class TestPrerequisiteConfig:
    def test_basic_construction(self) -> None:
        cfg = PrerequisiteConfig(required_tool_ids=["get_user"])
        assert cfg.required_tool_ids == ["get_user"]
        assert cfg.required_args == {}

    def test_with_args(self) -> None:
        cfg = PrerequisiteConfig(
            required_tool_ids=["get_user"],
            required_args={"user_id": "123"},
        )
        assert cfg.required_args == {"user_id": "123"}


class TestProhibitionConfig:
    def test_always_prohibition(self) -> None:
        cfg = ProhibitionConfig(always=True)
        assert cfg.always is True
        assert cfg.after_tool_ids == []

    def test_conditional_prohibition(self) -> None:
        cfg = ProhibitionConfig(
            after_tool_ids=["delete_user"],
        )
        assert cfg.after_tool_ids == ["delete_user"]


class TestParameterConfig:
    def test_allowed_values(self) -> None:
        cfg = ParameterConfig(param_name="status", allowed_values=["active", "inactive"])
        assert cfg.param_name == "status"
        assert cfg.allowed_values == ["active", "inactive"]

    def test_range_values(self) -> None:
        cfg = ParameterConfig(param_name="limit", min_value=1, max_value=100)
        assert cfg.min_value == 1
        assert cfg.max_value == 100

    def test_pattern(self) -> None:
        cfg = ParameterConfig(param_name="email", pattern=r"^[^@]+@[^@]+\.[^@]+$")
        assert cfg.pattern is not None

    def test_blocked_values(self) -> None:
        cfg = ParameterConfig(param_name="role", blocked_values=["admin", "root"])
        assert cfg.blocked_values == ["admin", "root"]


class TestSequenceConfig:
    def test_basic(self) -> None:
        cfg = SequenceConfig(required_order=["list_users", "get_user", "update_user"])
        assert len(cfg.required_order) == 3


class TestSessionRateConfig:
    def test_basic(self) -> None:
        cfg = SessionRateConfig(max_calls=10)
        assert cfg.max_calls == 10
        assert cfg.window_seconds is None
        assert cfg.per_tool is True  # default

    def test_with_window(self) -> None:
        cfg = SessionRateConfig(max_calls=5, window_seconds=60)
        assert cfg.window_seconds == 60


class TestApprovalConfig:
    def test_basic(self) -> None:
        cfg = ApprovalConfig(approval_message="Are you sure?")
        assert cfg.approval_message == "Are you sure?"
        assert cfg.when_param_matches == {}


# ---------------------------------------------------------------------------
# BehavioralRule
# ---------------------------------------------------------------------------


class TestBehavioralRule:
    def test_prerequisite_rule(self) -> None:
        rule = BehavioralRule(
            rule_id="rule_001",
            kind=RuleKind.PREREQUISITE,
            description="Must fetch user before updating",
            target_tool_ids=["update_user"],
            config=PrerequisiteConfig(required_tool_ids=["get_user"]),
        )
        assert rule.rule_id == "rule_001"
        assert rule.kind == RuleKind.PREREQUISITE
        assert rule.status == RuleStatus.ACTIVE  # default
        assert rule.priority == 100  # default
        assert isinstance(rule.config, PrerequisiteConfig)

    def test_prohibition_rule(self) -> None:
        rule = BehavioralRule(
            rule_id="rule_002",
            kind=RuleKind.PROHIBITION,
            description="Never delete after error",
            target_tool_ids=["delete_user"],
            config=ProhibitionConfig(
                after_tool_ids=["update_user"],
            ),
        )
        assert rule.kind == RuleKind.PROHIBITION

    def test_parameter_rule(self) -> None:
        rule = BehavioralRule(
            rule_id="rule_003",
            kind=RuleKind.PARAMETER,
            description="Limit must be between 1 and 100",
            target_tool_ids=["list_items"],
            config=ParameterConfig(param_name="limit", min_value=1, max_value=100),
        )
        assert rule.kind == RuleKind.PARAMETER

    def test_created_at_defaults_to_now(self) -> None:
        rule = BehavioralRule(
            rule_id="rule_x",
            kind=RuleKind.RATE,
            description="Rate limit",
            config=SessionRateConfig(max_calls=10),
        )
        assert rule.created_at is not None
        assert isinstance(rule.created_at, datetime)

    def test_target_methods_and_hosts(self) -> None:
        rule = BehavioralRule(
            rule_id="rule_y",
            kind=RuleKind.PROHIBITION,
            description="No DELETEs to api.example.com",
            target_methods=["DELETE"],
            target_hosts=["api.example.com"],
            config=ProhibitionConfig(always=True),
        )
        assert rule.target_methods == ["DELETE"]
        assert rule.target_hosts == ["api.example.com"]

    def test_serialization_roundtrip(self) -> None:
        rule = BehavioralRule(
            rule_id="rule_rt",
            kind=RuleKind.PREREQUISITE,
            description="Test roundtrip",
            target_tool_ids=["update_user"],
            config=PrerequisiteConfig(required_tool_ids=["get_user"]),
            created_at=datetime(2026, 2, 26, tzinfo=UTC),
        )
        data = rule.model_dump(mode="json")
        restored = BehavioralRule.model_validate(data)
        assert restored.rule_id == rule.rule_id
        assert restored.kind == rule.kind
        assert isinstance(restored.config, PrerequisiteConfig)
        assert restored.config.required_tool_ids == ["get_user"]

    def test_json_serialization(self) -> None:
        rule = BehavioralRule(
            rule_id="rule_json",
            kind=RuleKind.PARAMETER,
            description="JSON test",
            config=ParameterConfig(param_name="x", allowed_values=[1, 2, 3]),
            created_at=datetime(2026, 2, 26, tzinfo=UTC),
        )
        json_str = rule.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["rule_id"] == "rule_json"
        assert parsed["kind"] == "parameter"


# ---------------------------------------------------------------------------
# RuleViolation & RuleEvaluation
# ---------------------------------------------------------------------------


class TestRuleViolation:
    def test_construction(self) -> None:
        v = RuleViolation(
            rule_id="rule_001",
            rule_kind=RuleKind.PREREQUISITE,
            tool_id="update_user",
            description="Must call get_user first",
            feedback="Call get_user before update_user.",
            suggestion="Call get_user first.",
        )
        assert v.rule_id == "rule_001"
        assert v.severity == "error"  # default

    def test_warning_severity(self) -> None:
        v = RuleViolation(
            rule_id="rule_002",
            rule_kind=RuleKind.RATE,
            tool_id="list_items",
            description="Approaching rate limit",
            feedback="Slow down.",
            severity="warning",
        )
        assert v.severity == "warning"


class TestRuleEvaluation:
    def test_allowed(self) -> None:
        ev = RuleEvaluation(allowed=True, violations=[], feedback="")
        assert ev.allowed is True
        assert len(ev.violations) == 0

    def test_blocked_with_violations(self) -> None:
        v = RuleViolation(
            rule_id="r1",
            rule_kind=RuleKind.PREREQUISITE,
            tool_id="update_user",
            description="Missing prerequisite",
            feedback="Call get_user first.",
        )
        ev = RuleEvaluation(
            allowed=False,
            violations=[v],
            feedback="Blocked: 1 violation.",
        )
        assert ev.allowed is False
        assert len(ev.violations) == 1


class TestRuleConflict:
    def test_construction(self) -> None:
        c = RuleConflict(
            rule_a_id="r1",
            rule_b_id="r2",
            conflict_type="circular_dependency",
            description="r1 requires X, r2 prohibits after X",
        )
        assert c.rule_a_id == "r1"
        assert c.conflict_type == "circular_dependency"
