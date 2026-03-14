"""Tests for the pure next-steps recommendation engine."""

from __future__ import annotations

from toolwright.ui.views.next_steps import (
    NextStepsInput,
    NextStepsOutput,
    compute_next_steps,
)


class TestComputeNextSteps:
    """Verify priority-ordered decision tree."""

    def test_missing_lockfile_is_highest_priority(self) -> None:
        result = compute_next_steps(NextStepsInput(
            command="status",
            lockfile_state="missing",
        ))
        assert "gate sync" in result.primary.command
        assert result.primary.label == "Sync lockfile"

    def test_pending_approvals_before_verification(self) -> None:
        result = compute_next_steps(NextStepsInput(
            command="status",
            lockfile_state="pending",
            pending_count=3,
            verification_state="not_run",
        ))
        assert "gate allow --all" in result.primary.command
        assert "3 tools" in result.primary.why

    def test_pending_approvals_includes_all_flag(self) -> None:
        """H5: gate allow suggestion must include --all so users don't get an error."""
        result = compute_next_steps(NextStepsInput(
            command="status",
            lockfile_state="pending",
            pending_count=1,
        ))
        assert "--all" in result.primary.command

    def test_single_pending_tool_uses_singular(self) -> None:
        result = compute_next_steps(NextStepsInput(
            command="status",
            lockfile_state="pending",
            pending_count=1,
        ))
        assert "1 tool awaiting" in result.primary.why

    def test_verification_failure_suggests_repair(self) -> None:
        result = compute_next_steps(NextStepsInput(
            command="status",
            lockfile_state="sealed",
            verification_state="fail",
            has_approved_lockfile=True,
        ))
        assert "repair" in result.primary.command

    def test_breaking_drift_suggests_investigation(self) -> None:
        result = compute_next_steps(NextStepsInput(
            command="status",
            lockfile_state="sealed",
            drift_state="breaking",
            has_approved_lockfile=True,
            has_baseline=True,
        ))
        assert "drift" in result.primary.command
        assert "breaking" in result.primary.label.lower()

    def test_stale_lockfile_suggests_resync(self) -> None:
        result = compute_next_steps(NextStepsInput(
            command="status",
            lockfile_state="stale",
            has_approved_lockfile=True,
        ))
        assert "gate sync" in result.primary.command
        assert "stale" in result.primary.why.lower()

    def test_no_baseline_suggests_snapshot(self) -> None:
        result = compute_next_steps(NextStepsInput(
            command="status",
            lockfile_state="sealed",
            has_approved_lockfile=True,
            has_baseline=False,
        ))
        assert "snapshot" in result.primary.command

    def test_no_mcp_config_suggests_config(self) -> None:
        result = compute_next_steps(NextStepsInput(
            command="status",
            lockfile_state="sealed",
            has_approved_lockfile=True,
            has_baseline=True,
            has_mcp_config=False,
            drift_state="clean",
        ))
        assert "config" in result.primary.command

    def test_drift_not_checked_suggests_drift(self) -> None:
        result = compute_next_steps(NextStepsInput(
            command="status",
            lockfile_state="sealed",
            has_approved_lockfile=True,
            has_baseline=True,
            has_mcp_config=True,
            drift_state="not_checked",
        ))
        assert "drift" in result.primary.command
        assert result.primary.label == "Check for drift"

    def test_verification_not_run_suggests_verify(self) -> None:
        result = compute_next_steps(NextStepsInput(
            command="status",
            lockfile_state="sealed",
            has_approved_lockfile=True,
            has_baseline=True,
            has_mcp_config=True,
            drift_state="clean",
            verification_state="not_run",
        ))
        assert "verify" in result.primary.command

    def test_all_green_suggests_serve(self) -> None:
        result = compute_next_steps(NextStepsInput(
            command="status",
            lockfile_state="sealed",
            has_approved_lockfile=True,
            has_baseline=True,
            has_mcp_config=True,
            drift_state="clean",
            verification_state="pass",
        ))
        assert "serve" in result.primary.command
        assert result.primary.label == "Ready to serve"

    def test_alternatives_capped_at_3(self) -> None:
        # Many issues: missing lockfile + pending + verification fail + stale
        result = compute_next_steps(NextStepsInput(
            command="status",
            lockfile_state="missing",
            pending_count=5,
            verification_state="fail",
            drift_state="breaking",
        ))
        assert len(result.alternatives) <= 3

    def test_toolpack_id_appended_to_commands(self) -> None:
        result = compute_next_steps(NextStepsInput(
            command="status",
            toolpack_id="stripe-api",
            lockfile_state="missing",
        ))
        assert "--toolpack stripe-api" in result.primary.command

    def test_no_toolpack_id_omits_flag(self) -> None:
        result = compute_next_steps(NextStepsInput(
            command="status",
            lockfile_state="missing",
        ))
        assert "--toolpack" not in result.primary.command

    def test_drift_warnings_appear_as_alternative(self) -> None:
        result = compute_next_steps(NextStepsInput(
            command="status",
            lockfile_state="sealed",
            has_approved_lockfile=True,
            has_baseline=True,
            has_mcp_config=True,
            drift_state="warnings",
            verification_state="pass",
        ))
        # Primary should be serve (all else green), drift warning in alternatives
        assert "serve" in result.primary.command
        drift_alts = [a for a in result.alternatives if "drift" in a.command]
        assert len(drift_alts) == 1
        assert "warning" in drift_alts[0].label.lower()

    def test_output_types(self) -> None:
        result = compute_next_steps(NextStepsInput(command="status"))
        assert isinstance(result, NextStepsOutput)
        assert isinstance(result.primary.command, str)
        assert isinstance(result.primary.label, str)
        assert isinstance(result.primary.why, str)
        assert isinstance(result.alternatives, list)
