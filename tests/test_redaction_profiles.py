"""Tests for redaction profiles."""

from __future__ import annotations

import pytest

from toolwright.core.capture.redaction_profiles import (
    DEFAULT_SAFE,
    HIGH_RISK_PII,
    get_profile,
    list_profiles,
)


def test_default_safe_profile() -> None:
    p = DEFAULT_SAFE
    assert p.id == "default_safe"
    assert "authorization" in p.redact_headers
    assert "cookie" in p.redact_headers
    assert "token" in p.redact_query_params
    assert p.truncate_bodies is True
    assert p.max_body_chars == 4096


def test_high_risk_pii_profile() -> None:
    p = HIGH_RISK_PII
    assert p.id == "high_risk_pii"
    assert "authorization" in p.redact_headers  # inherits from default
    assert "email" in p.redact_query_params
    assert "phone" in p.redact_query_params
    assert "ssn" in p.redact_query_params
    assert p.max_body_chars == 2048  # more aggressive


def test_get_profile_default() -> None:
    p = get_profile("default_safe")
    assert p.id == "default_safe"


def test_get_profile_pii() -> None:
    p = get_profile("high_risk_pii")
    assert p.id == "high_risk_pii"


def test_get_profile_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown redaction profile"):
        get_profile("nonexistent")


def test_list_profiles() -> None:
    profiles = list_profiles()
    assert "default_safe" in profiles
    assert "high_risk_pii" in profiles
    assert len(profiles) == 2


def test_pii_profile_has_email_pattern() -> None:
    """PII profile should have regex for email detection."""
    p = HIGH_RISK_PII
    email_patterns = [pat for pat in p.redact_body_patterns if "@" in pat]
    assert len(email_patterns) >= 1


def test_pii_profile_has_phone_pattern() -> None:
    """PII profile should have regex for phone number detection."""
    p = HIGH_RISK_PII
    phone_patterns = [pat for pat in p.redact_body_patterns if "\\d{3}" in pat]
    assert len(phone_patterns) >= 1
