"""Tests for RepairApplier — patch dispatch, auto-heal policy, result counting."""

from __future__ import annotations

from pathlib import Path

from toolwright.core.repair.applier import RepairApplier
from toolwright.models.reconcile import AutoHealPolicy
from toolwright.models.repair import (
    PatchAction,
    PatchItem,
    PatchKind,
    RepairPatchPlan,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch(
    id: str,
    kind: PatchKind,
    action: PatchAction,
) -> PatchItem:
    """Build a minimal PatchItem for testing."""
    return PatchItem(
        id=id,
        diagnosis_id=f"diag_{id}",
        kind=kind,
        action=action,
        title=f"Patch {id}",
        description=f"Description for {id}",
        cli_command=f"toolwright {action.value}",
        reason=f"Reason for {id}",
    )


def _plan(*patches: PatchItem) -> RepairPatchPlan:
    """Build a RepairPatchPlan from a list of PatchItems."""
    safe = sum(1 for p in patches if p.kind == PatchKind.SAFE)
    approval = sum(1 for p in patches if p.kind == PatchKind.APPROVAL_REQUIRED)
    manual = sum(1 for p in patches if p.kind == PatchKind.MANUAL)
    return RepairPatchPlan(
        total_patches=len(patches),
        safe_count=safe,
        approval_required_count=approval,
        manual_count=manual,
        patches=list(patches),
    )


# ===========================================================================
# 1. Empty plan
# ===========================================================================


class TestEmptyPlan:
    """An empty plan should return an empty result regardless of policy."""

    def test_empty_plan_off(self, tmp_path: Path) -> None:
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.OFF)
        result = applier.apply_plan(_plan())
        assert result.total == 0
        assert result.applied_count == 0
        assert result.skipped_count == 0
        assert result.results == []

    def test_empty_plan_safe(self, tmp_path: Path) -> None:
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.SAFE)
        result = applier.apply_plan(_plan())
        assert result.total == 0
        assert result.applied_count == 0

    def test_empty_plan_all(self, tmp_path: Path) -> None:
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.ALL)
        result = applier.apply_plan(_plan())
        assert result.total == 0
        assert result.applied_count == 0


# ===========================================================================
# 2. OFF policy — nothing auto-applies
# ===========================================================================


class TestOffPolicy:
    """When auto_heal=OFF, every patch is skipped."""

    def test_safe_patches_skipped(self, tmp_path: Path) -> None:
        plan = _plan(
            _patch("p1", PatchKind.SAFE, PatchAction.VERIFY_CONTRACTS),
        )
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.OFF)
        result = applier.apply_plan(plan)

        assert result.total == 1
        assert result.applied_count == 0
        assert result.skipped_count == 1
        assert result.results[0].applied is False

    def test_approval_patches_skipped(self, tmp_path: Path) -> None:
        plan = _plan(
            _patch("p1", PatchKind.APPROVAL_REQUIRED, PatchAction.GATE_ALLOW),
        )
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.OFF)
        result = applier.apply_plan(plan)

        assert result.applied_count == 0
        assert result.skipped_count == 1

    def test_manual_patches_skipped(self, tmp_path: Path) -> None:
        plan = _plan(
            _patch("p1", PatchKind.MANUAL, PatchAction.INVESTIGATE),
        )
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.OFF)
        result = applier.apply_plan(plan)

        assert result.applied_count == 0
        assert result.skipped_count == 1

    def test_mixed_plan_all_skipped(self, tmp_path: Path) -> None:
        plan = _plan(
            _patch("p1", PatchKind.SAFE, PatchAction.VERIFY_CONTRACTS),
            _patch("p2", PatchKind.APPROVAL_REQUIRED, PatchAction.GATE_ALLOW),
            _patch("p3", PatchKind.MANUAL, PatchAction.INVESTIGATE),
        )
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.OFF)
        result = applier.apply_plan(plan)

        assert result.total == 3
        assert result.applied_count == 0
        assert result.skipped_count == 3


# ===========================================================================
# 3. SAFE policy — only SAFE patches auto-apply
# ===========================================================================


