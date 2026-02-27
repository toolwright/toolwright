"""Tests for tags on Endpoint model and tag-based scope filtering."""

from toolwright.core.normalize.aggregator import EndpointAggregator
from toolwright.models.capture import CaptureSession, CaptureSource, HttpExchange, HTTPMethod
from toolwright.models.endpoint import Endpoint
from toolwright.models.scope import FilterOperator, Scope, ScopeFilter, ScopeRule


def make_endpoint(
    method: str = "GET",
    path: str = "/api/users",
    host: str = "api.example.com",
    tags: list[str] | None = None,
    is_first_party: bool = True,
    is_auth_related: bool = False,
    has_pii: bool = False,
) -> Endpoint:
    return Endpoint(
        method=method,
        path=path,
        host=host,
        tags=tags or [],
        is_first_party=is_first_party,
        is_auth_related=is_auth_related,
        has_pii=has_pii,
    )


class TestEndpointTagsField:
    """Tests for tags field on Endpoint model."""

    def test_tags_default_empty(self):
        """Tags should default to empty list."""
        ep = Endpoint(method="GET", path="/api/users", host="api.example.com")
        assert ep.tags == []

    def test_tags_set_explicitly(self):
        """Tags should be settable."""
        ep = make_endpoint(tags=["users", "read"])
        assert ep.tags == ["users", "read"]

    def test_tags_serialization(self):
        """Tags should survive model serialization round-trip."""
        ep = make_endpoint(tags=["commerce", "write"])
        data = ep.model_dump()
        assert data["tags"] == ["commerce", "write"]

        restored = Endpoint.model_validate(data)
        assert restored.tags == ["commerce", "write"]


class TestAggregatorPopulatesTags:
    """Tests that the aggregator populates tags during endpoint creation."""

    def _make_session(self, exchanges: list[HttpExchange]) -> CaptureSession:
        return CaptureSession(
            name="test",
            source=CaptureSource.HAR,
            allowed_hosts=["api.example.com"],
            exchanges=exchanges,
        )

    def _make_exchange(
        self, method: str = "GET", path: str = "/api/users"
    ) -> HttpExchange:
        return HttpExchange(
            url=f"https://api.example.com{path}",
            method=HTTPMethod(method),
            host="api.example.com",
            path=path,
            request_headers={},
            response_status=200,
            response_headers={},
        )

    def test_tags_populated_from_path_segment(self):
        """Tags should include the first meaningful path segment."""
        session = self._make_session([self._make_exchange(path="/api/users")])
        agg = EndpointAggregator(first_party_hosts=["api.example.com"])
        endpoints = agg.aggregate(session)

        assert len(endpoints) == 1
        assert "users" in endpoints[0].tags

    def test_tags_include_read_write(self):
        """Tags should include 'read' for GET, 'write' for POST."""
        session = self._make_session([
            self._make_exchange(method="GET", path="/api/products"),
            self._make_exchange(method="POST", path="/api/orders"),
        ])
        agg = EndpointAggregator(first_party_hosts=["api.example.com"])
        endpoints = agg.aggregate(session)

        get_ep = next(ep for ep in endpoints if ep.method == "GET")
        post_ep = next(ep for ep in endpoints if ep.method == "POST")

        assert "read" in get_ep.tags
        assert "write" in post_ep.tags

    def test_tags_include_auth(self):
        """Auth-related endpoints should have 'auth' tag."""
        session = self._make_session([self._make_exchange(path="/api/login")])
        agg = EndpointAggregator(first_party_hosts=["api.example.com"])
        endpoints = agg.aggregate(session)

        assert "auth" in endpoints[0].tags

    def test_tags_include_pii(self):
        """Endpoints with PII should have 'pii' tag."""
        exchange = self._make_exchange(path="/api/users")
        exchange.response_body_json = {"email": "a@b.com", "name": "Alice"}
        session = self._make_session([exchange])
        agg = EndpointAggregator(first_party_hosts=["api.example.com"])
        endpoints = agg.aggregate(session)

        assert "pii" in endpoints[0].tags


class TestTagBasedScopeFilter:
    """Tests for tag-based filtering in scope engine."""

    def test_contains_filter_matches_tag_in_list(self):
        """CONTAINS on tags should match if tag is in the list."""
        f = ScopeFilter(field="tags", operator=FilterOperator.CONTAINS, value="commerce")
        ep = make_endpoint(tags=["commerce", "read"])
        assert f.evaluate(ep) is True

    def test_contains_filter_no_match(self):
        """CONTAINS on tags should not match if tag is absent."""
        f = ScopeFilter(field="tags", operator=FilterOperator.CONTAINS, value="auth")
        ep = make_endpoint(tags=["commerce", "read"])
        assert f.evaluate(ep) is False

    def test_not_contains_filter(self):
        """NOT_CONTAINS on tags should exclude endpoints with the tag."""
        f = ScopeFilter(field="tags", operator=FilterOperator.NOT_CONTAINS, value="auth")
        ep = make_endpoint(tags=["commerce", "read"])
        assert f.evaluate(ep) is True

        ep_auth = make_endpoint(tags=["auth", "write"])
        assert f.evaluate(ep_auth) is False

    def test_tag_scope_include_rule(self):
        """A scope rule using tag CONTAINS should include matching endpoints."""
        scope = Scope(
            name="commerce_tools",
            rules=[
                ScopeRule(
                    name="commerce_only",
                    include=True,
                    filters=[
                        ScopeFilter(
                            field="tags",
                            operator=FilterOperator.CONTAINS,
                            value="commerce",
                        ),
                    ],
                ),
            ],
        )
        assert scope.matches(make_endpoint(tags=["commerce", "read"])) is True
        assert scope.matches(make_endpoint(tags=["users", "read"])) is False

    def test_tag_scope_exclude_rule(self):
        """A scope rule using tag exclusion should filter out matching endpoints."""
        scope = Scope(
            name="no_auth_tools",
            rules=[
                ScopeRule(
                    name="exclude_auth",
                    include=False,
                    filters=[
                        ScopeFilter(
                            field="tags",
                            operator=FilterOperator.CONTAINS,
                            value="auth",
                        ),
                    ],
                ),
                ScopeRule(
                    name="include_all",
                    include=True,
                    filters=[
                        ScopeFilter(
                            field="is_first_party",
                            operator=FilterOperator.EQUALS,
                            value=True,
                        ),
                    ],
                ),
            ],
        )
        assert scope.matches(make_endpoint(tags=["auth", "write"])) is False
        assert scope.matches(make_endpoint(tags=["users", "read"])) is True
