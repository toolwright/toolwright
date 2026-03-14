"""Tests for rule template loading and application."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from toolwright.cli.main import cli
from toolwright.rules.loader import apply_template, list_templates, load_template


def test_list_templates_returns_bundled():
    """list_templates should return the 3 bundled templates."""
    templates = list_templates()
    names = {t["name"] for t in templates}
    assert "crud-safety" in names
    assert "rate-control" in names
    assert "retry-safety" in names


def test_list_templates_includes_metadata():
    """Each template entry should include name, description, rule_count."""
    templates = list_templates()
    for t in templates:
        assert "name" in t
        assert "description" in t
        assert "rule_count" in t
        assert isinstance(t["rule_count"], int)
        assert t["rule_count"] > 0


def test_load_template_returns_parsed_yaml():
    """load_template should return the full template dict."""
    template = load_template("crud-safety")
    assert template["name"] == "crud-safety"
    assert len(template["rules"]) == 3
    assert template["rules"][0]["kind"] == "prerequisite"


def test_load_template_rate_control():
    """load_template should parse rate-control correctly."""
    template = load_template("rate-control")
    assert template["name"] == "rate-control"
    assert len(template["rules"]) == 2
    assert template["rules"][0]["kind"] == "rate"


def test_load_template_retry_safety():
    """load_template should parse retry-safety correctly."""
    template = load_template("retry-safety")
    assert template["name"] == "retry-safety"
    assert len(template["rules"]) == 1
    assert template["rules"][0]["kind"] == "rate"
    assert template["rules"][0]["config"]["per_tool"] is True


def test_load_template_unknown_raises():
    """load_template should raise ValueError for unknown template."""
    with pytest.raises(ValueError, match="Unknown rule template"):
        load_template("nonexistent")


def test_load_template_unknown_lists_available():
    """The error for unknown template should list available templates."""
    with pytest.raises(ValueError, match="crud-safety"):
        load_template("nonexistent")


def test_apply_template_creates_draft_rules(tmp_path):
    """apply_template should create DRAFT rules in the rules JSON file."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")

    created = apply_template("retry-safety", rules_path=rules_path)
    assert len(created) == 1
    assert created[0].status.value == "draft"
    assert created[0].kind.value == "rate"

    # Verify persisted
    data = json.loads(rules_path.read_text())
    assert len(data) == 1
    assert data[0]["status"] == "draft"


def test_apply_template_with_activate(tmp_path):
    """apply_template with activate=True should create ACTIVE rules."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")

    created = apply_template("retry-safety", rules_path=rules_path, activate=True)
    assert created[0].status.value == "active"


def test_apply_template_appends_to_existing(tmp_path):
    """apply_template should append to existing rules, not overwrite."""
    rules_path = tmp_path / "rules.json"
    existing_rule = {
        "rule_id": "existing-1",
        "kind": "rate",
        "description": "existing rule",
        "config": {"max_calls": 5},
    }
    rules_path.write_text(json.dumps([existing_rule]))

    apply_template("retry-safety", rules_path=rules_path)
    data = json.loads(rules_path.read_text())
    assert len(data) == 2
    assert data[0]["rule_id"] == "existing-1"


def test_apply_template_creates_parent_dirs(tmp_path):
    """apply_template should create parent directories if missing."""
    rules_path = tmp_path / "nested" / "dir" / "rules.json"

    created = apply_template("retry-safety", rules_path=rules_path)
    assert len(created) == 1
    assert rules_path.exists()
    data = json.loads(rules_path.read_text())
    assert len(data) == 1


def test_apply_template_rule_ids_contain_template_name(tmp_path):
    """Generated rule IDs should reference the template name."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")

    created = apply_template("crud-safety", rules_path=rules_path)
    for rule in created:
        assert "crud-safety" in rule.rule_id


def test_apply_template_created_by_field(tmp_path):
    """created_by should indicate the template source."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")

    created = apply_template("retry-safety", rules_path=rules_path)
    assert created[0].created_by == "template:retry-safety"


def test_apply_crud_safety_template(tmp_path):
    """apply_template for crud-safety should create 3 rules with correct kinds."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")

    created = apply_template("crud-safety", rules_path=rules_path)
    assert len(created) == 3
    kinds = [r.kind.value for r in created]
    assert kinds.count("prerequisite") == 2
    assert kinds.count("approval") == 1


# ---------------------------------------------------------------------------
# CLI tests for `rules template` subgroup
# ---------------------------------------------------------------------------


def _rules_path(tmp_path: Path) -> Path:
    return tmp_path / "rules.json"


def _invoke_template(runner: CliRunner, args: list[str], tmp_path: Path):
    return runner.invoke(
        cli,
        ["rules", "--rules-path", str(_rules_path(tmp_path)), "template"] + args,
    )


