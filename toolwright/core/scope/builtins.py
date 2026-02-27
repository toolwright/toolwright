"""Built-in scope definitions."""

from __future__ import annotations

from toolwright.models.scope import (
    FilterOperator,
    Scope,
    ScopeFilter,
    ScopeRule,
    ScopeType,
)


def get_builtin_scope(scope_type: ScopeType, first_party_hosts: list[str]) -> Scope:
    """Get a built-in scope by type.

    Args:
        scope_type: The type of built-in scope
        first_party_hosts: List of first-party host patterns

    Returns:
        Configured Scope object

    Raises:
        ValueError: If scope type is CUSTOM or unknown
    """
    builders = {
        ScopeType.FIRST_PARTY_ONLY: _build_first_party_only,
        ScopeType.AUTH_SURFACE: _build_auth_surface,
        ScopeType.STATE_CHANGING: _build_state_changing,
        ScopeType.PII_SURFACE: _build_pii_surface,
        ScopeType.AGENT_SAFE_READONLY: _build_agent_safe_readonly,
    }

    if scope_type == ScopeType.CUSTOM:
        raise ValueError("Cannot get built-in scope for CUSTOM type")

    builder = builders.get(scope_type)
    if not builder:
        raise ValueError(f"Unknown built-in scope type: {scope_type}")

    return builder(first_party_hosts)


