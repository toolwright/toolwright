"""Tests for scope engine."""

import tempfile
from pathlib import Path

from toolwright.core.scope import ScopeEngine, get_builtin_scope, parse_scope_file
from toolwright.models.endpoint import Endpoint
from toolwright.models.scope import FilterOperator, Scope, ScopeFilter, ScopeRule, ScopeType


def make_endpoint(
    method: str = "GET",
    path: str = "/api/users",
    host: str = "api.example.com",
    is_first_party: bool = True,
    is_auth_related: bool = False,
    has_pii: bool = False,
    risk_tier: str = "low",
) -> Endpoint:
    """Create a test endpoint."""
    return Endpoint(
        method=method,
        path=path,
        host=host,
        is_first_party=is_first_party,
        is_auth_related=is_auth_related,
        has_pii=has_pii,
        risk_tier=risk_tier,
    )


class TestScopeFilter:
    """Tests for ScopeFilter evaluation."""

    def test_equals_operator(self):
        """Test equals operator."""
        filter_ = ScopeFilter(field="method", operator=FilterOperator.EQUALS, value="GET")
        endpoint = make_endpoint(method="GET")

        assert filter_.evaluate(endpoint) is True

        endpoint = make_endpoint(method="POST")
        assert filter_.evaluate(endpoint) is False

    def test_not_equals_operator(self):
        """Test not_equals operator."""
        filter_ = ScopeFilter(field="method", operator=FilterOperator.NOT_EQUALS, value="GET")
        endpoint = make_endpoint(method="POST")

        assert filter_.evaluate(endpoint) is True

    def test_contains_operator(self):
        """Test contains operator."""
        filter_ = ScopeFilter(field="path", operator=FilterOperator.CONTAINS, value="/users")
        endpoint = make_endpoint(path="/api/users/123")

        assert filter_.evaluate(endpoint) is True

        endpoint = make_endpoint(path="/api/products")
        assert filter_.evaluate(endpoint) is False

    def test_matches_operator(self):
        """Test regex matches operator."""
        filter_ = ScopeFilter(
            field="path",
            operator=FilterOperator.MATCHES,
            value=".*/(login|auth).*",
        )

        endpoint = make_endpoint(path="/api/login")
        assert filter_.evaluate(endpoint) is True

        endpoint = make_endpoint(path="/api/auth/token")
        assert filter_.evaluate(endpoint) is True

        endpoint = make_endpoint(path="/api/users")
        assert filter_.evaluate(endpoint) is False

    def test_in_operator(self):
        """Test in operator."""
        filter_ = ScopeFilter(
            field="method",
            operator=FilterOperator.IN,
            value=["POST", "PUT", "PATCH"],
        )

        endpoint = make_endpoint(method="POST")
        assert filter_.evaluate(endpoint) is True

        endpoint = make_endpoint(method="GET")
        assert filter_.evaluate(endpoint) is False

    def test_boolean_field(self):
        """Test boolean field matching."""
        filter_ = ScopeFilter(
            field="is_first_party",
            operator=FilterOperator.EQUALS,
            value=True,
        )

        endpoint = make_endpoint(is_first_party=True)
        assert filter_.evaluate(endpoint) is True

        endpoint = make_endpoint(is_first_party=False)
        assert filter_.evaluate(endpoint) is False


class TestScopeRule:
    """Tests for ScopeRule evaluation."""

    def test_single_filter_include(self):
        """Test rule with single filter and include=True."""
        rule = ScopeRule(
            name="get_only",
            include=True,
            filters=[
                ScopeFilter(field="method", operator=FilterOperator.EQUALS, value="GET"),
            ],
        )

        endpoint = make_endpoint(method="GET")
        assert rule.evaluate(endpoint) is True

        endpoint = make_endpoint(method="POST")
        assert rule.evaluate(endpoint) is None  # No match

    def test_single_filter_exclude(self):
        """Test rule with single filter and include=False."""
        rule = ScopeRule(
            name="no_post",
            include=False,
            filters=[
                ScopeFilter(field="method", operator=FilterOperator.EQUALS, value="POST"),
            ],
        )

        endpoint = make_endpoint(method="POST")
        assert rule.evaluate(endpoint) is False  # Exclude

        endpoint = make_endpoint(method="GET")
        assert rule.evaluate(endpoint) is None  # No match

    def test_multiple_filters_and_logic(self):
        """Test that multiple filters use AND logic."""
        rule = ScopeRule(
            name="first_party_get",
            include=True,
            filters=[
                ScopeFilter(field="method", operator=FilterOperator.EQUALS, value="GET"),
                ScopeFilter(field="is_first_party", operator=FilterOperator.EQUALS, value=True),
            ],
        )

        # Both conditions met
        endpoint = make_endpoint(method="GET", is_first_party=True)
        assert rule.evaluate(endpoint) is True

        # Only one condition met
        endpoint = make_endpoint(method="GET", is_first_party=False)
        assert rule.evaluate(endpoint) is None

        endpoint = make_endpoint(method="POST", is_first_party=True)
        assert rule.evaluate(endpoint) is None


