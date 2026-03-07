"""Tests for method-aware risk classification capping.

GET/HEAD/OPTIONS (read-only) methods should be capped at medium risk,
regardless of path keywords. Write methods (POST, PUT, PATCH, DELETE)
keep their full risk classification.
"""

from __future__ import annotations

from toolwright.core.normalize.aggregator import EndpointAggregator
from toolwright.models.capture import CaptureSession, HttpExchange, HTTPMethod


def _make_session(
    exchanges: list[HttpExchange],
    host: str = "store.myshopify.com",
) -> CaptureSession:
    return CaptureSession(
        id="test-session",
        name="test",
        source="manual",
        exchanges=exchanges,
        allowed_hosts=[host],
    )


def _classify(
    method: HTTPMethod,
    path: str,
    host: str = "store.myshopify.com",
) -> str:
    """Helper: create an exchange, aggregate, return the risk_tier."""
    url = f"https://{host}{path}"
    exchange = HttpExchange(
        url=url,
        method=method,
        host=host,
        path=path,
        response_status=200,
    )
    aggregator = EndpointAggregator(first_party_hosts=[host])
    endpoints = aggregator.aggregate(_make_session([exchange], host=host))
    assert len(endpoints) == 1, f"Expected 1 endpoint, got {len(endpoints)}"
    return endpoints[0].risk_tier


# --- Read-only methods should be capped at medium ---


def test_get_admin_path_capped_at_medium() -> None:
    """GET /admin/... should be capped at medium, not critical."""
    tier = _classify(HTTPMethod.GET, "/admin/api/2024-01/products.json")
    assert tier == "medium", f"Expected medium, got {tier}"


def test_get_payments_path_capped_at_medium() -> None:
    """GET /admin/api/.../payments/refunds.json should be capped at medium."""
    tier = _classify(HTTPMethod.GET, "/admin/api/2024-01/payments/refunds.json")
    assert tier == "medium", f"Expected medium, got {tier}"


# --- Write methods keep full classification ---


def test_delete_admin_path_stays_critical() -> None:
    """DELETE /admin/... should remain critical."""
    tier = _classify(HTTPMethod.DELETE, "/admin/api/2024-01/products/123.json")
    assert tier == "critical", f"Expected critical, got {tier}"


def test_post_admin_path_stays_critical() -> None:
    """POST /admin/... should remain critical."""
    tier = _classify(HTTPMethod.POST, "/admin/api/2024-01/products.json")
    assert tier == "critical", f"Expected critical, got {tier}"


def test_put_admin_path_stays_critical() -> None:
    """PUT /admin/... should remain critical."""
    tier = _classify(HTTPMethod.PUT, "/admin/api/2024-01/products/123.json")
    assert tier == "critical", f"Expected critical, got {tier}"


# --- Non-keyword paths are unaffected ---


def test_get_safe_path_unchanged() -> None:
    """GET on a path with no risk keywords should stay safe."""
    tier = _classify(HTTPMethod.GET, "/api/products.json")
    assert tier == "safe", f"Expected safe, got {tier}"


def test_get_auth_path_capped_at_medium() -> None:
    """GET /api/auth/login should be capped at medium even though auth-related."""
    tier = _classify(HTTPMethod.GET, "/api/auth/login")
    assert tier == "medium", f"Expected medium, got {tier}"
