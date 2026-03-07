"""Smart gate defaults for risk-based auto-approval in the ship flow.

LOW and MEDIUM risk tools are auto-approved with risk_policy provenance.
HIGH risk tools prompt with default Yes. CRITICAL prompts with default No.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApprovalClassification:
    """Result of classifying a tool's risk tier for approval."""

    auto_approve: bool
    approved_by: str = ""
    default_yes: bool = True


def classify_approval(risk_tier: str) -> ApprovalClassification:
    """Classify how a tool should be approved based on its risk tier.

    Returns an ApprovalClassification indicating whether the tool should be
    auto-approved (with provenance) or prompted to the user.
    """
    tier = risk_tier.lower()

    if tier in ("low", "safe"):
        return ApprovalClassification(
            auto_approve=True,
            approved_by=f"risk_policy:{tier}",
        )
    if tier == "medium":
        return ApprovalClassification(
            auto_approve=True,
            approved_by="risk_policy:medium",
        )
    if tier == "critical":
        return ApprovalClassification(
            auto_approve=False,
            default_yes=False,
        )
    # high or unknown → prompt with default Yes
    return ApprovalClassification(
        auto_approve=False,
        default_yes=True,
    )
