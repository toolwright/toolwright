"""Tests for ToolpackAuthRequirement model and auth detection visibility."""

from __future__ import annotations

from toolwright.core.toolpack import ToolpackAuthRequirement


class TestToolpackAuthRequirement:
    """Test the ToolpackAuthRequirement Pydantic model."""

    def test_creates_with_required_fields(self) -> None:
        req = ToolpackAuthRequirement(
            host="api.stripe.com",
            scheme="bearer",
            location="header",
            env_var_name="TOOLWRIGHT_AUTH_API_STRIPE_COM",
        )
        assert req.host == "api.stripe.com"
        assert req.scheme == "bearer"
        assert req.location == "header"
        assert req.env_var_name == "TOOLWRIGHT_AUTH_API_STRIPE_COM"

    def test_header_name_optional(self) -> None:
        req = ToolpackAuthRequirement(
            host="api.stripe.com",
            scheme="bearer",
            location="header",
            env_var_name="TOOLWRIGHT_AUTH_API_STRIPE_COM",
            header_name="Authorization",
        )
        assert req.header_name == "Authorization"

    def test_default_header_name_is_none(self) -> None:
        req = ToolpackAuthRequirement(
            host="api.stripe.com",
            scheme="bearer",
            location="header",
            env_var_name="TOOLWRIGHT_AUTH_API_STRIPE_COM",
        )
        assert req.header_name is None

    def test_env_var_name_precomputed_correctly(self) -> None:
        """api.github.com -> TOOLWRIGHT_AUTH_API_GITHUB_COM"""
        from toolwright.cli.commands_auth import _host_to_env_var

        env_var = _host_to_env_var("api.github.com")
        req = ToolpackAuthRequirement(
            host="api.github.com",
            scheme="bearer",
            location="header",
            env_var_name=env_var,
        )
        assert req.env_var_name == "TOOLWRIGHT_AUTH_API_GITHUB_COM"

    def test_serializes_to_dict(self) -> None:
        req = ToolpackAuthRequirement(
            host="api.stripe.com",
            scheme="bearer",
            location="header",
            env_var_name="TOOLWRIGHT_AUTH_API_STRIPE_COM",
            header_name="Authorization",
        )
        d = req.model_dump()
        assert d["host"] == "api.stripe.com"
        assert d["scheme"] == "bearer"
        assert d["location"] == "header"
        assert d["env_var_name"] == "TOOLWRIGHT_AUTH_API_STRIPE_COM"
        assert d["header_name"] == "Authorization"


class TestBuildAuthRequirements:
    """Test building auth requirements from detector output."""

    def test_builds_from_detected_bearer(self) -> None:
        from toolwright.core.toolpack import build_auth_requirements

        hosts = ["api.stripe.com"]
        auth_type = "bearer"
        reqs = build_auth_requirements(hosts=hosts, auth_type=auth_type)
        assert len(reqs) == 1
        assert reqs[0].host == "api.stripe.com"
        assert reqs[0].scheme == "bearer"
        assert reqs[0].location == "header"
        assert reqs[0].header_name == "Authorization"
        assert reqs[0].env_var_name == "TOOLWRIGHT_AUTH_API_STRIPE_COM"

    def test_builds_from_detected_api_key(self) -> None:
        from toolwright.core.toolpack import build_auth_requirements

        reqs = build_auth_requirements(
            hosts=["api.example.com"],
            auth_type="api_key",
        )
        assert len(reqs) == 1
        assert reqs[0].scheme == "api_key"
        assert reqs[0].header_name == "X-API-Key"

    def test_builds_for_multiple_hosts(self) -> None:
        from toolwright.core.toolpack import build_auth_requirements

        reqs = build_auth_requirements(
            hosts=["api.stripe.com", "auth.stripe.com"],
            auth_type="bearer",
        )
        assert len(reqs) == 2
        assert reqs[0].host == "api.stripe.com"
        assert reqs[1].host == "auth.stripe.com"
        assert reqs[0].env_var_name != reqs[1].env_var_name

    def test_builds_none_scheme(self) -> None:
        from toolwright.core.toolpack import build_auth_requirements

        reqs = build_auth_requirements(
            hosts=["api.example.com"],
            auth_type="none",
        )
        assert len(reqs) == 1
        assert reqs[0].scheme == "none"
        assert reqs[0].header_name is None
