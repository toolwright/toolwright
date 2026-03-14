"""Governance health score engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ScoreDimension:
    """A single dimension of the governance score."""

    name: str
    score: float  # 0.0 to 1.0
    weight: float
    details: str
    recommendations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GovernanceScore:
    """Aggregated governance health score."""

    total: int  # 0-100
    grade: str  # A, B, C, D, F
    dimensions: list[ScoreDimension]
    top_recommendations: list[str]
    toolpack_id: str

    @staticmethod
    def grade_from_score(score: int) -> str:
        if score >= 90:
            return "A"
        if score >= 80:
            return "B"
        if score >= 70:
            return "C"
        if score >= 60:
            return "D"
        return "F"


def compute_score(
    *,
    toolpack_path: str | Path,
) -> GovernanceScore:
    """Compute governance health score for a toolpack."""
    from toolwright.core.approval.lockfile import ApprovalStatus, LockfileManager
    from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths
    from toolwright.ui.ops import get_status, run_doctor_checks

    tp_path = Path(toolpack_path)
    toolpack = load_toolpack(tp_path)
    resolved = resolve_toolpack_paths(toolpack=toolpack, toolpack_path=tp_path)

    dimensions: list[ScoreDimension] = []
    all_recommendations: list[str] = []

    # --- 1. Approval Health (30%) ---
    approval_score = 0.0
    approval_details = "No lockfile found"
    approval_recs: list[str] = []

    lockfile_path = resolved.approved_lockfile_path or resolved.pending_lockfile_path
    if lockfile_path and lockfile_path.exists():
        try:
            manager = LockfileManager(lockfile_path)
            lf = manager.load()
            total = lf.total_tools
            if total > 0:
                approved_ratio = lf.approved_count / total
                pending_ratio = lf.pending_count / total
                rejected_ratio = lf.rejected_count / total

                approval_score = max(
                    0.0,
                    approved_ratio - (pending_ratio * 0.3) - (rejected_ratio * 0.5),
                )

                parts = [f"{lf.approved_count}/{total} approved"]
                if lf.pending_count:
                    parts.append(f"{lf.pending_count} pending")
                    approval_recs.append(
                        f"Run 'toolwright gate allow' to approve {lf.pending_count} pending tool(s)"
                    )
                if lf.rejected_count:
                    parts.append(f"{lf.rejected_count} rejected")
                approval_details = ", ".join(parts)
            else:
                approval_details = "No tools in lockfile"
                approval_recs.append("Run 'toolwright create <recipe>' to generate tools")
        except Exception:
            approval_details = "Lockfile could not be loaded"
            approval_recs.append("Run 'toolwright compile' to regenerate lockfile")
    else:
        approval_recs.append("Run 'toolwright gate allow' to create an approved lockfile")

    dimensions.append(
        ScoreDimension(
            name="Approval",
            score=approval_score,
            weight=0.30,
            details=approval_details,
            recommendations=approval_recs,
        )
    )
    all_recommendations.extend(approval_recs)

    # --- 2. Drift / API Stability (25%) ---
    drift_score = 0.5  # default: not checked
    drift_details = "Not checked"
    drift_recs: list[str] = []

    try:
        status = get_status(str(tp_path))
        drift_state = status.drift_state
        if drift_state == "clean":
            drift_score = 1.0
            drift_details = "No drift detected"
        elif drift_state == "warnings":
            drift_score = 0.6
            drift_details = "Drift warnings detected"
            drift_recs.append("Run 'toolwright drift' to review changes")
        elif drift_state == "breaking":
            drift_score = 0.1
            drift_details = "Breaking changes detected"
            drift_recs.append("Run 'toolwright drift' and 'toolwright repair diagnose' urgently")
        else:
            drift_details = "Drift not yet checked"
            drift_recs.append("Run 'toolwright drift' to check for API changes")
    except Exception:
        drift_recs.append("Run 'toolwright drift' to check for API changes")

    dimensions.append(
        ScoreDimension(
            name="Stability",
            score=drift_score,
            weight=0.25,
            details=drift_details,
            recommendations=drift_recs,
        )
    )
    all_recommendations.extend(drift_recs)

    # --- 3. Verification (25%) ---
    verify_score = 0.0
    verify_details = "Not verified"
    verify_recs: list[str] = []

    try:
        verify_state = status.verification_state
        if verify_state == "pass":
            verify_score = 1.0
            verify_details = "All checks passed"
        elif verify_state == "partial":
            verify_score = 0.6
            verify_details = "Partial verification"
            verify_recs.append("Run 'toolwright verify' with --mode all for full check")
        elif verify_state == "fail":
            verify_score = 0.2
            verify_details = "Verification failed"
            verify_recs.append("Run 'toolwright verify' and fix failing checks")
        else:
            verify_details = "Not yet verified"
            verify_recs.append("Run 'toolwright verify' to validate governance")
    except Exception:
        verify_recs.append("Run 'toolwright verify' to validate governance")

    dimensions.append(
        ScoreDimension(
            name="Verification",
            score=verify_score,
            weight=0.25,
            details=verify_details,
            recommendations=verify_recs,
        )
    )
    all_recommendations.extend(verify_recs)

    # --- 4. Readiness (20%) ---
    readiness_score = 0.0
    readiness_details = "Not checked"
    readiness_recs: list[str] = []

    try:
        doctor = run_doctor_checks(toolpack_path=str(tp_path))
        total_checks = len(doctor.checks)
        passed = sum(1 for c in doctor.checks if c.passed)
        if total_checks > 0:
            readiness_score = passed / total_checks
            readiness_details = f"{passed}/{total_checks} checks passed"
            failed_checks = [c for c in doctor.checks if not c.passed]
            for c in failed_checks[:3]:
                readiness_recs.append(f"Fix: {c.name} -- {c.detail}")
        else:
            readiness_details = "No checks available"
    except Exception:
        readiness_recs.append("Run 'toolwright doctor' to check readiness")

    dimensions.append(
        ScoreDimension(
            name="Readiness",
            score=readiness_score,
            weight=0.20,
            details=readiness_details,
            recommendations=readiness_recs,
        )
    )
    all_recommendations.extend(readiness_recs)

    # --- Aggregate ---
    weighted = sum(d.score * d.weight for d in dimensions)
    total = round(weighted * 100)
    total = max(0, min(100, total))
    grade = GovernanceScore.grade_from_score(total)

    # Top 3 recommendations (deduplicated)
    seen: set[str] = set()
    top_recs: list[str] = []
    for r in all_recommendations:
        if r not in seen:
            seen.add(r)
            top_recs.append(r)
            if len(top_recs) >= 3:
                break

    # Resolve display name
    from toolwright.ui.ops import resolve_display_name

    toolpack_id = resolve_display_name(toolpack)

    return GovernanceScore(
        total=total,
        grade=grade,
        dimensions=dimensions,
        top_recommendations=top_recs,
        toolpack_id=toolpack_id,
    )
