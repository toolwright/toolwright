"""Tests for the rules CLI commands.

Tests the `toolwright rules` command group: add, list, remove, show,
export, import.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from toolwright.cli.main import cli

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rules_file(tmp_path: Path) -> Path:
    """Return path to a rules file in tmp_path."""
    return tmp_path / "rules.json"


def _invoke(runner: CliRunner, args: list[str], tmp_path: Path) -> object:
    """Invoke CLI with --rules-path pointing to tmp_path."""
    return runner.invoke(cli, ["rules", "--rules-path", str(_rules_file(tmp_path))] + args)


# ---------------------------------------------------------------------------
# Tests: rules group registration
# ---------------------------------------------------------------------------


class TestRulesGroupRegistered:
    """Test that the rules command group is registered."""

    def test_rules_group_in_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["rules", "--help"])
        assert result.exit_code == 0
        assert "rules" in result.output.lower()

    def test_rules_has_subcommands(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["rules", "--help"])
        assert "add" in result.output
        assert "list" in result.output
        assert "remove" in result.output
        assert "show" in result.output


# ---------------------------------------------------------------------------
# Tests: rules add
# ---------------------------------------------------------------------------


class TestRulesAdd:
    """Test the `rules add` command."""

    def test_add_prerequisite_rule(self, tmp_path: Path):
        runner = CliRunner()
        result = _invoke(runner, [
            "add",
            "--kind", "prerequisite",
            "--target", "update_user",
            "--description", "Must call get_user before update_user",
            "--requires", "get_user",
        ], tmp_path)
        assert result.exit_code == 0
        assert "added" in result.output.lower() or "created" in result.output.lower()

        # Verify rule was persisted
        rules = json.loads(_rules_file(tmp_path).read_text())
        assert len(rules) == 1
        assert rules[0]["kind"] == "prerequisite"

    def test_add_prohibition_rule(self, tmp_path: Path):
        runner = CliRunner()
        result = _invoke(runner, [
            "add",
            "--kind", "prohibition",
            "--target", "delete_user",
            "--description", "Never delete users",
        ], tmp_path)
        assert result.exit_code == 0

        rules = json.loads(_rules_file(tmp_path).read_text())
        assert len(rules) == 1
        assert rules[0]["kind"] == "prohibition"
        assert rules[0]["config"]["always"] is True

    def test_add_rate_rule(self, tmp_path: Path):
        runner = CliRunner()
        result = _invoke(runner, [
            "add",
            "--kind", "rate",
            "--target", "search",
            "--description", "Max 10 calls per session",
            "--max-calls", "10",
        ], tmp_path)
        assert result.exit_code == 0

        rules = json.loads(_rules_file(tmp_path).read_text())
        assert len(rules) == 1
        assert rules[0]["config"]["max_calls"] == 10

    def test_add_parameter_rule(self, tmp_path: Path):
        runner = CliRunner()
        result = _invoke(runner, [
            "add",
            "--kind", "parameter",
            "--target", "update_user",
            "--description", "Role must be user or moderator",
            "--param-name", "role",
            "--allowed-values", "user,moderator",
        ], tmp_path)
        assert result.exit_code == 0

        rules = json.loads(_rules_file(tmp_path).read_text())
        assert rules[0]["config"]["param_name"] == "role"
        assert rules[0]["config"]["allowed_values"] == ["user", "moderator"]

    def test_add_parameter_rule_with_pattern(self, tmp_path: Path):
        """Test that --pattern option is supported for parameter rules."""
        runner = CliRunner()
        result = _invoke(runner, [
            "add",
            "--kind", "parameter",
            "--target", "post_repo_label",
            "--description", "Label color must be valid hex",
            "--param-name", "color",
            "--pattern", "^[0-9a-fA-F]{6}$",
        ], tmp_path)
        assert result.exit_code == 0, f"Exit code was {result.exit_code}: {result.output}"

        rules = json.loads(_rules_file(tmp_path).read_text())
        assert rules[0]["config"]["param_name"] == "color"
        assert rules[0]["config"]["pattern"] == "^[0-9a-fA-F]{6}$"

    def test_add_duplicate_rule_is_skipped(self, tmp_path: Path):
        """Adding the same rule twice (same kind + targets + description) should skip."""
        runner = CliRunner()
        add_args = [
            "add",
            "--kind", "prohibition",
            "--target", "delete_user",
            "--description", "Never delete users",
        ]
        r1 = _invoke(runner, add_args, tmp_path)
        assert r1.exit_code == 0
        assert "added" in r1.output.lower()

        r2 = _invoke(runner, add_args, tmp_path)
        assert r2.exit_code == 0
        assert "already exists" in r2.output.lower()

        rules = json.loads(_rules_file(tmp_path).read_text())
        assert len(rules) == 1

    def test_add_duplicate_rule_id_gives_clean_error(self, tmp_path: Path):
        """H7: Duplicate custom --rule-id should show clean error, not traceback."""
        runner = CliRunner()
        _invoke(runner, [
            "add", "--kind", "prohibition", "--target", "delete_user",
            "--description", "First rule", "--rule-id", "my-custom-id",
        ], tmp_path)

        result = _invoke(runner, [
            "add", "--kind", "prohibition", "--target", "other_tool",
            "--description", "Second rule", "--rule-id", "my-custom-id",
        ], tmp_path)
        assert result.exit_code == 1
        assert "already exists" in result.output.lower()
        # Ensure no traceback leaked
        assert "Traceback" not in result.output

    def test_add_different_rules_both_kept(self, tmp_path: Path):
        """Adding rules with different descriptions should keep both."""
        runner = CliRunner()
        _invoke(runner, [
            "add", "--kind", "prohibition",
            "--target", "delete_user",
            "--description", "Never delete users",
        ], tmp_path)
        _invoke(runner, [
            "add", "--kind", "prohibition",
            "--target", "delete_user",
            "--description", "A different reason to block deletes",
        ], tmp_path)

        rules = json.loads(_rules_file(tmp_path).read_text())
        assert len(rules) == 2


# ---------------------------------------------------------------------------
# Tests: rules list
# ---------------------------------------------------------------------------


class TestRulesList:
    """Test the `rules list` command."""

    def test_list_empty(self, tmp_path: Path):
        runner = CliRunner()
        result = _invoke(runner, ["list"], tmp_path)
        assert result.exit_code == 0
        assert "no rules" in result.output.lower() or "0" in result.output

    def test_list_shows_rules(self, tmp_path: Path):
        runner = CliRunner()
        # Add two rules first
        _invoke(runner, [
            "add", "--kind", "prohibition", "--target", "delete_user",
            "--description", "No deletes",
        ], tmp_path)
        _invoke(runner, [
            "add", "--kind", "prerequisite", "--target", "update_user",
            "--description", "Prereq", "--requires", "get_user",
        ], tmp_path)

        result = _invoke(runner, ["list"], tmp_path)
        assert result.exit_code == 0
        assert "prohibition" in result.output.lower()
        assert "prerequisite" in result.output.lower()

    def test_list_filter_by_kind(self, tmp_path: Path):
        runner = CliRunner()
        _invoke(runner, [
            "add", "--kind", "prohibition", "--target", "delete_user",
            "--description", "No deletes",
        ], tmp_path)
        _invoke(runner, [
            "add", "--kind", "prerequisite", "--target", "update_user",
            "--description", "Prereq", "--requires", "get_user",
        ], tmp_path)

        result = _invoke(runner, ["list", "--kind", "prohibition"], tmp_path)
        assert result.exit_code == 0
        assert "prohibition" in result.output.lower()


# ---------------------------------------------------------------------------
# Tests: rules show
# ---------------------------------------------------------------------------


class TestRulesShow:
    """Test the `rules show` command."""

    def test_show_existing_rule(self, tmp_path: Path):
        runner = CliRunner()
        _invoke(runner, [
            "add", "--kind", "prohibition", "--target", "delete_user",
            "--description", "No deletes",
        ], tmp_path)

        # Get the rule_id from the rules file
        rules = json.loads(_rules_file(tmp_path).read_text())
        rule_id = rules[0]["rule_id"]

        result = _invoke(runner, ["show", rule_id], tmp_path)
        assert result.exit_code == 0
        assert rule_id in result.output

    def test_show_missing_rule(self, tmp_path: Path):
        runner = CliRunner()
        result = _invoke(runner, ["show", "nonexistent"], tmp_path)
        assert result.exit_code != 0 or "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# Tests: rules remove
# ---------------------------------------------------------------------------


class TestRulesRemove:
    """Test the `rules remove` command."""

    def test_remove_existing_rule(self, tmp_path: Path):
        runner = CliRunner()
        _invoke(runner, [
            "add", "--kind", "prohibition", "--target", "delete_user",
            "--description", "No deletes",
        ], tmp_path)

        rules = json.loads(_rules_file(tmp_path).read_text())
        rule_id = rules[0]["rule_id"]

        result = _invoke(runner, ["remove", rule_id, "--yes"], tmp_path)
        assert result.exit_code == 0
        assert "removed" in result.output.lower()

        # Verify rule was removed from file
        rules_after = json.loads(_rules_file(tmp_path).read_text())
        assert len(rules_after) == 0

    def test_remove_missing_rule(self, tmp_path: Path):
        runner = CliRunner()
        result = _invoke(runner, ["remove", "nonexistent"], tmp_path)
        assert result.exit_code != 0 or "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# Tests: rules export/import
# ---------------------------------------------------------------------------


class TestRulesExportImport:
    """Test export and import of rules."""

    def test_export_creates_file(self, tmp_path: Path):
        runner = CliRunner()
        _invoke(runner, [
            "add", "--kind", "prohibition", "--target", "delete_user",
            "--description", "No deletes",
        ], tmp_path)

        export_path = tmp_path / "exported_rules.json"
        result = _invoke(runner, ["export", "--output", str(export_path)], tmp_path)
        assert result.exit_code == 0
        assert export_path.exists()

        exported = json.loads(export_path.read_text())
        assert len(exported) == 1

    def test_import_loads_rules(self, tmp_path: Path):
        runner = CliRunner()

        # Create a rules file to import
        import_data = [
            {
                "rule_id": "imported_1",
                "kind": "prohibition",
                "description": "Imported rule",
                "target_tool_ids": ["some_tool"],
                "config": {"always": True},
            }
        ]
        import_path = tmp_path / "import_rules.json"
        import_path.write_text(json.dumps(import_data, default=str))

        result = _invoke(runner, ["import", "--input", str(import_path)], tmp_path)
        assert result.exit_code == 0

        # Verify rule was imported
        rules = json.loads(_rules_file(tmp_path).read_text())
        assert any(r["rule_id"] == "imported_1" for r in rules)
