"""Tests for tool description generation quality."""

from __future__ import annotations

from toolwright.core.compile.tools import ToolManifestGenerator
from toolwright.models.endpoint import Endpoint


def _make_endpoint(
    method: str, path: str,
    response_schema: dict | None = None,
    tags: list[str] | None = None,
) -> Endpoint:
    return Endpoint(
        method=method,
        host="api.example.com",
        path=path,
        signature_id="test",
        response_body_schema=response_schema,
        tags=tags or [],
    )


class TestDescriptionArticle:
    """Article usage: 'a' vs 'an'."""

    def setup_method(self) -> None:
        self.gen = ToolManifestGenerator()

    def test_a_before_consonant(self) -> None:
        ep = _make_endpoint("DELETE", "/api/users/{user_id}/orders/{order_id}")
        desc = self.gen._generate_description(ep)
        assert "a order" not in desc.lower()
        assert "an order" in desc.lower() or "order" in desc.lower()

    def test_a_before_vowel_resource(self) -> None:
        """POST create uses 'a new X' pattern; article applies to 'new'."""
        ep = _make_endpoint("POST", "/api/invoices")
        desc = self.gen._generate_description(ep)
        assert "a new invoice" in desc.lower()

    def test_retrieve_vowel_resource_uses_an(self) -> None:
        """GET detail on vowel-starting resource uses 'an'."""
        ep = _make_endpoint("GET", "/api/invoices/{id}")
        desc = self.gen._generate_description(ep)
        assert "an invoice" in desc.lower()

    def test_a_before_consonant_resource(self) -> None:
        ep = _make_endpoint("POST", "/api/products")
        desc = self.gen._generate_description(ep)
        assert "a product" in desc.lower() or "a new product" in desc.lower()


class TestDescriptionSpecialPaths:
    """Special path detection (search, graphql, health)."""

    def setup_method(self) -> None:
        self.gen = ToolManifestGenerator()

    def test_post_search_not_create(self) -> None:
        """POST /search should say 'Search' not 'Create a new search'."""
        ep = _make_endpoint("POST", "/api/v1/search")
        desc = self.gen._generate_description(ep)
        assert "create" not in desc.lower()
        assert "search" in desc.lower()

    def test_post_graphql_not_create(self) -> None:
        """POST /graphql should not say 'Create a new graphql'."""
        ep = _make_endpoint("POST", "/graphql")
        desc = self.gen._generate_description(ep)
        assert "create a new graphql" not in desc.lower()

    def test_get_health_not_list(self) -> None:
        """GET /health should not say 'List all health'."""
        ep = _make_endpoint("GET", "/health")
        desc = self.gen._generate_description(ep)
        assert "list all health" not in desc.lower()
        assert "health" in desc.lower()

    def test_get_status_not_list(self) -> None:
        """GET /status should not say 'List all status'."""
        ep = _make_endpoint("GET", "/status")
        desc = self.gen._generate_description(ep)
        assert "list all status" not in desc.lower()


class TestDescriptionNestedResources:
    """Nested resource descriptions use the leaf resource."""

    def setup_method(self) -> None:
        self.gen = ToolManifestGenerator()

    def test_nested_collection(self) -> None:
        """GET /users/{id}/orders should mention 'orders'."""
        ep = _make_endpoint("GET", "/api/users/{user_id}/orders")
        desc = self.gen._generate_description(ep)
        assert "order" in desc.lower()

    def test_nested_detail(self) -> None:
        """GET /users/{id}/orders/{oid} should say 'Retrieve' not 'List'."""
        ep = _make_endpoint("GET", "/api/users/{user_id}/orders/{order_id}")
        desc = self.gen._generate_description(ep)
        assert "retrieve" in desc.lower()
        assert "list" not in desc.lower()


class TestDescriptionResponseFields:
    """Response field hints are included when schema is present."""

    def setup_method(self) -> None:
        self.gen = ToolManifestGenerator()

    def test_returns_clause_included(self) -> None:
        ep = _make_endpoint(
            "GET", "/api/products",
            response_schema={
                "type": "object",
                "properties": {"id": {}, "name": {}, "price": {}},
            },
        )
        desc = self.gen._generate_description(ep)
        assert "returns:" in desc.lower()
        assert "id" in desc
        assert "price" in desc

    def test_no_returns_without_schema(self) -> None:
        ep = _make_endpoint("GET", "/api/products")
        desc = self.gen._generate_description(ep)
        assert "returns:" not in desc.lower()
