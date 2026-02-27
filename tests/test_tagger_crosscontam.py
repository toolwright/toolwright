"""Tests for tagger field cross-contamination fixes."""

from __future__ import annotations

from toolwright.core.normalize.tagger import AutoTagger
from toolwright.models.endpoint import Endpoint


def _make_endpoint(
    path: str, method: str = "GET",
    response_schema: dict | None = None,
    request_schema: dict | None = None,
) -> Endpoint:
    return Endpoint(
        method=method,
        host="api.example.com",
        path=path,
        signature_id="test",
        response_body_schema=response_schema,
        request_body_schema=request_schema,
    )


class TestTaggerFieldCrossContamination:
    """Field-based tags should not cross-contaminate unrelated domains."""

    def setup_method(self) -> None:
        self.tagger = AutoTagger()

    def test_product_with_name_not_tagged_as_users(self) -> None:
        """Product endpoint with 'name' field should NOT get 'users' tag."""
        ep = _make_endpoint(
            "/api/products",
            response_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "price": {"type": "number"},
                },
            },
        )
        tags = self.tagger.classify(ep)
        assert "users" not in tags
        assert "commerce" in tags  # price triggers commerce

    def test_product_detail_with_name_not_tagged_as_users(self) -> None:
        """Product detail with 'name' + 'description' should NOT get 'users' tag."""
        ep = _make_endpoint(
            "/api/products/{id}",
            response_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "stock": {"type": "integer"},
                },
            },
        )
        tags = self.tagger.classify(ep)
        assert "users" not in tags

    def test_user_with_name_and_email_tagged_as_users(self) -> None:
        """User endpoint with 'name' + 'email' SHOULD get 'users' tag."""
        ep = _make_endpoint(
            "/api/people",
            response_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                },
            },
        )
        tags = self.tagger.classify(ep)
        assert "users" in tags

    def test_user_path_still_gets_users_tag(self) -> None:
        """Path-based signal should still work regardless of fields."""
        ep = _make_endpoint(
            "/api/users",
            response_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                },
            },
        )
        tags = self.tagger.classify(ep)
        assert "users" in tags  # from path signal

    def test_email_alone_triggers_users(self) -> None:
        """'email' is a strong user signal even without other fields."""
        ep = _make_endpoint(
            "/api/contacts",
            response_schema={
                "type": "object",
                "properties": {
                    "email": {"type": "string"},
                },
            },
        )
        tags = self.tagger.classify(ep)
        assert "users" in tags

    def test_notification_endpoint_not_tagged_users_via_email(self) -> None:
        """notifications path with 'email' field: path wins for notifications."""
        ep = _make_endpoint(
            "/api/notifications",
            response_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "email": {"type": "string"},
                },
            },
        )
        tags = self.tagger.classify(ep)
        assert "notifications" in tags
