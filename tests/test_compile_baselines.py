"""Tests for compile_baselines() — shape baseline compilation from captured exchanges.

Covers: exchange-to-tool matching, shape inference from response bodies,
probe template generation, empty/missing responses, and multi-exchange merging.
"""
from __future__ import annotations

from typing import Any

from toolwright.models.baseline import BaselineIndex
from toolwright.models.capture import CaptureSession, CaptureSource, HttpExchange


def _make_session(
    exchanges: list[dict[str, Any]],
    allowed_hosts: list[str] | None = None,
) -> CaptureSession:
    """Build a minimal CaptureSession from exchange specs."""
    exs = []
    for ex in exchanges:
        exs.append(
            HttpExchange(
                url=ex.get("url", "https://api.example.com/products"),
                method=ex.get("method", "GET"),
                response_status=ex.get("status", 200),
                response_body_json=ex.get("response_json"),
                response_content_type=ex.get("content_type", "application/json"),
            )
        )
    return CaptureSession(
        id="cap_test",
        name="Test",
        allowed_hosts=allowed_hosts or ["api.example.com"],
        exchanges=exs,
        source=CaptureSource.HAR,
    )


def _make_manifest(actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a minimal tools manifest from action specs."""
    return {
        "name": "Test Tools",
        "actions": actions,
        "allowed_hosts": ["api.example.com"],
    }


class TestCompileBaselinesBasic:
    def test_single_tool_single_exchange(self):
        """One exchange with JSON body -> one baseline entry."""
        from toolwright.core.drift.baselines import compile_shape_baselines

        session = _make_session([
            {
                "url": "https://api.example.com/products",
                "method": "GET",
                "response_json": {"products": [{"id": 1, "title": "Widget"}]},
            },
        ])
        manifest = _make_manifest([
            {
                "name": "list_products",
                "method": "GET",
                "host": "api.example.com",
                "path": "/products",
            },
        ])

        index = compile_shape_baselines(session, manifest)

        assert isinstance(index, BaselineIndex)
        assert "list_products" in index.baselines

        bl = index.baselines["list_products"]
        assert bl.shape.sample_count == 1
        assert bl.source == "har"
        assert bl.probe_template.method == "GET"
        assert bl.probe_template.path == "/products"
        assert bl.content_hash == bl.shape.content_hash()

    def test_multiple_exchanges_merge_shapes(self):
        """Multiple exchanges for same tool -> merged shape."""
        from toolwright.core.drift.baselines import compile_shape_baselines

        session = _make_session([
            {
                "url": "https://api.example.com/products",
                "method": "GET",
                "response_json": {"products": [{"id": 1, "title": "A"}]},
            },
            {
                "url": "https://api.example.com/products",
                "method": "GET",
                "response_json": {"products": [{"id": 2, "title": "B", "tags": ["new"]}]},
            },
        ])
        manifest = _make_manifest([
            {
                "name": "list_products",
                "method": "GET",
                "host": "api.example.com",
                "path": "/products",
            },
        ])

        index = compile_shape_baselines(session, manifest)
        bl = index.baselines["list_products"]

        # 2 exchanges merged
        assert bl.shape.sample_count == 2

        # Should have fields from both responses
        assert ".products[].id" in bl.shape.fields
        assert ".products[].title" in bl.shape.fields
        assert ".products[].tags" in bl.shape.fields  # only in 2nd exchange


class TestCompileBaselinesNoResponseBody:
    def test_exchange_without_json_body_skipped(self):
        """Exchanges without response_body_json are skipped."""
        from toolwright.core.drift.baselines import compile_shape_baselines

        session = _make_session([
            {
                "url": "https://api.example.com/products",
                "method": "GET",
                "response_json": None,  # No JSON body
            },
        ])
        manifest = _make_manifest([
            {
                "name": "list_products",
                "method": "GET",
                "host": "api.example.com",
                "path": "/products",
            },
        ])

        index = compile_shape_baselines(session, manifest)
        assert len(index.baselines) == 0

    def test_no_matching_exchanges(self):
        """No exchanges match any tool -> empty index."""
        from toolwright.core.drift.baselines import compile_shape_baselines

        session = _make_session([
            {
                "url": "https://api.example.com/orders",
                "method": "GET",
                "response_json": {"orders": []},
            },
        ])
        manifest = _make_manifest([
            {
                "name": "list_products",
                "method": "GET",
                "host": "api.example.com",
                "path": "/products",
            },
        ])

        index = compile_shape_baselines(session, manifest)
        assert len(index.baselines) == 0


class TestCompileBaselinesMultipleTools:
    def test_multiple_tools(self):
        """Exchanges for different tools -> separate baselines."""
        from toolwright.core.drift.baselines import compile_shape_baselines

        session = _make_session([
            {
                "url": "https://api.example.com/products",
                "method": "GET",
                "response_json": {"products": [{"id": 1}]},
            },
            {
                "url": "https://api.example.com/orders",
                "method": "GET",
                "response_json": {"orders": [{"id": 100}]},
            },
        ])
        manifest = _make_manifest([
            {
                "name": "list_products",
                "method": "GET",
                "host": "api.example.com",
                "path": "/products",
            },
            {
                "name": "list_orders",
                "method": "GET",
                "host": "api.example.com",
                "path": "/orders",
            },
        ])

        index = compile_shape_baselines(session, manifest)
        assert "list_products" in index.baselines
        assert "list_orders" in index.baselines


class TestCompileBaselinesProbeTemplate:
    def test_probe_template_from_first_exchange(self):
        """Probe template uses the first matching exchange's request info."""
        from toolwright.core.drift.baselines import compile_shape_baselines

        session = _make_session([
            {
                "url": "https://api.example.com/products?limit=50&fields=id,title",
                "method": "GET",
                "response_json": {"products": []},
            },
        ])
        manifest = _make_manifest([
            {
                "name": "list_products",
                "method": "GET",
                "host": "api.example.com",
                "path": "/products",
            },
        ])

        index = compile_shape_baselines(session, manifest)
        probe = index.baselines["list_products"].probe_template

        assert probe.method == "GET"
        assert probe.path == "/products"
        assert probe.query_params.get("limit") == "50"
        assert probe.query_params.get("fields") == "id,title"


class TestCompileBaselinesAuthRedaction:
    def test_auth_headers_stripped_from_probe(self):
        """Authorization and cookie headers must not appear in probe template."""
        from toolwright.core.drift.baselines import compile_shape_baselines

        session = _make_session([
            {
                "url": "https://api.example.com/products",
                "method": "GET",
                "response_json": {"products": []},
            },
        ])
        # Manually add auth headers to the exchange
        session.exchanges[0].request_headers = {
            "Authorization": "Bearer sk-live-secret",
            "Accept": "application/json",
            "Cookie": "session=abc123",
        }

        manifest = _make_manifest([
            {
                "name": "list_products",
                "method": "GET",
                "host": "api.example.com",
                "path": "/products",
            },
        ])

        index = compile_shape_baselines(session, manifest)
        probe = index.baselines["list_products"].probe_template

        # Auth headers must be stripped
        assert "Authorization" not in probe.headers
        assert "authorization" not in probe.headers
        assert "Cookie" not in probe.headers
        assert "cookie" not in probe.headers
        # Safe headers kept
        assert probe.headers.get("Accept") == "application/json"
