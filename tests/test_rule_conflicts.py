"""Tests for behavioral rule conflict detection."""

from __future__ import annotations

from toolwright.core.correct.conflicts import detect_conflicts
from toolwright.models.rule import (
    BehavioralRule,
    ParameterConfig,
    PrerequisiteConfig,
    ProhibitionConfig,
    RuleKind,
    SequenceConfig,
)


class TestConflictDetection:
    def test_no_conflicts_for_unrelated_rules(self) -> None:
        rules = [
            BehavioralRule(
                rule_id="r1",
                kind=RuleKind.PREREQUISITE,
                description="A requires B",
                target_tool_ids=["a"],
                config=PrerequisiteConfig(required_tool_ids=["b"]),
            ),
            BehavioralRule(
                rule_id="r2",
                kind=RuleKind.PREREQUISITE,
                description="C requires D",
                target_tool_ids=["c"],
                config=PrerequisiteConfig(required_tool_ids=["d"]),
            ),
        ]
        new_rule = rules[0]
        conflicts = detect_conflicts(new_rule, rules[1:])
        assert conflicts == []

    def test_circular_prerequisite_prohibition(self) -> None:
        """A requires B + B prohibited after A = circular."""
        existing = [
            BehavioralRule(
                rule_id="r2",
                kind=RuleKind.PROHIBITION,
                description="B prohibited after A",
                target_tool_ids=["b"],
                config=ProhibitionConfig(after_tool_ids=["a"]),
            ),
        ]
        new_rule = BehavioralRule(
            rule_id="r1",
            kind=RuleKind.PREREQUISITE,
            description="A requires B",
            target_tool_ids=["a"],
            config=PrerequisiteConfig(required_tool_ids=["b"]),
        )
        conflicts = detect_conflicts(new_rule, existing)
        assert len(conflicts) >= 1
        assert conflicts[0].conflict_type == "circular_dependency"

    def test_parameter_whitelist_blacklist_overlap(self) -> None:
        """Same param with overlapping allowed and blocked values."""
        existing = [
            BehavioralRule(
                rule_id="r2",
                kind=RuleKind.PARAMETER,
                description="Block admin",
                target_tool_ids=["set_role"],
                config=ParameterConfig(param_name="role", blocked_values=["admin", "superadmin"]),
            ),
        ]
        new_rule = BehavioralRule(
            rule_id="r1",
            kind=RuleKind.PARAMETER,
            description="Allow admin",
            target_tool_ids=["set_role"],
            config=ParameterConfig(param_name="role", allowed_values=["admin", "user"]),
        )
        conflicts = detect_conflicts(new_rule, existing)
        assert len(conflicts) >= 1
        assert conflicts[0].conflict_type == "parameter_contradiction"

    def test_contradictory_sequences(self) -> None:
        """A,B,C vs C,B,A on same targets."""
        existing = [
            BehavioralRule(
                rule_id="r2",
                kind=RuleKind.SEQUENCE,
                description="Order C,B,A",
                target_tool_ids=["a", "b", "c"],
                config=SequenceConfig(required_order=["c", "b", "a"]),
            ),
        ]
        new_rule = BehavioralRule(
            rule_id="r1",
            kind=RuleKind.SEQUENCE,
            description="Order A,B,C",
            target_tool_ids=["a", "b", "c"],
            config=SequenceConfig(required_order=["a", "b", "c"]),
        )
        conflicts = detect_conflicts(new_rule, existing)
        assert len(conflicts) >= 1
        assert conflicts[0].conflict_type == "sequence_contradiction"

    def test_no_conflict_different_targets(self) -> None:
        """Same kind but different target tools = no conflict."""
        existing = [
            BehavioralRule(
                rule_id="r2",
                kind=RuleKind.PARAMETER,
                description="Block admin on tool_x",
                target_tool_ids=["tool_x"],
                config=ParameterConfig(param_name="role", blocked_values=["admin"]),
            ),
        ]
        new_rule = BehavioralRule(
            rule_id="r1",
            kind=RuleKind.PARAMETER,
            description="Allow admin on tool_y",
            target_tool_ids=["tool_y"],
            config=ParameterConfig(param_name="role", allowed_values=["admin"]),
        )
        conflicts = detect_conflicts(new_rule, existing)
        assert conflicts == []
