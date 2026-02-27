"""RepairApplier — dispatch PatchActions according to AutoHealPolicy."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from toolwright.models.reconcile import AutoHealPolicy
from toolwright.models.repair import PatchAction, PatchItem, PatchKind, RepairPatchPlan

# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


class PatchResult(BaseModel):
    """Outcome of applying (or skipping) a single patch."""

    patch_id: str
    applied: bool
    reason: str = ""


class ApplyResult(BaseModel):
    """Aggregate outcome of applying a full repair plan."""

    total: int = 0
    applied_count: int = 0
    skipped_count: int = 0
    results: list[PatchResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Action dispatch table
# ---------------------------------------------------------------------------

# SAFE actions — stub implementations that return applied=True.
_SAFE_ACTIONS: frozenset[PatchAction] = frozenset(
    {
        PatchAction.VERIFY_CONTRACTS,
        PatchAction.VERIFY_PROVENANCE,
    }
)

# APPROVAL_REQUIRED actions — need human sign-off.
_APPROVAL_ACTIONS: frozenset[PatchAction] = frozenset(
    {
        PatchAction.GATE_ALLOW,
        PatchAction.GATE_SYNC,
        PatchAction.GATE_RESEAL,
    }
)

# MANUAL actions — require manual intervention.
_MANUAL_ACTIONS: frozenset[PatchAction] = frozenset(
    {
        PatchAction.INVESTIGATE,
        PatchAction.RE_MINT,
        PatchAction.REVIEW_POLICY,
        PatchAction.ADD_HOST,
    }
)


def _dispatch(action: PatchAction) -> PatchResult:
    """Execute the action handler and return a raw PatchResult.

    This is the *intrinsic* result of running the action, independent of
    the auto-heal policy.  The caller decides whether to honour or skip it.
    """
    if action in _SAFE_ACTIONS:
        return PatchResult(patch_id="", applied=True)
    if action in _APPROVAL_ACTIONS:
        return PatchResult(
            patch_id="", applied=False, reason="requires human approval"
        )
    # MANUAL (and any unknown future actions)
    return PatchResult(patch_id="", applied=False, reason="manual action required")


# ---------------------------------------------------------------------------
# Applier
# ---------------------------------------------------------------------------


class RepairApplier:
    """Apply patches from a RepairPatchPlan according to an AutoHealPolicy.

    Three-tier logic:
      OFF  — nothing auto-applies; all patches are skipped.
      SAFE — only PatchKind.SAFE patches auto-apply.
      ALL  — SAFE + APPROVAL_REQUIRED auto-apply; MANUAL is still skipped.
    """

    def __init__(
        self,
        toolpack_dir: Path,
        auto_heal: AutoHealPolicy = AutoHealPolicy.SAFE,
    ) -> None:
        self._toolpack_dir = toolpack_dir
        self._auto_heal = auto_heal

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_plan(self, plan: RepairPatchPlan) -> ApplyResult:
        """Apply patches from *plan* according to the auto_heal policy."""
        results: list[PatchResult] = []
        applied = 0
        skipped = 0

        for patch in plan.patches:
            pr = self._apply_one(patch)
            results.append(pr)
            if pr.applied:
                applied += 1
            else:
                skipped += 1

        return ApplyResult(
            total=len(plan.patches),
            applied_count=applied,
            skipped_count=skipped,
            results=results,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _should_auto_apply(self, patch: PatchItem) -> bool:
        """Decide whether this patch can be auto-applied under the current policy."""
        if self._auto_heal == AutoHealPolicy.OFF:
            return False
        if self._auto_heal == AutoHealPolicy.SAFE:
            return patch.kind == PatchKind.SAFE
        # ALL: safe + approval_required
        return patch.kind in (PatchKind.SAFE, PatchKind.APPROVAL_REQUIRED)

    def _apply_one(self, patch: PatchItem) -> PatchResult:
        """Process a single patch: dispatch if allowed, otherwise skip."""
        raw = _dispatch(patch.action)

        if not self._should_auto_apply(patch):
            # Policy says skip — preserve the intrinsic reason for context.
            reason = raw.reason or "auto-heal policy does not allow this patch"
            return PatchResult(patch_id=patch.id, applied=False, reason=reason)

        # Policy allows auto-apply — mark as applied (stub execution).
        return PatchResult(patch_id=patch.id, applied=True, reason=raw.reason)
