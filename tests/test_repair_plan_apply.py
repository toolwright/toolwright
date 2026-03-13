"""Tests for `toolwright repair plan` and `toolwright repair apply` CLI commands."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from click.testing import CliRunner

from toolwright.models.repair import (
    PatchAction,
    PatchItem,
    PatchKind,
    RepairPatchPlan,
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def repair_plan_file(tmp_path):
    """Create a repair plan file with mixed patch kinds."""
    plan = RepairPatchPlan(
        total_patches=3,
        safe_count=1,
        approval_required_count=1,
        manual_count=1,
        patches=[
            PatchItem(
                id="p_safe_1",
                diagnosis_id="d_1",
                kind=PatchKind.SAFE,
                action=PatchAction.VERIFY_CONTRACTS,
                title="Re-verify contracts",
                description="Re-run contract verification for get_users",
                cli_command="toolwright verify --mode contracts --tools tools.json",
                reason="Contract check stale after schema change",
            ),
            PatchItem(
                id="p_approval_1",
                diagnosis_id="d_2",
                kind=PatchKind.APPROVAL_REQUIRED,
                action=PatchAction.GATE_ALLOW,
                title="Approve new tool",
                description="New tool create_item needs approval",
                cli_command="toolwright gate allow create_item",
                reason="New tool discovered in API",
                risk_note="Expands tool capability",
            ),
            PatchItem(
                id="p_manual_1",
                diagnosis_id="d_3",
                kind=PatchKind.MANUAL,
                action=PatchAction.INVESTIGATE,
                title="Investigate auth failure",
                description="Auth mechanism changed, manual investigation required",
                cli_command="# Manual: investigate auth change for create_order",
                reason="Auth type changed from bearer to api_key",
            ),
        ],
        commands_sh=(
            "toolwright verify --mode contracts --tools tools.json\n"
            "toolwright gate allow create_item\n"
            "# Manual: investigate auth change for create_order"
        ),
    )

    plan_dir = tmp_path / ".toolwright" / "state"
    plan_dir.mkdir(parents=True)
    plan_path = plan_dir / "repair_plan.json"

    # Wrap in a plan envelope with generated_at timestamp
    plan_data = {
        "generated_at": datetime.now(UTC).isoformat(),
        "plan": plan.model_dump(),
    }
    plan_path.write_text(json.dumps(plan_data, indent=2))
    return tmp_path


# ---------------------------------------------------------------------------
# Tests: repair plan
# ---------------------------------------------------------------------------


class TestRepairPlanCommand:
    """Tests for `toolwright repair plan`."""

    def test_repair_plan_help(self, runner):
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["repair", "plan", "--help"])
        assert result.exit_code == 0
        assert "plan" in result.output.lower()

    def test_repair_plan_shows_patches(self, runner, repair_plan_file):
        from toolwright.cli.main import cli

        result = runner.invoke(
            cli, ["repair", "plan", "--root", str(repair_plan_file)]
        )
        assert result.exit_code == 0
        assert "safe" in result.output.lower()
        assert "approval" in result.output.lower()
        assert "manual" in result.output.lower()

    def test_repair_plan_shows_patch_counts(self, runner, repair_plan_file):
        from toolwright.cli.main import cli

        result = runner.invoke(
            cli, ["repair", "plan", "--root", str(repair_plan_file)]
        )
        assert result.exit_code == 0
        assert "3" in result.output  # total patches

    def test_repair_plan_handles_no_plan_file(self, runner, tmp_path):
        from toolwright.cli.main import cli

        result = runner.invoke(
            cli, ["repair", "plan", "--root", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "no repair plan" in result.output.lower() or "not found" in result.output.lower()

    def test_repair_plan_shows_cli_commands(self, runner, repair_plan_file):
        from toolwright.cli.main import cli

        result = runner.invoke(
            cli, ["repair", "plan", "--root", str(repair_plan_file)]
        )
        assert result.exit_code == 0
        assert "verify" in result.output.lower()


# ---------------------------------------------------------------------------
# Tests: repair apply
# ---------------------------------------------------------------------------


class TestRepairApplyCommand:
    """Tests for `toolwright repair apply`."""

    def test_repair_apply_help(self, runner):
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["repair", "apply", "--help"])
        assert result.exit_code == 0
        assert "apply" in result.output.lower()

    def test_repair_apply_handles_no_plan_file(self, runner, tmp_path):
        from toolwright.cli.main import cli

        result = runner.invoke(
            cli, ["repair", "apply", "--root", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "no repair plan" in result.output.lower() or "not found" in result.output.lower()

    def test_repair_apply_warns_stale_plan(self, runner, tmp_path):
        """Plans older than threshold should produce a staleness warning."""
        from toolwright.cli.main import cli

        plan = RepairPatchPlan(
            total_patches=1,
            safe_count=1,
            patches=[
                PatchItem(
                    id="p_safe_1",
                    diagnosis_id="d_1",
                    kind=PatchKind.SAFE,
                    action=PatchAction.VERIFY_CONTRACTS,
                    title="Re-verify contracts",
                    description="Test",
                    cli_command="toolwright verify --mode contracts",
                    reason="Test",
                ),
            ],
        )

        plan_dir = tmp_path / ".toolwright" / "state"
        plan_dir.mkdir(parents=True)
        plan_path = plan_dir / "repair_plan.json"

        # Set generated_at to 2 hours ago (past the default 1-hour threshold)
        old_time = "2020-01-01T00:00:00+00:00"
        plan_data = {
            "generated_at": old_time,
            "plan": plan.model_dump(),
        }
        plan_path.write_text(json.dumps(plan_data, indent=2))

        result = runner.invoke(
            cli, ["repair", "apply", "--root", str(tmp_path)]
        )
        assert "stale" in result.output.lower() or "old" in result.output.lower()

    def test_repair_apply_shows_summary(self, runner, repair_plan_file):
        from toolwright.cli.main import cli

        result = runner.invoke(
            cli, ["repair", "apply", "--root", str(repair_plan_file)]
        )
        assert result.exit_code == 0
        # Should show some output about the plan
        assert "safe" in result.output.lower() or "patch" in result.output.lower()


# ---------------------------------------------------------------------------
# Tests: repair command group
# ---------------------------------------------------------------------------


class TestRepairCommandGroup:
    """Tests for `toolwright repair` command group."""

    def test_repair_help(self, runner):
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["repair", "--help"])
        assert result.exit_code == 0
        assert "plan" in result.output
        assert "apply" in result.output

    def test_repair_is_registered(self, runner):
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["--help"])
        assert "repair" in result.output
