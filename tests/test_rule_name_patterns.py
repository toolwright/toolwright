"""Tests for glob-based tool name pattern matching in rule targeting."""

from __future__ import annotations

from toolwright.core.correct.engine import RuleEngine
from toolwright.core.correct.session import SessionHistory
from toolwright.models.rule import (
    BehavioralRule,
    ProhibitionConfig,
    RuleKind,
)


def test_target_name_patterns_matches_glob(tmp_path):
    """A rule with target_name_patterns should match tool names via glob."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")
    engine = RuleEngine(rules_path=rules_path)

    rule = BehavioralRule(
        rule_id="test-1",
        kind=RuleKind.PROHIBITION,
        description="Block all delete tools",
        target_name_patterns=["delete_*", "*_delete"],
        config=ProhibitionConfig(always=True),
    )
    engine.add_rule(rule)

    session = SessionHistory()

    # Should match delete_product
    result = engine.evaluate("delete_product", "DELETE", "api.example.com", {}, session)
    assert not result.allowed

    # Should match bulk_delete
    result = engine.evaluate("bulk_delete", "DELETE", "api.example.com", {}, session)
    assert not result.allowed

    # Should NOT match get_products
    result = engine.evaluate("get_products", "GET", "api.example.com", {}, session)
    assert result.allowed


def test_match_all_requires_both_fields(tmp_path):
    """match=all means tool must match ALL non-empty targeting fields."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")
    engine = RuleEngine(rules_path=rules_path)

    rule = BehavioralRule(
        rule_id="test-2",
        kind=RuleKind.PROHIBITION,
        description="Block delete_* AND DELETE method",
        target_name_patterns=["delete_*"],
        target_methods=["DELETE"],
        match="all",
        config=ProhibitionConfig(always=True),
    )
    engine.add_rule(rule)

    session = SessionHistory()

    # Matches both pattern AND method -> blocked
    result = engine.evaluate("delete_product", "DELETE", "api.example.com", {}, session)
    assert not result.allowed

    # Matches pattern but NOT method -> allowed (all = AND)
    result = engine.evaluate("delete_product", "GET", "api.example.com", {}, session)
    assert result.allowed

    # Matches method but NOT pattern -> allowed (all = AND)
    result = engine.evaluate("remove_product", "DELETE", "api.example.com", {}, session)
    assert result.allowed


def test_match_any_requires_either_field(tmp_path):
    """match=any means tool matches if ANY non-empty targeting field hits."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")
    engine = RuleEngine(rules_path=rules_path)

    rule = BehavioralRule(
        rule_id="test-3",
        kind=RuleKind.PROHIBITION,
        description="Block delete_* OR DELETE method",
        target_name_patterns=["delete_*"],
        target_methods=["DELETE"],
        match="any",
        config=ProhibitionConfig(always=True),
    )
    engine.add_rule(rule)

    session = SessionHistory()

    # Matches pattern (regardless of method) -> blocked
    result = engine.evaluate("delete_product", "GET", "api.example.com", {}, session)
    assert not result.allowed

    # Matches method (regardless of pattern) -> blocked
    result = engine.evaluate("remove_product", "DELETE", "api.example.com", {}, session)
    assert not result.allowed

    # Matches neither -> allowed
    result = engine.evaluate("get_products", "GET", "api.example.com", {}, session)
    assert result.allowed


def test_empty_patterns_match_all(tmp_path):
    """Empty target_name_patterns should not filter anything (backward compat)."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")
    engine = RuleEngine(rules_path=rules_path)

    rule = BehavioralRule(
        rule_id="test-4",
        kind=RuleKind.PROHIBITION,
        description="Block everything",
        config=ProhibitionConfig(always=True),
    )
    engine.add_rule(rule)

    session = SessionHistory()
    result = engine.evaluate("any_tool", "GET", "api.example.com", {}, session)
    assert not result.allowed
