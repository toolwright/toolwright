"""WebMCP capture — discover tools declared by websites via navigator.modelContext.

WebMCP (W3C draft, Feb 2026) allows websites to register JavaScript tools that
AI agents can invoke via structured schemas. Toolwright captures these declarations
(not executions) and converts them to CaptureSession for the standard compile pipeline.

Supports:
- navigator.modelContext.provideContext() (W3C WebMCP)
- navigator.modelContext.registerTool() (W3C WebMCP)
- window.__MCP_B_TOOLS__ (MCP-B polyfill)
- <meta name="mcp-tools"> / <link rel="mcp-tools"> (HTML manifest)
- /.well-known/mcp-tools.json (convention)
"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

from pydantic import BaseModel, Field


class WebMCPTool(BaseModel):
    """A tool discovered via WebMCP."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    source_url: str = ""
    source_method: str = "webmcp"  # webmcp, mcp_b, meta_tag, well_known
    discovered_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


# JavaScript to inject into the page to extract WebMCP tool registrations.
# We override navigator.modelContext to intercept tool registrations,
# then also check MCP-B polyfill and meta tags.
EXTRACTION_SCRIPT = """
() => {
    const tools = [];

    // 1. Check navigator.modelContext (W3C WebMCP)
    if (window.navigator && window.navigator.modelContext) {
        const mc = window.navigator.modelContext;
        // Try to read registered tools
        if (mc._tools) {
            for (const t of mc._tools) {
                tools.push({
                    name: t.name || '',
                    description: t.description || '',
                    inputSchema: t.inputSchema || {},
                    source: 'webmcp'
                });
            }
        }
        if (mc.tools) {
            const mcTools = typeof mc.tools === 'function' ? mc.tools() : mc.tools;
            if (Array.isArray(mcTools)) {
                for (const t of mcTools) {
                    tools.push({
                        name: t.name || '',
                        description: t.description || '',
                        inputSchema: t.inputSchema || {},
                        source: 'webmcp'
                    });
                }
            }
        }
    }

    // 2. Check MCP-B polyfill (window.__MCP_B_TOOLS__)
    if (window.__MCP_B_TOOLS__ && Array.isArray(window.__MCP_B_TOOLS__)) {
        for (const t of window.__MCP_B_TOOLS__) {
            tools.push({
                name: t.name || '',
                description: t.description || '',
                inputSchema: t.inputSchema || t.input_schema || {},
                source: 'mcp_b'
            });
        }
    }

    // 3. Check __MCP_TOOLS__ (generic polyfill)
    if (window.__MCP_TOOLS__ && Array.isArray(window.__MCP_TOOLS__)) {
        for (const t of window.__MCP_TOOLS__) {
            tools.push({
                name: t.name || '',
                description: t.description || '',
                inputSchema: t.inputSchema || t.input_schema || {},
                source: 'mcp_b'
            });
        }
    }

    // 4. Check <meta name="mcp-tools"> or <link rel="mcp-tools">
    const metaTools = document.querySelector('meta[name="mcp-tools"]');
    if (metaTools) {
        try {
            const parsed = JSON.parse(metaTools.getAttribute('content'));
            if (Array.isArray(parsed)) {
                for (const t of parsed) {
                    tools.push({
                        name: t.name || '',
                        description: t.description || '',
                        inputSchema: t.inputSchema || {},
                        source: 'meta_tag'
                    });
                }
            }
        } catch(e) {}
    }

    const linkTools = document.querySelector('link[rel="mcp-tools"]');
    const linkHref = linkTools ? linkTools.getAttribute('href') : null;

    // Deduplicate by name
    const seen = new Set();
    const unique = [];
    for (const t of tools) {
        if (!seen.has(t.name)) {
            seen.add(t.name);
            unique.push(t);
        }
    }

    return {
        tools: unique,
        linkToolsHref: linkHref,
        hasModelContext: !!(window.navigator && window.navigator.modelContext),
        hasMcpB: !!window.__MCP_B_TOOLS__
    };
}
"""


