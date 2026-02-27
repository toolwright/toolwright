"""Tests for the rule status lifecycle.

Task 9.23: Replace `enabled: bool` with `status: RuleStatus` on BehavioralRule.
Tests cover the RuleStatus enum, legacy migration from enabled→status,
engine filtering by status, and status lifecycle transitions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from toolwright.models.rule import (
    BehavioralRule,
    ProhibitionConfig,
    RuleKind,
    RuleStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rule(
    rule_id: str = "test_rule",
    status: RuleStatus = RuleStatus.ACTIVE,
) -> BehavioralRule:
    """Build a minimal BehavioralRule for testing."""
    return BehavioralRule(
        rule_id=rule_id,
        kind=RuleKind.PROHIBITION,
        description="Test rule",
        target_tool_ids=["some_tool"],
        target_methods=[],
        target_hosts=[],
        config=ProhibitionConfig(always=True),
        created_at=datetime.now(UTC),
        created_by="test",
        status=status,
    )


def _engine_with_rules(tmp_path: Path, rules: list[BehavioralRule]):
    """Create a RuleEngine with the given rules persisted to tmp_path."""
    import json

    from toolwright.core.correct.engine import RuleEngine

    rules_file = tmp_path / "rules.json"
    data = [r.model_dump(mode="json") for r in rules]
    rules_file.write_text(json.dumps(data, indent=2, default=str))
    return RuleEngine(rules_path=rules_file)


# ---------------------------------------------------------------------------
# Tests: RuleStatus enum
# ---------------------------------------------------------------------------


class TestRuleStatus:
    """Test that the RuleStatus enum exists and has the expected values."""

    def test_default_status_is_active(self) -> None:
        rule = BehavioralRule(
            rule_id="default_test",
            kind=RuleKind.PROHIBITION,
            description="Test default",
            target_tool_ids=["tool"],
            target_methods=[],
            target_hosts=[],
            config=ProhibitionConfig(always=True),
            created_at=datetime.now(UTC),
            created_by="test",
        )
        assert rule.status == RuleStatus.ACTIVE

    def test_draft_status(self) -> None:
        rule = _make_rule(status=RuleStatus.DRAFT)
        assert rule.status == RuleStatus.DRAFT

    def test_disabled_status(self) -> None:
        rule = _make_rule(status=RuleStatus.DISABLED)
        assert rule.status == RuleStatus.DISABLED

    def test_status_values(self) -> None:
        members = set(RuleStatus)
        assert members == {RuleStatus.DRAFT, RuleStatus.ACTIVE, RuleStatus.DISABLED}


# ---------------------------------------------------------------------------
# Tests: legacy migration (enabled → status)
# ---------------------------------------------------------------------------


class TestLegacyMigration:
    """Test that legacy 'enabled' field is converted to 'status'."""

    def test_enabled_true_becomes_active(self) -> None:
        rule = BehavioralRule.model_validate(
            {
                "rule_id": "legacy_true",
                "kind": "prohibition",
                "description": "Legacy enabled=True",
                "target_tool_ids": ["tool"],
                "target_methods": [],
                "target_hosts": [],
                "config": {"always": True},
                "created_at": datetime.now(UTC).isoformat(),
                "created_by": "test",
                "enabled": True,
            }
        )
        assert rule.status == RuleStatus.ACTIVE

    def test_enabled_false_becomes_disabled(self) -> None:
        rule = BehavioralRule.model_validate(
            {
                "rule_id": "legacy_false",
                "kind": "prohibition",
                "description": "Legacy enabled=False",
                "target_tool_ids": ["tool"],
                "target_methods": [],
                "target_hosts": [],
                "config": {"always": True},
                "created_at": datetime.now(UTC).isoformat(),
                "created_by": "test",
                "enabled": False,
            }
        )
        assert rule.status == RuleStatus.DISABLED


# ---------------------------------------------------------------------------
# Tests: RuleEngine status filtering
# ---------------------------------------------------------------------------


class TestRuleEngineStatusFiltering:
    """Test that the engine only evaluates ACTIVE rules."""

    def test_active_rules_evaluated(self, tmp_path: Path) -> None:
        from toolwright.core.correct.session import SessionHistory

        rule = _make_rule(rule_id="active_rule", status=RuleStatus.ACTIVE)
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()

        result = engine.evaluate("some_tool", "GET", "host", {}, session)
        # ACTIVE prohibition with always=True should block
        assert result.allowed is False
        assert len(result.violations) == 1

    def test_draft_rules_skipped(self, tmp_path: Path) -> None:
        from toolwright.core.correct.session import SessionHistory

        rule = _make_rule(rule_id="draft_rule", status=RuleStatus.DRAFT)
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()

        result = engine.evaluate("some_tool", "GET", "host", {}, session)
        # DRAFT rule should be skipped — no violations
        assert result.allowed is True
        assert len(result.violations) == 0

    def test_disabled_rules_skipped(self, tmp_path: Path) -> None:
        from toolwright.core.correct.session import SessionHistory

        rule = _make_rule(rule_id="disabled_rule", status=RuleStatus.DISABLED)
        engine = _engine_with_rules(tmp_path, [rule])
        session = SessionHistory()

        result = engine.evaluate("some_tool", "GET", "host", {}, session)
        # DISABLED rule should be skipped — no violations
        assert result.allowed is True
        assert len(result.violations) == 0


# ---------------------------------------------------------------------------
# Tests: RuleEngine status lifecycle transitions
# ---------------------------------------------------------------------------


class TestRuleEngineStatusLifecycle:
    """Test status transitions via engine CRUD."""

    def test_update_rule_status_draft_to_active(self, tmp_path: Path) -> None:
        rule = _make_rule(rule_id="lifecycle_rule", status=RuleStatus.DRAFT)
        engine = _engine_with_rules(tmp_path, [rule])

        engine.update_rule("lifecycle_rule", status=RuleStatus.ACTIVE)
        updated = engine.get_rule("lifecycle_rule")
        assert updated is not None
        assert updated.status == RuleStatus.ACTIVE

    def test_update_rule_status_active_to_disabled(self, tmp_path: Path) -> None:
        rule = _make_rule(rule_id="lifecycle_rule", status=RuleStatus.ACTIVE)
        engine = _engine_with_rules(tmp_path, [rule])

        engine.update_rule("lifecycle_rule", status=RuleStatus.DISABLED)
        updated = engine.get_rule("lifecycle_rule")
        assert updated is not None
        assert updated.status == RuleStatus.DISABLED

    def test_add_rule_with_draft_status(self, tmp_path: Path) -> None:
        from toolwright.core.correct.engine import RuleEngine

        rules_file = tmp_path / "rules.json"
        engine = RuleEngine(rules_path=rules_file)

        rule = _make_rule(rule_id="new_draft", status=RuleStatus.DRAFT)
        engine.add_rule(rule)

        all_rules = engine.list_rules()
        assert len(all_rules) == 1
        assert all_rules[0].rule_id == "new_draft"
        assert all_rules[0].status == RuleStatus.DRAFT
