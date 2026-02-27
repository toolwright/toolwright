"""Tests for the auto-tagging engine."""

from __future__ import annotations

from toolwright.core.normalize.tagger import AutoTagger
from toolwright.models.endpoint import Endpoint


def _ep(
    method: str = "GET",
    path: str = "/api/v1/users",
    response_body_schema: dict | None = None,
    request_body_schema: dict | None = None,
    tags: list[str] | None = None,
) -> Endpoint:
    """Helper to build minimal Endpoint for tagger tests."""
    return Endpoint(
        method=method,
        path=path,
        host="api.example.com",
        url=f"https://api.example.com{path}",
        tags=tags or [],
        response_body_schema=response_body_schema,
        request_body_schema=request_body_schema,
    )


class TestAutoTaggerPathSignals:
    """Test tag inference from URL path segments."""

    def test_commerce_paths(self):
        tagger = AutoTagger()
        ep = _ep(path="/api/v1/orders")
        tags = tagger.classify(ep)
        assert "commerce" in tags

    def test_products_path(self):
        tagger = AutoTagger()
        ep = _ep(path="/api/v1/products/{id}")
        tags = tagger.classify(ep)
        assert "commerce" in tags

    def test_cart_path(self):
        tagger = AutoTagger()
        ep = _ep(path="/api/v1/cart/items")
        tags = tagger.classify(ep)
        assert "commerce" in tags

    def test_users_path(self):
        tagger = AutoTagger()
        ep = _ep(path="/api/v1/users")
        tags = tagger.classify(ep)
        assert "users" in tags

    def test_profile_path(self):
        tagger = AutoTagger()
        ep = _ep(path="/api/v1/profile")
        tags = tagger.classify(ep)
        assert "users" in tags

    def test_auth_path(self):
        tagger = AutoTagger()
        ep = _ep(method="POST", path="/api/v1/auth/login")
        tags = tagger.classify(ep)
        assert "auth" in tags

    def test_search_path(self):
        tagger = AutoTagger()
        ep = _ep(method="POST", path="/api/v1/search")
        tags = tagger.classify(ep)
        assert "search" in tags

    def test_admin_path(self):
        tagger = AutoTagger()
        ep = _ep(path="/api/v1/admin/settings")
        tags = tagger.classify(ep)
        assert "admin" in tags


class TestAutoTaggerResponseFieldSignals:
    """Test tag inference from response schema fields."""

    def test_commerce_fields(self):
        tagger = AutoTagger()
        ep = _ep(
            path="/api/v1/items",
            response_body_schema={
                "type": "object",
                "properties": {
                    "price": {"type": "number"},
                    "quantity": {"type": "integer"},
                    "sku": {"type": "string"},
                },
            },
        )
        tags = tagger.classify(ep)
        assert "commerce" in tags

    def test_user_fields(self):
        tagger = AutoTagger()
        ep = _ep(
            path="/api/v1/people",
            response_body_schema={
                "type": "object",
                "properties": {
                    "email": {"type": "string"},
                    "name": {"type": "string"},
                    "phone": {"type": "string"},
                },
            },
        )
        tags = tagger.classify(ep)
        assert "users" in tags

    def test_auth_fields(self):
        tagger = AutoTagger()
        ep = _ep(
            path="/api/v1/connect",
            response_body_schema={
                "type": "object",
                "properties": {
                    "token": {"type": "string"},
                    "expires_at": {"type": "string"},
                },
            },
        )
        tags = tagger.classify(ep)
        assert "auth" in tags

    def test_nested_array_response_fields(self):
        """Fields inside array items should also be checked."""
        tagger = AutoTagger()
        ep = _ep(
            path="/api/v1/data",
            response_body_schema={
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "price": {"type": "number"},
                                "total": {"type": "number"},
                            },
                        },
                    },
                },
            },
        )
        tags = tagger.classify(ep)
        assert "commerce" in tags


class TestAutoTaggerHTTPSemantics:
    """Test tag inference from HTTP method and path patterns."""

    def test_delete_is_destructive(self):
        tagger = AutoTagger()
        ep = _ep(method="DELETE", path="/api/v1/items/{id}")
        tags = tagger.classify(ep)
        assert "destructive" in tags

    def test_get_collection_is_listing(self):
        tagger = AutoTagger()
        ep = _ep(method="GET", path="/api/v1/items")
        tags = tagger.classify(ep)
        assert "listing" in tags

    def test_get_with_id_not_listing(self):
        tagger = AutoTagger()
        ep = _ep(method="GET", path="/api/v1/items/{id}")
        tags = tagger.classify(ep)
        assert "listing" not in tags

    def test_post_search_is_search(self):
        tagger = AutoTagger()
        ep = _ep(method="POST", path="/api/v1/search")
        tags = tagger.classify(ep)
        assert "search" in tags

    def test_post_query_is_search(self):
        tagger = AutoTagger()
        ep = _ep(method="POST", path="/api/v1/graphql/query")
        tags = tagger.classify(ep)
        assert "search" in tags


class TestAutoTaggerDedup:
    """Tags should be deduplicated."""

    def test_no_duplicate_tags(self):
        tagger = AutoTagger()
        ep = _ep(path="/api/v1/users", response_body_schema={
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "name": {"type": "string"},
            },
        })
        tags = tagger.classify(ep)
        assert len(tags) == len(set(tags))


class TestAutoTaggerMerge:
    """Test merging tagger results into existing endpoint tags."""

    def test_merge_preserves_existing(self):
        tagger = AutoTagger()
        ep = _ep(
            path="/api/v1/orders",
            tags=["read", "orders"],
        )
        tags = tagger.classify(ep)
        # Should include existing tags plus new ones
        assert "read" in tags
        assert "orders" in tags
        assert "commerce" in tags

    def test_enrich_endpoints(self):
        """enrich_endpoints should update endpoint tags in place."""
        tagger = AutoTagger()
        ep = _ep(path="/api/v1/products")
        assert "commerce" not in ep.tags
        tagger.enrich_endpoints([ep])
        assert "commerce" in ep.tags
