"""Tests for richer heuristic descriptions (Phase 2.3)."""

from __future__ import annotations

from toolwright.core.compile.tools import ToolManifestGenerator
from toolwright.models.endpoint import Endpoint


def _ep(
    method: str = "GET",
    path: str = "/api/v1/items",
    tags: list[str] | None = None,
    response_body_schema: dict | None = None,
    risk_tier: str = "safe",
) -> Endpoint:
    return Endpoint(
        method=method,
        path=path,
        host="api.example.com",
        url=f"https://api.example.com{path}",
        tags=tags or [],
        response_body_schema=response_body_schema,
        risk_tier=risk_tier,
    )


class TestTagBasedGuidance:
    """Tool descriptions should include 'Use this to...' guidance from tags."""

    def test_commerce_tag_adds_guidance(self):
        gen = ToolManifestGenerator()
        ep = _ep(
            path="/api/v1/orders",
            tags=["orders", "commerce", "read", "listing"],
        )
        desc = gen._generate_description(ep)
        assert "Use this to" in desc

    def test_users_tag_adds_guidance(self):
        gen = ToolManifestGenerator()
        ep = _ep(
            path="/api/v1/users",
            tags=["users", "read", "listing"],
        )
        desc = gen._generate_description(ep)
        assert "Use this to" in desc

    def test_auth_tag_adds_guidance(self):
        gen = ToolManifestGenerator()
        ep = _ep(
            method="POST",
            path="/api/v1/auth/login",
            tags=["auth", "write"],
        )
        desc = gen._generate_description(ep)
        assert "Use this to" in desc

    def test_no_tag_no_guidance(self):
        """If no recognized domain tag, no 'Use this to' prefix."""
        gen = ToolManifestGenerator()
        ep = _ep(path="/api/v1/misc", tags=["read"])
        desc = gen._generate_description(ep)
        # Should still have a valid description, just without guidance
        assert desc  # non-empty
        assert "Use this to" not in desc


class TestResponseSchemaInDescription:
    """Descriptions should include response field types for top fields."""

    def test_response_fields_with_types(self):
        gen = ToolManifestGenerator()
        ep = _ep(
            path="/api/v1/products",
            response_body_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "price": {"type": "number"},
                },
            },
        )
        desc = gen._generate_description(ep)
        assert "Returns:" in desc


class TestMCPServerDescription:
    """The MCP server's _build_description should use enriched descriptions."""

    def test_build_description_uses_action_desc(self):
        """_build_description should pass through the action's description."""
        from toolwright.mcp.server import ToolwrightMCPServer

        action = {
            "name": "get_orders",
            "description": "Use this to browse orders. List all orders. Returns: id, total, status",
            "method": "GET",
            "path": "/api/v1/orders",
            "risk_tier": "safe",
        }
        # ToolwrightMCPServer._build_description is a regular method
        # but we can test it directly by constructing a minimal instance
        # Actually, it's simpler to just call it as an unbound method
        desc = ToolwrightMCPServer._build_description(None, action)
        assert "Use this to browse orders" in desc