class TestTemplateListCLI:
    def test_lists_all_templates(self, tmp_path):
        runner = CliRunner()
        result = _invoke_template(runner, ["list"], tmp_path)
        assert result.exit_code == 0
        assert "crud-safety" in result.output
        assert "rate-control" in result.output
        assert "retry-safety" in result.output

    def test_shows_rule_counts(self, tmp_path):
        runner = CliRunner()
        result = _invoke_template(runner, ["list"], tmp_path)
        assert "3 rules" in result.output  # crud-safety
        assert "2 rules" in result.output  # rate-control
        assert "1 rule)" in result.output  # retry-safety


class TestTemplateShowCLI:
    def test_shows_template_details(self, tmp_path):
        runner = CliRunner()
        result = _invoke_template(runner, ["show", "crud-safety"], tmp_path)
        assert result.exit_code == 0
        assert "crud-safety" in result.output
        assert "read-before-delete" in result.output
        assert "prerequisite" in result.output

    def test_shows_all_rules(self, tmp_path):
        runner = CliRunner()
        result = _invoke_template(runner, ["show", "crud-safety"], tmp_path)
        assert "read-before-delete" in result.output
        assert "read-before-update" in result.output
        assert "confirm-destructive" in result.output

    def test_unknown_template_errors(self, tmp_path):
        runner = CliRunner()
        result = _invoke_template(runner, ["show", "nonexistent"], tmp_path)
        assert result.exit_code != 0
        assert "Unknown rule template" in result.output


class TestTemplateApplyCLI:
    def test_apply_creates_draft_rules(self, tmp_path):
        runner = CliRunner()
        result = _invoke_template(runner, ["apply", "retry-safety"], tmp_path)
        assert result.exit_code == 0
        assert "1 rule created as DRAFT" in result.output

    def test_apply_with_activate(self, tmp_path):
        runner = CliRunner()
        result = _invoke_template(
            runner, ["apply", "retry-safety", "--activate"], tmp_path
        )
        assert result.exit_code == 0
        assert "ACTIVE" in result.output

    def test_apply_persists_to_file(self, tmp_path):
        runner = CliRunner()
        _invoke_template(runner, ["apply", "crud-safety"], tmp_path)
        data = json.loads(_rules_path(tmp_path).read_text())
        assert len(data) == 3

    def test_apply_unknown_template_errors(self, tmp_path):
        runner = CliRunner()
        result = _invoke_template(runner, ["apply", "nonexistent"], tmp_path)
        assert result.exit_code != 0
        assert "Unknown rule template" in result.output

    def test_apply_shows_hint_for_activate(self, tmp_path):
        runner = CliRunner()
        result = _invoke_template(runner, ["apply", "retry-safety"], tmp_path)
        assert "toolwright rules activate" in result.output

    def test_apply_twice_is_idempotent(self, tmp_path):
        """Applying the same template twice must not create duplicate rules."""
        runner = CliRunner()
        _invoke_template(runner, ["apply", "crud-safety"], tmp_path)
        result = _invoke_template(runner, ["apply", "crud-safety"], tmp_path)
        assert result.exit_code == 0
        data = json.loads(_rules_path(tmp_path).read_text())
        assert len(data) == 3  # not 6
        assert "already exists" in result.output.lower() or "skipping" in result.output.lower()

    def test_apply_twice_logs_skip_message(self, tmp_path):
        """Second apply should log that rules were skipped."""
        runner = CliRunner()
        _invoke_template(runner, ["apply", "crud-safety"], tmp_path)
        result = _invoke_template(runner, ["apply", "crud-safety"], tmp_path)
        assert "already exist" in result.output.lower()


class TestApplyTemplateIdempotent:
    """Idempotency tests at the loader level."""

    def test_apply_template_twice_no_duplicates(self, tmp_path):
        """apply_template called twice produces no duplicates."""
        rules_path = tmp_path / "rules.json"
        rules_path.write_text("[]")

        apply_template("crud-safety", rules_path=rules_path)
        created2 = apply_template("crud-safety", rules_path=rules_path)
        assert len(created2) == 0

        data = json.loads(rules_path.read_text())
        assert len(data) == 3

    def test_apply_template_twice_different_templates_ok(self, tmp_path):
        """Applying two different templates should create all rules."""
        rules_path = tmp_path / "rules.json"
        rules_path.write_text("[]")

        c1 = apply_template("crud-safety", rules_path=rules_path)
        c2 = apply_template("retry-safety", rules_path=rules_path)
        assert len(c1) == 3
        assert len(c2) == 1

        data = json.loads(rules_path.read_text())
        assert len(data) == 4