def parse_webmcp_result(
    result: dict[str, Any],
    source_url: str,
) -> list[WebMCPTool]:
    """Parse the extraction script result into WebMCPTool objects."""
    tools: list[WebMCPTool] = []
    raw_tools = result.get("tools", [])
    if not isinstance(raw_tools, list):
        return tools

    for raw in raw_tools:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name", "")).strip()
        if not name:
            continue
        tools.append(WebMCPTool(
            name=name,
            description=str(raw.get("description", "")),
            input_schema=_coerce_input_schema(raw.get("inputSchema")),
            source_url=source_url,
            source_method=str(raw.get("source", "webmcp")),
        ))

    return tools


async def discover_webmcp_tools(
    page: Any,  # playwright Page object
    source_url: str,
    timeout_ms: int = 5000,
) -> list[WebMCPTool]:
    """Discover WebMCP tools on a loaded page.

    Injects extraction script and returns discovered tools.
    Also checks /.well-known/mcp-tools.json as fallback.
    """
    # Wait a bit for tool registrations to complete
    with suppress(Exception):
        await page.wait_for_timeout(min(timeout_ms, 3000))

    # Run extraction script
    result = await page.evaluate(EXTRACTION_SCRIPT)
    if not isinstance(result, dict):
        result = {}

    tools = parse_webmcp_result(result, source_url)

    # Check <link rel="mcp-tools"> manifest if present
    link_href = result.get("linkToolsHref")
    if link_href:
        manifest_url = urljoin(source_url, link_href)
        manifest_tools = await _fetch_manifest(page, manifest_url, source_url)
        # Add tools not already discovered
        existing_names = {t.name for t in tools}
        for t in manifest_tools:
            if t.name not in existing_names:
                tools.append(t)

    # Try well-known manifest as last resort
    if not tools:
        well_known_url = urljoin(source_url, "/.well-known/mcp-tools.json")
        well_known_tools = await _fetch_manifest(page, well_known_url, source_url)
        tools.extend(well_known_tools)

    return tools


async def _fetch_manifest(
    page: Any,
    manifest_url: str,
    source_url: str,
) -> list[WebMCPTool]:
    """Fetch and parse a JSON manifest of MCP tools."""
    try:
        response = await page.evaluate(f"""
            async () => {{
                try {{
                    const resp = await fetch("{manifest_url}");
                    if (!resp.ok) return null;
                    return await resp.json();
                }} catch(e) {{
                    return null;
                }}
            }}
        """)
        if not response:
            return []

        raw_tools = response if isinstance(response, list) else response.get("tools", [])
        tools: list[WebMCPTool] = []
        for raw in raw_tools:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name", "")).strip()
            if not name:
                continue
            tools.append(WebMCPTool(
                name=name,
                description=str(raw.get("description", "")),
                input_schema=_coerce_input_schema(
                    raw.get("inputSchema", raw.get("input_schema")),
                ),
                source_url=source_url,
                source_method="well_known",
            ))
        return tools
    except Exception:
        return []


def webmcp_tools_to_exchanges(
    tools: list[WebMCPTool],
    source_url: str,
) -> list[dict[str, Any]]:
    """Convert WebMCP tools into HttpExchange-compatible dicts.

    This allows WebMCP tools to flow through the standard capture -> compile pipeline.
    Each tool becomes a synthetic exchange that the compiler can recognize.
    """
    from urllib.parse import urlparse

    parsed = urlparse(source_url)
    host = parsed.netloc

    exchanges = []
    for tool in tools:
        exchanges.append({
            "url": f"{source_url}#webmcp-tool-{tool.name}",
            "method": "GET",  # Synthetic — WebMCP tools don't have HTTP methods
            "host": host,
            "path": f"/webmcp/{tool.name}",
            "response_status": 200,
            "response_body_json": {
                "webmcp_tool": True,
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            },
            "notes": {
                "webmcp_source": tool.source_method,
                "webmcp_tool_name": tool.name,
                "webmcp_discovered_at": tool.discovered_at,
            },
        })

    return exchanges


def _coerce_input_schema(raw_schema: Any) -> dict[str, Any]:
    """Normalize discovered input schema payloads to dict."""
    if isinstance(raw_schema, dict):
        return raw_schema
    return {}
