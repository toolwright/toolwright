"""Tests for keyword-based risk tier inference in EndpointAggregator."""

from __future__ import annotations

from toolwright.core.normalize import EndpointAggregator
from toolwright.models.capture import CaptureSession, CaptureSource, HttpExchange, HTTPMethod


def test_payment_path_get_capped_at_medium() -> None:
    """GET requests to payment paths are capped at medium (read-only cap)."""
    session = CaptureSession(
        id="cap_risk_keywords",
        name="Risk Keywords",
        source=CaptureSource.HAR,
        allowed_hosts=["api.example.com"],
        exchanges=[
            HttpExchange(
                url="https://api.example.com/api/clientpaymenttoken/buy",
                method=HTTPMethod.GET,
                host="api.example.com",
                path="/api/clientpaymenttoken/buy",
                response_status=200,
                response_content_type="application/json",
            )
        ],
    )
    endpoints = EndpointAggregator(first_party_hosts=["api.example.com"]).aggregate(session)
    assert len(endpoints) == 1
    assert endpoints[0].risk_tier == "medium"


def test_payment_path_post_stays_critical() -> None:
    """POST requests to payment paths remain critical (write method)."""
    session = CaptureSession(
        id="cap_risk_keywords",
        name="Risk Keywords",
        source=CaptureSource.HAR,
        allowed_hosts=["api.example.com"],
        exchanges=[
            HttpExchange(
                url="https://api.example.com/api/clientpaymenttoken/buy",
                method=HTTPMethod.POST,
                host="api.example.com",
                path="/api/clientpaymenttoken/buy",
                response_status=200,
                response_content_type="application/json",
            )
        ],
    )
    endpoints = EndpointAggregator(first_party_hosts=["api.example.com"]).aggregate(session)
    assert len(endpoints) == 1
    assert endpoints[0].risk_tier == "critical"