class TestScope:
    """Tests for Scope evaluation."""

    def test_first_match_wins(self):
        """Test that first matching rule determines result."""
        scope = Scope(
            name="test_scope",
            rules=[
                # Exclude POST first
                ScopeRule(
                    name="no_post",
                    include=False,
                    filters=[
                        ScopeFilter(field="method", operator=FilterOperator.EQUALS, value="POST"),
                    ],
                ),
                # Include everything else
                ScopeRule(
                    name="include_all",
                    include=True,
                    filters=[
                        ScopeFilter(
                            field="method",
                            operator=FilterOperator.IN,
                            value=["GET", "POST", "PUT"],
                        ),
                    ],
                ),
            ],
        )

        # POST should be excluded (first rule matches)
        endpoint = make_endpoint(method="POST")
        assert scope.matches(endpoint) is False

        # GET should be included (second rule matches)
        endpoint = make_endpoint(method="GET")
        assert scope.matches(endpoint) is True

    def test_no_match_defaults_to_exclude(self):
        """Test that no matching rules defaults to exclude."""
        scope = Scope(
            name="test_scope",
            rules=[
                ScopeRule(
                    name="only_get",
                    include=True,
                    filters=[
                        ScopeFilter(field="method", operator=FilterOperator.EQUALS, value="GET"),
                    ],
                ),
            ],
        )

        # DELETE doesn't match any rule
        endpoint = make_endpoint(method="DELETE")
        assert scope.matches(endpoint) is False


class TestBuiltinScopes:
    """Tests for built-in scopes."""

    def test_first_party_only(self):
        """Test first_party_only scope."""
        scope = get_builtin_scope(ScopeType.FIRST_PARTY_ONLY, ["api.example.com"])

        # First-party included
        endpoint = make_endpoint(is_first_party=True)
        assert scope.matches(endpoint) is True

        # Third-party excluded
        endpoint = make_endpoint(is_first_party=False)
        assert scope.matches(endpoint) is False

    def test_auth_surface(self):
        """Test auth_surface scope."""
        scope = get_builtin_scope(ScopeType.AUTH_SURFACE, ["api.example.com"])

        # Auth path included
        endpoint = make_endpoint(path="/api/login")
        assert scope.matches(endpoint) is True

        endpoint = make_endpoint(path="/api/auth/token")
        assert scope.matches(endpoint) is True

        # Non-auth path with auth flag
        endpoint = make_endpoint(path="/api/users", is_auth_related=True)
        assert scope.matches(endpoint) is True

        # Non-auth path without flag
        endpoint = make_endpoint(path="/api/products", is_auth_related=False)
        assert scope.matches(endpoint) is False

    def test_state_changing(self):
        """Test state_changing scope."""
        scope = get_builtin_scope(ScopeType.STATE_CHANGING, ["api.example.com"])

        # POST included
        endpoint = make_endpoint(method="POST", path="/api/users")
        assert scope.matches(endpoint) is True

        # PUT/PATCH/DELETE included
        endpoint = make_endpoint(method="DELETE", path="/api/users/123")
        assert scope.matches(endpoint) is True

        # GET excluded
        endpoint = make_endpoint(method="GET", path="/api/users")
        assert scope.matches(endpoint) is False

        # Search POST excluded (read-only)
        endpoint = make_endpoint(method="POST", path="/api/search")
        assert scope.matches(endpoint) is False

    def test_pii_surface(self):
        """Test pii_surface scope."""
        scope = get_builtin_scope(ScopeType.PII_SURFACE, ["api.example.com"])

        # User path included
        endpoint = make_endpoint(path="/api/users/123")
        assert scope.matches(endpoint) is True

        endpoint = make_endpoint(path="/api/profile")
        assert scope.matches(endpoint) is True

        # Has PII flag included
        endpoint = make_endpoint(path="/api/orders", has_pii=True)
        assert scope.matches(endpoint) is True

        # Non-PII excluded
        endpoint = make_endpoint(path="/api/products", has_pii=False)
        assert scope.matches(endpoint) is False

    def test_agent_safe_readonly(self):
        """Test agent_safe_readonly scope."""
        scope = get_builtin_scope(ScopeType.AGENT_SAFE_READONLY, ["api.example.com"])

        # Safe GET included
        endpoint = make_endpoint(method="GET", is_first_party=True)
        assert scope.matches(endpoint) is True

        # POST excluded
        endpoint = make_endpoint(method="POST", is_first_party=True)
        assert scope.matches(endpoint) is False

        # Third-party excluded
        endpoint = make_endpoint(method="GET", is_first_party=False)
        assert scope.matches(endpoint) is False

        # Auth excluded
        endpoint = make_endpoint(method="GET", is_first_party=True, is_auth_related=True)
        assert scope.matches(endpoint) is False

        # PII excluded
        endpoint = make_endpoint(method="GET", is_first_party=True, has_pii=True)
        assert scope.matches(endpoint) is False

        # Admin excluded
        endpoint = make_endpoint(method="GET", is_first_party=True, path="/api/admin/users")
        assert scope.matches(endpoint) is False


