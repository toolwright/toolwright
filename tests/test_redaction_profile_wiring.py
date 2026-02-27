"""Tests for redaction profile wiring into Redactor."""

from __future__ import annotations

from toolwright.core.capture.redaction_profiles import (
    get_profile,
)
from toolwright.core.capture.redactor import Redactor
from toolwright.models.capture import CaptureSession, CaptureSource, HttpExchange


def _make_exchange(
    *,
    url: str = "https://api.example.com/users",
    method: str = "GET",
    request_headers: dict | None = None,
) -> HttpExchange:
    return HttpExchange(
        url=url,
        method=method,
        host="api.example.com",
        path="/users",
        request_headers=request_headers or {},
        response_status=200,
        response_headers={},
        source=CaptureSource.HAR,
    )


def _make_session(exchanges: list[HttpExchange]) -> CaptureSession:
    return CaptureSession(
        name="test",
        source=CaptureSource.HAR,
        allowed_hosts=["api.example.com"],
        exchanges=exchanges,
    )


class TestRedactorWithProfile:
    def test_default_safe_profile_redacts_standard_headers(self) -> None:
        """Default safe profile should redact auth headers."""
        profile = get_profile("default_safe")
        redactor = Redactor(profile=profile)
        exchange = _make_exchange(
            request_headers={"authorization": "Bearer secret123", "content-type": "application/json"}
        )
        redacted = redactor.redact_exchange(exchange)
        assert redacted.request_headers["authorization"] == "[REDACTED]"
        assert redacted.request_headers["content-type"] == "application/json"

    def test_high_risk_pii_profile_redacts_email_in_body(self) -> None:
        """High-risk PII profile should redact email patterns in bodies."""
        profile = get_profile("high_risk_pii")
        redactor = Redactor(profile=profile)
        # Manually create exchange with a body containing an email
        exchange_with_body = HttpExchange(
            url="https://api.example.com/users",
            method="POST",
            host="api.example.com",
            path="/users",
            request_headers={},
            request_body='{"email": "john@example.com", "name": "John"}',
            response_status=200,
            response_headers={},
            source=CaptureSource.HAR,
        )
        redacted = redactor.redact_exchange(exchange_with_body)
        assert "john@example.com" not in (redacted.request_body or "")

    def test_high_risk_pii_profile_redacts_phone_in_body(self) -> None:
        """High-risk PII profile should redact phone number patterns."""
        profile = get_profile("high_risk_pii")
        redactor = Redactor(profile=profile)
        exchange = HttpExchange(
            url="https://api.example.com/users",
            method="POST",
            host="api.example.com",
            path="/users",
            request_headers={},
            request_body='{"phone": "555-123-4567"}',
            response_status=200,
            response_headers={},
            source=CaptureSource.HAR,
        )
        redacted = redactor.redact_exchange(exchange)
        assert "555-123-4567" not in (redacted.request_body or "")

    def test_high_risk_pii_profile_redacts_extra_query_params(self) -> None:
        """High-risk PII profile should redact email/phone query params."""
        profile = get_profile("high_risk_pii")
        redactor = Redactor(profile=profile)
        exchange = HttpExchange(
            url="https://api.example.com/users?email=john@test.com&page=1",
            method="GET",
            host="api.example.com",
            path="/users",
            request_headers={},
            response_status=200,
            response_headers={},
            source=CaptureSource.HAR,
        )
        redacted = redactor.redact_exchange(exchange)
        assert "john@test.com" not in redacted.url

    def test_profile_max_body_chars_applied(self) -> None:
        """Profile's max_body_chars should be used for truncation."""
        profile = get_profile("high_risk_pii")
        redactor = Redactor(profile=profile)
        # high_risk_pii has max_body_chars=2048
        assert redactor.MAX_BODY_CHARS == 2048

    def test_no_profile_uses_defaults(self) -> None:
        """Redactor without profile should use built-in defaults."""
        redactor = Redactor()
        assert redactor.MAX_BODY_CHARS == 4096

    def test_profile_extra_headers_merged(self) -> None:
        """Profile headers should be added to redactor's sensitive headers."""
        profile = get_profile("high_risk_pii")
        redactor = Redactor(profile=profile)
        # high_risk_pii adds x-real-ip, x-client-ip
        assert "x-real-ip" in redactor.headers
        assert "x-client-ip" in redactor.headers

    def test_session_level_redaction_with_profile(self) -> None:
        """Full session redaction should work with profile."""
        profile = get_profile("default_safe")
        redactor = Redactor(profile=profile)
        session = _make_session([
            _make_exchange(request_headers={"authorization": "Bearer tok123"}),
        ])
        redacted = redactor.redact_session(session)
        assert redacted.exchanges[0].request_headers["authorization"] == "[REDACTED]"
