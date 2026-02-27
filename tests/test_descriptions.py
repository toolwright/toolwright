"""Tests for improved tool descriptions in tools.py and contract.py."""

from toolwright.core.compile.contract import ContractCompiler
from toolwright.core.compile.tools import ToolManifestGenerator
from toolwright.models.endpoint import Endpoint, Parameter, ParameterLocation


def make_endpoint(
    method: str = "GET",
    path: str = "/api/users/{id}",
    host: str = "api.example.com",
    parameters: list[Parameter] | None = None,
    response_body_schema: dict | None = None,
    risk_tier: str = "low",
    is_auth_related: bool = False,
    is_state_changing: bool = False,
) -> Endpoint:
    return Endpoint(
        method=method,
        path=path,
        host=host,
        parameters=parameters or [],
        response_body_schema=response_body_schema,
        risk_tier=risk_tier,
        is_auth_related=is_auth_related,
        is_state_changing=is_state_changing,
    )


class TestToolDescriptions:
    """Tests for ToolManifestGenerator._generate_description."""

    def test_get_single_resource_mentions_parameter(self):
        """GET /users/{id} should mention the parameter."""
        ep = make_endpoint(
            method="GET",
            path="/api/users/{id}",
            parameters=[
                Parameter(name="id", location=ParameterLocation.PATH, required=True),
            ],
        )
        gen = ToolManifestGenerator()
        desc = gen._generate_description(ep)
        assert "{id}" in desc or "by id" in desc.lower()

    def test_get_collection_says_list(self):
        """GET /users should say 'List' not 'Retrieve'."""
        ep = make_endpoint(method="GET", path="/api/users")
        gen = ToolManifestGenerator()
        desc = gen._generate_description(ep)
        assert desc.lower().startswith("list")

    def test_description_includes_response_fields(self):
        """Description should mention top response fields when schema is present."""
        ep = make_endpoint(
            method="GET",
            path="/api/users/{id}",
            parameters=[
                Parameter(name="id", location=ParameterLocation.PATH, required=True),
            ],
            response_body_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                    "role": {"type": "string"},
                },
            },
        )
        gen = ToolManifestGenerator()
        desc = gen._generate_description(ep)
        # Should mention at least some response fields
        assert "name" in desc.lower() or "email" in desc.lower()

    def test_post_description(self):
        """POST should say 'Create'."""
        ep = make_endpoint(method="POST", path="/api/users")
        gen = ToolManifestGenerator()
        desc = gen._generate_description(ep)
        assert "create" in desc.lower()

    def test_delete_description(self):
        """DELETE should say 'Delete'."""
        ep = make_endpoint(method="DELETE", path="/api/users/{id}")
        gen = ToolManifestGenerator()
        desc = gen._generate_description(ep)
        assert "delete" in desc.lower()

    def test_singular_resource_not_plural_glitch(self):
        """'Create a new orders' should be fixed to proper grammar."""
        ep = make_endpoint(method="POST", path="/api/orders")
        gen = ToolManifestGenerator()
        desc = gen._generate_description(ep)
        # Should not say "Create a new orders"
        assert "a new orders" not in desc.lower()

    def test_description_with_risk_warning(self):
        """High risk endpoints should include risk warning."""
        ep = make_endpoint(risk_tier="high", method="DELETE", path="/api/users/{id}")
        gen = ToolManifestGenerator()
        desc = gen._generate_description(ep)
        assert "risk" in desc.lower() or "high" in desc.lower()


class TestContractSummary:
    """Tests for ContractCompiler._generate_summary."""

    def test_get_collection_says_list(self):
        """GET collection should say 'List'."""
        ep = make_endpoint(method="GET", path="/api/products")
        compiler = ContractCompiler()
        summary = compiler._generate_summary(ep)
        assert summary.startswith("List")

    def test_get_single_resource(self):
        """GET with path param should say 'Get'."""
        ep = make_endpoint(method="GET", path="/api/products/{id}")
        compiler = ContractCompiler()
        summary = compiler._generate_summary(ep)
        assert summary.startswith("Get")

    def test_post_says_create(self):
        """POST should say 'Create'."""
        ep = make_endpoint(method="POST", path="/api/products")
        compiler = ContractCompiler()
        summary = compiler._generate_summary(ep)
        assert summary.startswith("Create")

    def test_summary_includes_response_fields(self):
        """Summary should mention top response fields when schema is present."""
        ep = make_endpoint(
            method="GET",
            path="/api/users/{id}",
            response_body_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                    "role": {"type": "string"},
                },
            },
        )
        compiler = ContractCompiler()
        summary = compiler._generate_summary(ep)
        assert "name" in summary.lower() or "email" in summary.lower()
