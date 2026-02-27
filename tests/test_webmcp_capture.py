"""Tests for WebMCP capture — tool discovery, parsing, and conversion."""

from __future__ import annotations

from toolwright.core.capture.webmcp_capture import (
    WebMCPTool,
    parse_webmcp_result,
    webmcp_tools_to_exchanges,
)
from toolwright.models.capture import CaptureSource

# --- WebMCPTool model ---

def test_webmcp_tool_defaults() -> None:
    tool = WebMCPTool(name="search")
    assert tool.name == "search"
    assert tool.description == ""
    assert tool.input_schema == {}
    assert tool.source_method == "webmcp"
    assert tool.discovered_at  # non-empty


def test_webmcp_tool_with_schema() -> None:
    tool = WebMCPTool(
        name="create_task",
        description="Create a new task",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title"},
                "priority": {"type": "number"},
            },
            "required": ["title"],
        },
        source_url="https://app.example.com",
    )
    assert tool.input_schema["properties"]["title"]["type"] == "string"
    assert "title" in tool.input_schema["required"]


# --- parse_webmcp_result ---

def test_parse_empty_result() -> None:
    tools = parse_webmcp_result({}, "https://example.com")
    assert tools == []


def test_parse_webmcp_tools() -> None:
    result = {
        "tools": [
            {
                "name": "search_products",
                "description": "Search the product catalog",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
                "source": "webmcp",
            },
            {
                "name": "add_to_cart",
                "description": "Add item to shopping cart",
                "inputSchema": {
                    "type": "object",
                    "properties": {"product_id": {"type": "string"}},
                },
                "source": "webmcp",
            },
        ],
        "hasModelContext": True,
        "hasMcpB": False,
    }
    tools = parse_webmcp_result(result, "https://shop.example.com")
    assert len(tools) == 2
    assert tools[0].name == "search_products"
    assert tools[0].source_method == "webmcp"
    assert tools[1].name == "add_to_cart"
    assert tools[0].source_url == "https://shop.example.com"


def test_parse_mcp_b_tools() -> None:
    result = {
        "tools": [
            {
                "name": "get_weather",
                "description": "Get weather for a location",
                "inputSchema": {"type": "object", "properties": {"city": {"type": "string"}}},
                "source": "mcp_b",
            }
        ],
        "hasMcpB": True,
    }
    tools = parse_webmcp_result(result, "https://weather.example.com")
    assert len(tools) == 1
    assert tools[0].source_method == "mcp_b"


def test_parse_meta_tag_tools() -> None:
    result = {
        "tools": [
            {
                "name": "translate",
                "description": "Translate text",
                "inputSchema": {},
                "source": "meta_tag",
            }
        ],
    }
    tools = parse_webmcp_result(result, "https://translate.example.com")
    assert len(tools) == 1
    assert tools[0].source_method == "meta_tag"


def test_parse_skips_empty_names() -> None:
    result = {
        "tools": [
            {"name": "", "description": "No name"},
            {"name": "valid", "description": "Has a name"},
        ]
    }
    tools = parse_webmcp_result(result, "https://example.com")
    assert len(tools) == 1
    assert tools[0].name == "valid"


def test_parse_skips_non_dict_entries() -> None:
    result = {"tools": ["not_a_dict", 42, None, {"name": "ok"}]}
    tools = parse_webmcp_result(result, "https://example.com")
    assert len(tools) == 1


def test_parse_no_tools_key() -> None:
    result = {"hasModelContext": False}
    tools = parse_webmcp_result(result, "https://example.com")
    assert tools == []


# --- webmcp_tools_to_exchanges ---

def test_tools_to_exchanges_basic() -> None:
    tools = [
        WebMCPTool(
            name="search",
            description="Search items",
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
            source_url="https://app.example.com",
        ),
    ]
    exchanges = webmcp_tools_to_exchanges(tools, "https://app.example.com")
    assert len(exchanges) == 1
    ex = exchanges[0]
    assert ex["method"] == "GET"
    assert ex["host"] == "app.example.com"
    assert ex["path"] == "/webmcp/search"
    assert ex["response_status"] == 200
    body = ex["response_body_json"]
    assert body["webmcp_tool"] is True
    assert body["name"] == "search"
    assert body["description"] == "Search items"
    assert body["inputSchema"]["properties"]["q"]["type"] == "string"


def test_tools_to_exchanges_preserves_notes() -> None:
    tools = [
        WebMCPTool(name="action", source_method="mcp_b", source_url="https://x.com"),
    ]
    exchanges = webmcp_tools_to_exchanges(tools, "https://x.com")
    assert exchanges[0]["notes"]["webmcp_source"] == "mcp_b"
    assert exchanges[0]["notes"]["webmcp_tool_name"] == "action"


def test_tools_to_exchanges_multiple() -> None:
    tools = [
        WebMCPTool(name="a", source_url="https://x.com"),
        WebMCPTool(name="b", source_url="https://x.com"),
        WebMCPTool(name="c", source_url="https://x.com"),
    ]
    exchanges = webmcp_tools_to_exchanges(tools, "https://x.com")
    assert len(exchanges) == 3
    paths = {e["path"] for e in exchanges}
    assert paths == {"/webmcp/a", "/webmcp/b", "/webmcp/c"}


def test_tools_to_exchanges_empty() -> None:
    exchanges = webmcp_tools_to_exchanges([], "https://x.com")
    assert exchanges == []


# --- CaptureSource enum ---

def test_capture_source_has_webmcp() -> None:
    assert CaptureSource.WEBMCP == "webmcp"
    assert "webmcp" in [s.value for s in CaptureSource]
