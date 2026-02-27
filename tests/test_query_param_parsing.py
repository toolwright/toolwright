"""Tests for query parameter parsing in EndpointAggregator."""

from __future__ import annotations

from toolwright.core.normalize import EndpointAggregator
from toolwright.models.capture import CaptureSession, CaptureSource, HttpExchange, HTTPMethod


def test_query_param_names_are_url_decoded() -> None:
    session = CaptureSession(
        id="cap_query_params",
        name="Query Param Decode",
        source=CaptureSource.HAR,
        allowed_hosts=["api.example.com"],
        exchanges=[
            HttpExchange(
                url=(
                    "https://api.example.com/api/p/csr/content_types/product_page_blurbs/entries"
                    "?query%5Bcontent_group%5D=hero&include%5B%5D=a&include%5B%5D=b"
                ),
                method=HTTPMethod.GET,
                host="api.example.com",
                path="/api/p/csr/content_types/product_page_blurbs/entries",
                response_status=200,
                response_content_type="application/json",
            )
        ],
    )
    endpoints = EndpointAggregator(first_party_hosts=["api.example.com"]).aggregate(session)
    assert len(endpoints) == 1
    names = {p.name for p in endpoints[0].parameters}
    assert "query[content_group]" in names
    assert "include[]" in names

