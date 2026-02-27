"""Tests for aggregator handling of list response bodies."""

from __future__ import annotations

from toolwright.core.normalize.aggregator import EndpointAggregator
from toolwright.models.capture import CaptureSession, HttpExchange, HTTPMethod


def _make_session(exchanges: list[HttpExchange]) -> CaptureSession:
    return CaptureSession(
        id="test-session",
        name="test",
        source="manual",
        exchanges=exchanges,
        allowed_hosts=["api.example.com"],
    )


def test_list_response_body_produces_schema() -> None:
    """List response bodies like [{...}, ...] should produce response_body_schema."""
    exchange = HttpExchange(
        url="https://api.example.com/posts",
        method=HTTPMethod.GET,
        host="api.example.com",
        path="/posts",
        response_status=200,
        response_body_json=[
            {"id": 1, "title": "Hello", "published": True},
            {"id": 2, "title": "World", "published": False},
        ],
        response_content_type="application/json",
    )

    aggregator = EndpointAggregator(first_party_hosts=["api.example.com"])
    endpoints = aggregator.aggregate(_make_session([exchange]))

    assert len(endpoints) == 1
    ep = endpoints[0]
    assert ep.response_body_schema is not None
    assert ep.response_body_schema.get("type") == "array"
    items = ep.response_body_schema.get("items", {})
    assert isinstance(items, dict)
    # Items schema should have properties from the list elements
    props = items.get("properties", {})
    assert "id" in props
    assert "title" in props
    assert "published" in props


def test_list_request_body_produces_schema() -> None:
    """List request bodies should also produce request_body_schema."""
    exchange = HttpExchange(
        url="https://api.example.com/batch",
        method=HTTPMethod.POST,
        host="api.example.com",
        path="/batch",
        request_body_json=[
            {"action": "create", "name": "foo"},
            {"action": "update", "name": "bar"},
        ],
        response_status=200,
        response_content_type="application/json",
    )

    aggregator = EndpointAggregator(first_party_hosts=["api.example.com"])
    endpoints = aggregator.aggregate(_make_session([exchange]))

    assert len(endpoints) == 1
    ep = endpoints[0]
    assert ep.request_body_schema is not None
    assert ep.request_body_schema.get("type") == "array"
    items = ep.request_body_schema.get("items", {})
    assert isinstance(items, dict)
    props = items.get("properties", {})
    assert "action" in props
    assert "name" in props