class TestScopeEngine:
    """Tests for ScopeEngine."""

    def test_load_builtin_scope(self):
        """Test loading built-in scopes."""
        engine = ScopeEngine(first_party_hosts=["api.example.com"])

        scope = engine.load_scope("first_party_only")
        assert scope.name == "first_party_only"
        assert scope.type == ScopeType.FIRST_PARTY_ONLY

    def test_filter_endpoints(self):
        """Test filtering endpoints by scope."""
        engine = ScopeEngine(first_party_hosts=["api.example.com"])
        scope = engine.load_scope("agent_safe_readonly")

        endpoints = [
            make_endpoint(method="GET", is_first_party=True),
            make_endpoint(method="POST", is_first_party=True),
            make_endpoint(method="GET", is_first_party=False),
            make_endpoint(method="GET", is_first_party=True, is_auth_related=True),
        ]

        filtered = engine.filter_endpoints(endpoints, scope)

        assert len(filtered) == 1
        assert filtered[0].method == "GET"
        assert filtered[0].is_first_party is True
        assert filtered[0].is_auth_related is False

    def test_get_available_scopes(self):
        """Test getting available scopes."""
        engine = ScopeEngine()

        scopes = engine.get_available_scopes()

        assert "first_party_only" in scopes
        assert "auth_surface" in scopes
        assert "state_changing" in scopes
        assert "pii_surface" in scopes
        assert "agent_safe_readonly" in scopes


class TestScopeParser:
    """Tests for scope YAML parsing."""

    def test_parse_simple_scope(self):
        """Test parsing a simple scope YAML."""
        yaml_content = """
name: my_custom_scope
description: Test scope

rules:
  - name: include_api
    include: true
    filters:
      - field: path
        operator: contains
        value: /api/

default_risk_tier: medium
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            scope = parse_scope_file(path)

            assert scope.name == "my_custom_scope"
            assert scope.description == "Test scope"
            assert len(scope.rules) == 1
            assert scope.rules[0].name == "include_api"
            assert scope.default_risk_tier == "medium"
        finally:
            path.unlink()

    def test_parse_scope_with_multiple_rules(self):
        """Test parsing scope with multiple rules."""
        yaml_content = """
name: checkout_scope
description: Checkout flow endpoints
first_party_hosts:
  - api.example.com
  - checkout.example.com

rules:
  - name: exclude_analytics
    include: false
    filters:
      - field: path
        operator: matches
        value: ".*/analytics/.*"

  - name: include_checkout
    include: true
    filters:
      - field: path
        operator: contains
        value: /checkout

  - name: include_cart
    include: true
    filters:
      - field: path
        operator: contains
        value: /cart

default_risk_tier: high
confirmation_required: true
rate_limit_per_minute: 30
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            path = Path(f.name)

        try:
            scope = parse_scope_file(path)

            assert scope.name == "checkout_scope"
            assert len(scope.first_party_hosts) == 2
            assert len(scope.rules) == 3
            assert scope.confirmation_required is True
            assert scope.rate_limit_per_minute == 30
        finally:
            path.unlink()