class TestSafePolicy:
    """When auto_heal=SAFE, only PatchKind.SAFE patches auto-apply."""

    def test_safe_patch_applied(self, tmp_path: Path) -> None:
        plan = _plan(
            _patch("p1", PatchKind.SAFE, PatchAction.VERIFY_CONTRACTS),
        )
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.SAFE)
        result = applier.apply_plan(plan)

        assert result.applied_count == 1
        assert result.skipped_count == 0
        assert result.results[0].applied is True

    def test_approval_patch_skipped(self, tmp_path: Path) -> None:
        plan = _plan(
            _patch("p1", PatchKind.APPROVAL_REQUIRED, PatchAction.GATE_ALLOW),
        )
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.SAFE)
        result = applier.apply_plan(plan)

        assert result.applied_count == 0
        assert result.skipped_count == 1
        assert "human approval" in result.results[0].reason.lower()

    def test_manual_patch_skipped(self, tmp_path: Path) -> None:
        plan = _plan(
            _patch("p1", PatchKind.MANUAL, PatchAction.RE_MINT),
        )
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.SAFE)
        result = applier.apply_plan(plan)

        assert result.applied_count == 0
        assert result.skipped_count == 1
        assert "manual" in result.results[0].reason.lower()

    def test_mixed_plan_only_safe_applied(self, tmp_path: Path) -> None:
        plan = _plan(
            _patch("p1", PatchKind.SAFE, PatchAction.VERIFY_CONTRACTS),
            _patch("p2", PatchKind.SAFE, PatchAction.VERIFY_PROVENANCE),
            _patch("p3", PatchKind.APPROVAL_REQUIRED, PatchAction.GATE_ALLOW),
            _patch("p4", PatchKind.MANUAL, PatchAction.INVESTIGATE),
        )
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.SAFE)
        result = applier.apply_plan(plan)

        assert result.total == 4
        assert result.applied_count == 2
        assert result.skipped_count == 2


# ===========================================================================
# 4. ALL policy — SAFE + APPROVAL_REQUIRED auto-apply, MANUAL skipped
# ===========================================================================


class TestAllPolicy:
    """When auto_heal=ALL, SAFE and APPROVAL_REQUIRED auto-apply; MANUAL is skipped."""

    def test_safe_patch_applied(self, tmp_path: Path) -> None:
        plan = _plan(
            _patch("p1", PatchKind.SAFE, PatchAction.VERIFY_CONTRACTS),
        )
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.ALL)
        result = applier.apply_plan(plan)

        assert result.applied_count == 1
        assert result.results[0].applied is True

    def test_approval_patch_applied(self, tmp_path: Path) -> None:
        plan = _plan(
            _patch("p1", PatchKind.APPROVAL_REQUIRED, PatchAction.GATE_ALLOW),
        )
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.ALL)
        result = applier.apply_plan(plan)

        assert result.applied_count == 1
        assert result.results[0].applied is True

    def test_manual_patch_still_skipped(self, tmp_path: Path) -> None:
        plan = _plan(
            _patch("p1", PatchKind.MANUAL, PatchAction.INVESTIGATE),
        )
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.ALL)
        result = applier.apply_plan(plan)

        assert result.applied_count == 0
        assert result.skipped_count == 1
        assert "manual" in result.results[0].reason.lower()

    def test_mixed_plan_manual_only_skipped(self, tmp_path: Path) -> None:
        plan = _plan(
            _patch("p1", PatchKind.SAFE, PatchAction.VERIFY_CONTRACTS),
            _patch("p2", PatchKind.APPROVAL_REQUIRED, PatchAction.GATE_SYNC),
            _patch("p3", PatchKind.APPROVAL_REQUIRED, PatchAction.GATE_RESEAL),
            _patch("p4", PatchKind.MANUAL, PatchAction.RE_MINT),
            _patch("p5", PatchKind.MANUAL, PatchAction.ADD_HOST),
        )
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.ALL)
        result = applier.apply_plan(plan)

        assert result.total == 5
        assert result.applied_count == 3
        assert result.skipped_count == 2


# ===========================================================================
# 5. Per-action dispatch correctness
# ===========================================================================


