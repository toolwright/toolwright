"""Tests for auth requirement detection."""

from __future__ import annotations

from toolwright.core.auth.detector import (
    AuthRequirement,
    check_session_auth_coverage,
    detect_auth_requirements,
)
from toolwright.models.capture import CaptureSession, CaptureSource, HttpExchange


def _make_session(exchanges: list[HttpExchange]) -> CaptureSession:
    return CaptureSession(
        id="cap_test",
        source=CaptureSource.PLAYWRIGHT,
        allowed_hosts=["api.example.com"],
        exchanges=exchanges,
        total_requests=len(exchanges),
    )


def _exchange(
    *,
    method: str = "GET",
    url: str = "https://api.example.com/data",
    status: int = 200,
    request_headers: dict | None = None,
    response_headers: dict | None = None,
) -> HttpExchange:
    return HttpExchange(
        url=url,
        method=method,
        response_status=status,
        request_headers=request_headers or {},
        response_headers=response_headers or {},
    )


# --- Auth detection ---

def test_no_auth_needed_for_public_api() -> None:
    session = _make_session([
        _exchange(status=200),
        _exchange(url="https://api.example.com/users", status=200),
    ])
    req = detect_auth_requirements(session)
    assert req.requires_auth is False


def test_detects_401_as_auth_required() -> None:
    session = _make_session([
        _exchange(status=401),
    ])
    req = detect_auth_requirements(session)
    assert req.requires_auth is True
    assert len(req.protected_endpoints) == 1
    assert "401/403" in req.evidence[0]


def test_detects_403_as_auth_required() -> None:
    session = _make_session([
        _exchange(url="https://api.example.com/admin", status=403),
    ])
    req = detect_auth_requirements(session)
    assert req.requires_auth is True


def test_detects_login_redirect() -> None:
    session = _make_session([
        _exchange(
            status=302,
            response_headers={"Location": "https://api.example.com/login"},
        ),
    ])
    req = detect_auth_requirements(session)
    assert req.requires_auth is True
    assert req.login_url == "https://api.example.com/login"
    assert "redirected to login" in req.evidence[0]


def test_detects_bearer_auth() -> None:
    session = _make_session([
        _exchange(
            request_headers={"Authorization": "Bearer token123"},
            status=200,
        ),
    ])
    req = detect_auth_requirements(session)
    assert req.auth_type == "bearer"


def test_detects_api_key_auth() -> None:
    session = _make_session([
        _exchange(
            request_headers={"X-API-Key": "key123"},
            status=200,
        ),
    ])
    req = detect_auth_requirements(session)
    assert req.auth_type == "api_key"


def test_detects_cookie_auth() -> None:
    session = _make_session([
        _exchange(
            status=401,
        ),
        _exchange(
            status=200,
            response_headers={"Set-Cookie": "session=abc; HttpOnly"},
        ),
    ])
    req = detect_auth_requirements(session)
    assert req.requires_auth is True
    assert req.auth_type == "cookie"


def test_suggestion_when_auth_needed() -> None:
    session = _make_session([_exchange(status=401)])
    req = detect_auth_requirements(session)
    assert "toolwright auth login" in req.suggestion


def test_to_dict() -> None:
    req = AuthRequirement(requires_auth=True, auth_type="bearer")
    d = req.to_dict()
    assert d["requires_auth"] is True
    assert d["auth_type"] == "bearer"


# --- Auth coverage ---

def test_coverage_all_public() -> None:
    session = _make_session([
        _exchange(status=200),
        _exchange(status=200),
    ])
    cov = check_session_auth_coverage(session)
    assert cov["coverage"] == 1.0
    assert cov["denied"] == 0


def test_coverage_with_denials() -> None:
    session = _make_session([
        _exchange(status=200),
        _exchange(status=401),
        _exchange(status=200),
        _exchange(status=403),
    ])
    cov = check_session_auth_coverage(session)
    assert cov["total"] == 4
    assert cov["denied"] == 2
    assert cov["coverage"] == 0.5


def test_coverage_empty_session() -> None:
    session = _make_session([])
    cov = check_session_auth_coverage(session)
    assert cov["total"] == 0
    assert cov["coverage"] == 1.0
