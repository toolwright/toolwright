"""Tests for scope confidence scoring (ScopeDraft)."""

from __future__ import annotations

from toolwright.models.scope import RiskReason, ScopeDraft


def test_scope_draft_basic() -> None:
    draft = ScopeDraft(
        endpoint_id="ep_1",
        scope_name="agent_safe_readonly",
        confidence=0.9,
        risk_tier="low",
    )
    assert draft.confidence == 0.9
    assert draft.review_required is False


def test_scope_draft_high_risk_low_confidence_requires_review() -> None:
    draft = ScopeDraft(
        endpoint_id="ep_2",
        scope_name="state_changing",
        confidence=0.5,
        risk_tier="high",
    )
    assert draft.review_required is True


def test_scope_draft_high_risk_high_confidence_no_review() -> None:
    draft = ScopeDraft(
        endpoint_id="ep_3",
        scope_name="state_changing",
        confidence=0.8,
        risk_tier="high",
    )
    assert draft.review_required is False


def test_scope_draft_critical_risk_low_confidence() -> None:
    draft = ScopeDraft(
        endpoint_id="ep_4",
        scope_name="pii_surface",
        confidence=0.3,
        risk_tier="critical",
    )
    assert draft.review_required is True


def test_scope_draft_medium_risk_low_confidence_no_review() -> None:
    draft = ScopeDraft(
        endpoint_id="ep_5",
        scope_name="agent_safe_readonly",
        confidence=0.4,
        risk_tier="medium",
    )
    assert draft.review_required is False


def test_scope_draft_with_risk_reasons() -> None:
    draft = ScopeDraft(
        endpoint_id="ep_6",
        scope_name="pii_surface",
        confidence=0.6,
        risk_tier="high",
        risk_reasons=[RiskReason.HAS_PII, RiskReason.STATE_CHANGING],
        signals=["POST method detected", "PII fields in request body"],
    )
    assert RiskReason.HAS_PII in draft.risk_reasons
    assert len(draft.signals) == 2
    assert draft.review_required is True


def test_scope_draft_with_explanation() -> None:
    draft = ScopeDraft(
        endpoint_id="ep_7",
        scope_name="auth_surface",
        confidence=0.95,
        risk_tier="high",
        explanation="Bearer auth header present with high confidence",
    )
    assert "Bearer auth" in draft.explanation
    assert draft.review_required is False


def test_risk_reason_enum_values() -> None:
    assert RiskReason.STATE_CHANGING == "state_changing"
    assert RiskReason.HAS_PII == "has_pii"
    assert RiskReason.THIRD_PARTY == "third_party"
    assert RiskReason.SENSITIVE_PATH == "sensitive_path"