class TestActionDispatch:
    """Each PatchAction dispatches to the correct handler and returns the right result."""

    def test_verify_contracts_returns_applied(self, tmp_path: Path) -> None:
        plan = _plan(_patch("p1", PatchKind.SAFE, PatchAction.VERIFY_CONTRACTS))
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.SAFE)
        result = applier.apply_plan(plan)
        assert result.results[0].applied is True

    def test_verify_provenance_returns_applied(self, tmp_path: Path) -> None:
        plan = _plan(_patch("p1", PatchKind.SAFE, PatchAction.VERIFY_PROVENANCE))
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.SAFE)
        result = applier.apply_plan(plan)
        assert result.results[0].applied is True

    def test_gate_allow_requires_human_approval(self, tmp_path: Path) -> None:
        plan = _plan(_patch("p1", PatchKind.APPROVAL_REQUIRED, PatchAction.GATE_ALLOW))
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.SAFE)
        result = applier.apply_plan(plan)
        assert result.results[0].applied is False
        assert "human approval" in result.results[0].reason.lower()

    def test_gate_sync_requires_human_approval(self, tmp_path: Path) -> None:
        plan = _plan(_patch("p1", PatchKind.APPROVAL_REQUIRED, PatchAction.GATE_SYNC))
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.SAFE)
        result = applier.apply_plan(plan)
        assert result.results[0].applied is False
        assert "human approval" in result.results[0].reason.lower()

    def test_gate_reseal_requires_human_approval(self, tmp_path: Path) -> None:
        plan = _plan(_patch("p1", PatchKind.APPROVAL_REQUIRED, PatchAction.GATE_RESEAL))
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.SAFE)
        result = applier.apply_plan(plan)
        assert result.results[0].applied is False
        assert "human approval" in result.results[0].reason.lower()

    def test_investigate_requires_manual_action(self, tmp_path: Path) -> None:
        plan = _plan(_patch("p1", PatchKind.MANUAL, PatchAction.INVESTIGATE))
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.SAFE)
        result = applier.apply_plan(plan)
        assert result.results[0].applied is False
        assert "manual" in result.results[0].reason.lower()

    def test_re_mint_requires_manual_action(self, tmp_path: Path) -> None:
        plan = _plan(_patch("p1", PatchKind.MANUAL, PatchAction.RE_MINT))
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.SAFE)
        result = applier.apply_plan(plan)
        assert result.results[0].applied is False
        assert "manual" in result.results[0].reason.lower()

    def test_review_policy_requires_manual_action(self, tmp_path: Path) -> None:
        plan = _plan(_patch("p1", PatchKind.MANUAL, PatchAction.REVIEW_POLICY))
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.SAFE)
        result = applier.apply_plan(plan)
        assert result.results[0].applied is False
        assert "manual" in result.results[0].reason.lower()

    def test_add_host_requires_manual_action(self, tmp_path: Path) -> None:
        plan = _plan(_patch("p1", PatchKind.MANUAL, PatchAction.ADD_HOST))
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.SAFE)
        result = applier.apply_plan(plan)
        assert result.results[0].applied is False
        assert "manual" in result.results[0].reason.lower()


# ===========================================================================
# 6. Result counts
# ===========================================================================


class TestResultCounts:
    """Verify total, applied_count, and skipped_count are consistent."""

    def test_counts_add_up(self, tmp_path: Path) -> None:
        plan = _plan(
            _patch("p1", PatchKind.SAFE, PatchAction.VERIFY_CONTRACTS),
            _patch("p2", PatchKind.SAFE, PatchAction.VERIFY_PROVENANCE),
            _patch("p3", PatchKind.APPROVAL_REQUIRED, PatchAction.GATE_ALLOW),
            _patch("p4", PatchKind.APPROVAL_REQUIRED, PatchAction.GATE_SYNC),
            _patch("p5", PatchKind.MANUAL, PatchAction.INVESTIGATE),
            _patch("p6", PatchKind.MANUAL, PatchAction.RE_MINT),
        )
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.ALL)
        result = applier.apply_plan(plan)

        assert result.total == 6
        assert result.applied_count + result.skipped_count == result.total
        assert result.applied_count == 4  # 2 safe + 2 approval
        assert result.skipped_count == 2  # 2 manual

    def test_result_ids_match_patches(self, tmp_path: Path) -> None:
        plan = _plan(
            _patch("alpha", PatchKind.SAFE, PatchAction.VERIFY_CONTRACTS),
            _patch("beta", PatchKind.MANUAL, PatchAction.INVESTIGATE),
        )
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.SAFE)
        result = applier.apply_plan(plan)

        result_ids = [r.patch_id for r in result.results]
        assert result_ids == ["alpha", "beta"]

    def test_len_results_equals_total(self, tmp_path: Path) -> None:
        plan = _plan(
            _patch("p1", PatchKind.SAFE, PatchAction.VERIFY_CONTRACTS),
            _patch("p2", PatchKind.APPROVAL_REQUIRED, PatchAction.GATE_ALLOW),
            _patch("p3", PatchKind.MANUAL, PatchAction.INVESTIGATE),
        )
        applier = RepairApplier(toolpack_dir=tmp_path, auto_heal=AutoHealPolicy.SAFE)
        result = applier.apply_plan(plan)

        assert len(result.results) == result.total