def _build_first_party_only(first_party_hosts: list[str]) -> Scope:
    """Build the first_party_only scope.

    Includes only requests to configured first-party domains.
    All third-party (analytics, CDN, ads) are excluded.
    """
    return Scope(
        name="first_party_only",
        type=ScopeType.FIRST_PARTY_ONLY,
        description="Only first-party API requests",
        first_party_hosts=first_party_hosts,
        rules=[
            ScopeRule(
                name="first_party_check",
                description="Include only first-party hosts",
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
        default_risk_tier="low",
        confirmation_required=False,
    )


def _build_auth_surface(first_party_hosts: list[str]) -> Scope:
    """Build the auth_surface scope.

    Endpoints involved in authentication flows:
    - Path contains auth-related keywords
    - Request uses auth headers
    - Response sets session cookies
    """
    auth_path_pattern = (
        ".*/(login|logout|signin|signout|auth|oauth|token|refresh|"
        "session|register|signup|password|reset|verify|confirm|activate|"
        "2fa|mfa|otp|sso|saml|oidc|jwt|bearer).*"
    )

    return Scope(
        name="auth_surface",
        type=ScopeType.AUTH_SURFACE,
        description="Authentication and authorization endpoints",
        first_party_hosts=first_party_hosts,
        rules=[
            # Include auth-related paths
            ScopeRule(
                name="auth_paths",
                description="Include endpoints with auth-related paths",
                include=True,
                filters=[
                    ScopeFilter(
                        field="path",
                        operator=FilterOperator.MATCHES,
                        value=auth_path_pattern,
                    ),
                ],
            ),
            # Include endpoints marked as auth-related
            ScopeRule(
                name="auth_flag",
                description="Include endpoints flagged as auth-related",
                include=True,
                filters=[
                    ScopeFilter(
                        field="is_auth_related",
                        operator=FilterOperator.EQUALS,
                        value=True,
                    ),
                ],
            ),
        ],
        default_risk_tier="critical",
        confirmation_required=True,
    )


def _build_state_changing(first_party_hosts: list[str]) -> Scope:
    """Build the state_changing scope.

    Non-GET methods that modify server state.
    Excludes safe POSTs like search and graphql queries.
    """
    return Scope(
        name="state_changing",
        type=ScopeType.STATE_CHANGING,
        description="State-changing operations (POST/PUT/PATCH/DELETE)",
        first_party_hosts=first_party_hosts,
        rules=[
            # Exclude safe POSTs (search, query, graphql)
            ScopeRule(
                name="exclude_safe_posts",
                description="Exclude read-only POST endpoints",
                include=False,
                filters=[
                    ScopeFilter(
                        field="method",
                        operator=FilterOperator.EQUALS,
                        value="POST",
                    ),
                    ScopeFilter(
                        field="path",
                        operator=FilterOperator.MATCHES,
                        value=".*/search.*|.*/query.*|.*/graphql.*",
                    ),
                ],
            ),
            # Include non-GET methods
            ScopeRule(
                name="non_get_methods",
                description="Include state-changing methods",
                include=True,
                filters=[
                    ScopeFilter(
                        field="method",
                        operator=FilterOperator.IN,
                        value=["POST", "PUT", "PATCH", "DELETE"],
                    ),
                ],
            ),
        ],
        default_risk_tier="high",
        confirmation_required=True,
        rate_limit_per_minute=10,
    )


def _build_pii_surface(first_party_hosts: list[str]) -> Scope:
    """Build the pii_surface scope.

    Endpoints handling personally identifiable information.
    """
    user_path_pattern = ".*/(user|profile|account|customer|member|person|contact|patient).*"

    return Scope(
        name="pii_surface",
        type=ScopeType.PII_SURFACE,
        description="Endpoints handling PII data",
        first_party_hosts=first_party_hosts,
        rules=[
            # Include user/profile endpoints
            ScopeRule(
                name="user_endpoints",
                description="Include user/profile related endpoints",
                include=True,
                filters=[
                    ScopeFilter(
                        field="path",
                        operator=FilterOperator.MATCHES,
                        value=user_path_pattern,
                    ),
                ],
            ),
            # Include endpoints with PII flag
            ScopeRule(
                name="has_pii",
                description="Include endpoints with detected PII",
                include=True,
                filters=[
                    ScopeFilter(
                        field="has_pii",
                        operator=FilterOperator.EQUALS,
                        value=True,
                    ),
                ],
            ),
        ],
        default_risk_tier="high",
        confirmation_required=True,
    )


def _build_agent_safe_readonly(first_party_hosts: list[str]) -> Scope:
    """Build the agent_safe_readonly scope.

    Strict read-only subset safe for autonomous agent use:
    - Only GET methods
    - First-party hosts only
    - Excludes auth endpoints
    - Excludes PII endpoints
    - Excludes admin paths
    """
    return Scope(
        name="agent_safe_readonly",
        type=ScopeType.AGENT_SAFE_READONLY,
        description="Safe read-only endpoints for agents",
        first_party_hosts=first_party_hosts,
        rules=[
            # Exclude non-first-party
            ScopeRule(
                name="first_party_only",
                description="Exclude third-party endpoints",
                include=False,
                filters=[
                    ScopeFilter(
                        field="is_first_party",
                        operator=FilterOperator.EQUALS,
                        value=False,
                    ),
                ],
            ),
            # Exclude non-GET methods
            ScopeRule(
                name="get_only",
                description="Exclude non-GET methods",
                include=False,
                filters=[
                    ScopeFilter(
                        field="method",
                        operator=FilterOperator.NOT_EQUALS,
                        value="GET",
                    ),
                ],
            ),
            # Exclude auth endpoints
            ScopeRule(
                name="no_auth",
                description="Exclude auth endpoints",
                include=False,
                filters=[
                    ScopeFilter(
                        field="is_auth_related",
                        operator=FilterOperator.EQUALS,
                        value=True,
                    ),
                ],
            ),
            # Exclude PII endpoints
            ScopeRule(
                name="no_pii",
                description="Exclude PII endpoints",
                include=False,
                filters=[
                    ScopeFilter(
                        field="has_pii",
                        operator=FilterOperator.EQUALS,
                        value=True,
                    ),
                ],
            ),
            # Exclude admin paths
            ScopeRule(
                name="no_admin",
                description="Exclude admin endpoints",
                include=False,
                filters=[
                    ScopeFilter(
                        field="path",
                        operator=FilterOperator.MATCHES,
                        value=".*/admin.*",
                    ),
                ],
            ),
            # Include everything else (that's GET and first-party)
            ScopeRule(
                name="include_safe_get",
                description="Include remaining safe GET endpoints",
                include=True,
                filters=[
                    ScopeFilter(
                        field="method",
                        operator=FilterOperator.EQUALS,
                        value="GET",
                    ),
                ],
            ),
        ],
        default_risk_tier="safe",
        confirmation_required=False,
        rate_limit_per_minute=60,
    )
