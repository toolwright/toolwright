"""Tests for rules lifecycle CLI commands: drafts, activate, disable.

Tests the `toolwright rules drafts`, `toolwright rules activate`,
and `toolwright rules disable` subcommands.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner

from toolwright.cli.main import cli
from toolwright.models.rule import (
    BehavioralRule,
    ProhibitionConfig,
    RuleKind,
    RuleStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rules_file(tmp_path: Path) -> Path:
    """Return path to a rules file in tmp_path."""
    return tmp_path / "rules.json"


def _invoke(runner: CliRunner, args: list[str], tmp_path: Path) -> object:
    """Invoke CLI with --rules-path pointing to tmp_path."""
    return runner.invoke(cli, ["rules", "--rules-path", str(_rules_file(tmp_path))] + args)


def _make_rule(
    rule_id: str,
    status: RuleStatus = RuleStatus.ACTIVE,
    description: str = "Test rule",
) -> BehavioralRule:
    """Create a BehavioralRule with sensible defaults."""
    return BehavioralRule(
        rule_id=rule_id,
        kind=RuleKind.PROHIBITION,
        description=description,
        status=status,
        target_tool_ids=["some_tool"],
        config=ProhibitionConfig(always=True),
        created_at=datetime.now(UTC),
        created_by="agent",
    )


def _write_rules(path: Path, rules: list[BehavioralRule]) -> None:
    """Write rules to a JSON file."""
    data = [r.model_dump(mode="json") for r in rules]
    path.write_text(json.dumps(data, default=str))


def _read_rules(path: Path) -> list[dict]:
    """Read rules back from a JSON file."""
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Tests: rules drafts
# ---------------------------------------------------------------------------


class TestRulesDrafts:
    """Test the `rules drafts` command."""

    def test_drafts_shows_draft_rules(self, tmp_path: Path):
        """DRAFT rules appear in the drafts output."""
        rules = [
            _make_rule("draft_1", RuleStatus.DRAFT, "First draft rule"),
            _make_rule("draft_2", RuleStatus.DRAFT, "Second draft rule"),
        ]
        _write_rules(_rules_file(tmp_path), rules)

        runner = CliRunner()
        result = _invoke(runner, ["drafts"], tmp_path)
        assert result.exit_code == 0
        assert "draft_1" in result.output
        assert "draft_2" in result.output
        assert "First draft rule" in result.output
        assert "Second draft rule" in result.output

    def test_drafts_empty_message(self, tmp_path: Path):
        """No DRAFT rules shows an empty message."""
        _write_rules(_rules_file(tmp_path), [])

        runner = CliRunner()
        result = _invoke(runner, ["drafts"], tmp_path)
        assert result.exit_code == 0
        assert "no draft rules" in result.output.lower()

    def test_drafts_hides_active_rules(self, tmp_path: Path):
        """ACTIVE rules do not appear in drafts output."""
        rules = [
            _make_rule("active_1", RuleStatus.ACTIVE, "Active rule"),
            _make_rule("draft_1", RuleStatus.DRAFT, "Draft rule"),
        ]
        _write_rules(_rules_file(tmp_path), rules)

        runner = CliRunner()
        result = _invoke(runner, ["drafts"], tmp_path)
        assert result.exit_code == 0
        assert "draft_1" in result.output
        assert "active_1" not in result.output


# ---------------------------------------------------------------------------
# Tests: rules activate
# ---------------------------------------------------------------------------


class TestRulesActivate:
    """Test the `rules activate` command."""

    def test_activate_draft_rule(self, tmp_path: Path):
        """DRAFT rule becomes ACTIVE after activation."""
        rules = [_make_rule("draft_rule", RuleStatus.DRAFT)]
        _write_rules(_rules_file(tmp_path), rules)

        runner = CliRunner()
        result = _invoke(runner, ["activate", "draft_rule"], tmp_path)
        assert result.exit_code == 0
        assert "activated" in result.output.lower()

        persisted = _read_rules(_rules_file(tmp_path))
        assert persisted[0]["status"] == "active"

    def test_activate_disabled_rule(self, tmp_path: Path):
        """DISABLED rule becomes ACTIVE after activation."""
        rules = [_make_rule("disabled_rule", RuleStatus.DISABLED)]
        _write_rules(_rules_file(tmp_path), rules)

        runner = CliRunner()
        result = _invoke(runner, ["activate", "disabled_rule"], tmp_path)
        assert result.exit_code == 0
        assert "activated" in result.output.lower()

        persisted = _read_rules(_rules_file(tmp_path))
        assert persisted[0]["status"] == "active"

    def test_activate_unknown_id(self, tmp_path: Path):
        """Unknown rule_id produces an error."""
        _write_rules(_rules_file(tmp_path), [])

        runner = CliRunner()
        result = _invoke(runner, ["activate", "no_such_rule"], tmp_path)
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# Tests: rules disable
# ---------------------------------------------------------------------------


class TestRulesDisable:
    """Test the `rules disable` command."""

    def test_disable_active_rule(self, tmp_path: Path):
        """ACTIVE rule becomes DISABLED after disabling."""
        rules = [_make_rule("active_rule", RuleStatus.ACTIVE)]
        _write_rules(_rules_file(tmp_path), rules)

        runner = CliRunner()
        result = _invoke(runner, ["disable", "active_rule"], tmp_path)
        assert result.exit_code == 0
        assert "disabled" in result.output.lower()

        persisted = _read_rules(_rules_file(tmp_path))
        assert persisted[0]["status"] == "disabled"

    def test_disable_unknown_id(self, tmp_path: Path):
        """Unknown rule_id produces an error."""
        _write_rules(_rules_file(tmp_path), [])

        runner = CliRunner()
        result = _invoke(runner, ["disable", "no_such_rule"], tmp_path)
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_disable_already_disabled(self, tmp_path: Path):
        """Already DISABLED rule produces an 'already disabled' message."""
        rules = [_make_rule("dis_rule", RuleStatus.DISABLED)]
        _write_rules(_rules_file(tmp_path), rules)

        runner = CliRunner()
        result = _invoke(runner, ["disable", "dis_rule"], tmp_path)
        assert result.exit_code == 0
        assert "already disabled" in result.output.lower()


# ---------------------------------------------------------------------------
# Tests: command help
# ---------------------------------------------------------------------------


class TestCommandHelp:
    """Test that --help works for the new subcommands."""

    def test_drafts_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["rules", "drafts", "--help"])
        assert result.exit_code == 0
        assert "draft" in result.output.lower()

    def test_activate_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["rules", "activate", "--help"])
        assert result.exit_code == 0
        assert "activate" in result.output.lower()
