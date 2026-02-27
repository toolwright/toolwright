"""Tests for WebMCP wiring into mint pipeline."""

from __future__ import annotations

from toolwright.core.capture.webmcp_capture import (
    WebMCPTool,
    webmcp_tools_to_exchanges,
)
from toolwright.models.capture import CaptureSource, HttpExchange


class TestWebMCPToExchanges:
    def test_tools_converted_to_exchanges(self) -> None:
        """WebMCP tools should be converted to HttpExchange-compatible dicts."""
        tools = [
            WebMCPTool(
                name="search_products",
                description="Search for products",
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
                source_url="https://example.com",
                source_method="webmcp",
            ),
        ]
        exchanges = webmcp_tools_to_exchanges(tools, "https://example.com")
        assert len(exchanges) == 1
        ex = exchanges[0]
        assert ex["method"] == "GET"
        assert ex["path"] == "/webmcp/search_products"
        assert ex["host"] == "example.com"
        assert ex["response_body_json"]["webmcp_tool"] is True
        assert ex["response_body_json"]["name"] == "search_products"

    def test_multiple_tools_converted(self) -> None:
        """Multiple tools should produce multiple exchanges."""
        tools = [
            WebMCPTool(name="tool_a", source_url="https://example.com"),
            WebMCPTool(name="tool_b", source_url="https://example.com"),
        ]
        exchanges = webmcp_tools_to_exchanges(tools, "https://example.com")
        assert len(exchanges) == 2
        paths = {ex["path"] for ex in exchanges}
        assert "/webmcp/tool_a" in paths
        assert "/webmcp/tool_b" in paths

    def test_empty_tools_returns_empty(self) -> None:
        """Empty tools list should return empty exchanges."""
        exchanges = webmcp_tools_to_exchanges([], "https://example.com")
        assert exchanges == []

    def test_exchanges_can_be_merged_into_session(self) -> None:
        """WebMCP exchange dicts should be convertible to HttpExchange objects."""
        tools = [
            WebMCPTool(
                name="add_to_cart",
                description="Add item to cart",
                source_url="https://shop.example.com",
            ),
        ]
        exchange_dicts = webmcp_tools_to_exchanges(tools, "https://shop.example.com")
        # Verify the dict has the fields needed for HttpExchange construction
        d = exchange_dicts[0]
        exchange = HttpExchange(
            url=d["url"],
            method=d["method"],
            host=d["host"],
            path=d["path"],
            request_headers={},
            response_status=d["response_status"],
            response_headers={},
            response_body_json=d["response_body_json"],
            source=CaptureSource.PLAYWRIGHT,
            notes=d["notes"],
        )
        assert exchange.host == "shop.example.com"
        assert exchange.path == "/webmcp/add_to_cart"
        assert exchange.notes["webmcp_tool_name"] == "add_to_cart"
