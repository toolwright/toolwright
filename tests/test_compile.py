"""Tests for artifact compilation."""

import json

import yaml

from toolwright.core.compile import (
    BaselineGenerator,
    ContractCompiler,
    PolicyGenerator,
    ToolManifestGenerator,
    ToolsetGenerator,
)
from toolwright.core.scope import get_builtin_scope
from toolwright.models.endpoint import Endpoint, Parameter, ParameterLocation
from toolwright.models.scope import ScopeType


def make_endpoint(
    method: str = "GET",
    path: str = "/api/users/{id}",
    host: str = "api.example.com",
    is_first_party: bool = True,
    is_auth_related: bool = False,
    has_pii: bool = False,
    is_state_changing: bool = False,
    risk_tier: str = "low",
    parameters: list[Parameter] | None = None,
    response_status_codes: list[int] | None = None,
    request_body_schema: dict | None = None,
    response_body_schema: dict | None = None,
) -> Endpoint:
    """Create a test endpoint."""
    return Endpoint(
        method=method,
        path=path,
        host=host,
        is_first_party=is_first_party,
        is_auth_related=is_auth_related,
        has_pii=has_pii,
        is_state_changing=is_state_changing,
        risk_tier=risk_tier,
        parameters=parameters or [],
        response_status_codes=response_status_codes or [200],
        request_body_schema=request_body_schema,
        response_body_schema=response_body_schema,
    )


class TestContractCompiler:
    """Tests for ContractCompiler."""

    def test_compile_basic_spec(self):
        """Test compiling a basic OpenAPI spec."""
        endpoints = [
            make_endpoint(method="GET", path="/api/users"),
            make_endpoint(method="GET", path="/api/users/{id}"),
            make_endpoint(method="POST", path="/api/users"),
        ]

        compiler = ContractCompiler(
            title="Test API",
            version="1.0.0",
            description="Test API description",
        )
        spec = compiler.compile(endpoints)

        assert spec["openapi"] == "3.1.0"
        assert spec["info"]["title"] == "Test API"
        assert spec["info"]["version"] == "1.0.0"
        assert spec["info"]["description"] == "Test API description"

    def test_compile_paths(self):
        """Test that paths are correctly compiled."""
        endpoints = [
            make_endpoint(method="GET", path="/api/users"),
            make_endpoint(method="POST", path="/api/users"),
            make_endpoint(method="GET", path="/api/users/{id}"),
        ]

        compiler = ContractCompiler()
        spec = compiler.compile(endpoints)

        assert "/api/users" in spec["paths"]
        assert "/api/users/{id}" in spec["paths"]
        assert "get" in spec["paths"]["/api/users"]
        assert "post" in spec["paths"]["/api/users"]

    def test_compile_is_deterministic_for_endpoint_order(self):
        """Spec paths/methods are stable regardless of endpoint input order."""
        endpoints = [
            make_endpoint(method="POST", path="/api/users"),
            make_endpoint(method="GET", path="/api/users/{id}"),
            make_endpoint(method="GET", path="/api/users"),
        ]

        compiler = ContractCompiler()
        spec_a = compiler.compile(endpoints)
        spec_b = compiler.compile(list(reversed(endpoints)))

        assert spec_a["paths"] == spec_b["paths"]

    def test_compile_servers(self):
        """Test that servers are extracted from hosts."""
        endpoints = [
            make_endpoint(host="api.example.com"),
            make_endpoint(host="api2.example.com"),
        ]

        compiler = ContractCompiler()
        spec = compiler.compile(endpoints)

        assert len(spec["servers"]) == 2
        urls = [s["url"] for s in spec["servers"]]
        assert "https://api.example.com" in urls
        assert "https://api2.example.com" in urls

    def test_compile_parameters(self):
        """Test that parameters are compiled correctly."""
        endpoints = [
            make_endpoint(
                method="GET",
                path="/api/users/{id}",
                parameters=[
                    Parameter(
                        name="id",
                        location=ParameterLocation.PATH,
                        param_type="string",
                        required=True,
                        description="User ID",
                    ),
                    Parameter(
                        name="include",
                        location=ParameterLocation.QUERY,
                        param_type="string",
                        required=False,
                    ),
                ],
            ),
        ]

        compiler = ContractCompiler()
        spec = compiler.compile(endpoints)

        params = spec["paths"]["/api/users/{id}"]["get"]["parameters"]
        assert len(params) == 2

        path_param = next(p for p in params if p["name"] == "id")
        assert path_param["in"] == "path"
        assert path_param["required"] is True
        assert path_param["description"] == "User ID"

    def test_compile_toolwright_metadata(self):
        """Test that Toolwright metadata is included."""
        endpoints = [
            make_endpoint(risk_tier="high", is_state_changing=True),
        ]

        compiler = ContractCompiler()
        spec = compiler.compile(endpoints, capture_id="cap_123")

        # Info metadata
        assert "x-toolwright" in spec["info"]
        assert spec["info"]["x-toolwright"]["capture_id"] == "cap_123"
        assert "generated_at" in spec["info"]["x-toolwright"]
        assert spec["info"]["x-toolwright"]["schema_version"] == "1.0"
        assert spec["x-toolwright"]["schema_version"] == "1.0"

        # Operation metadata
        operation = spec["paths"]["/api/users/{id}"]["get"]
        assert "x-toolwright" in operation
        assert operation["x-toolwright"]["risk_tier"] == "high"
        assert operation["x-toolwright"]["state_changing"] is True

    def test_compile_with_scope(self):
        """Test compiling with scope metadata."""
        endpoints = [make_endpoint()]
        scope = get_builtin_scope(ScopeType.FIRST_PARTY_ONLY, ["api.example.com"])

        compiler = ContractCompiler()
        spec = compiler.compile(endpoints, scope=scope)

        assert spec["info"]["x-toolwright"]["scope"] == "first_party_only"

    def test_to_yaml(self):
        """Test YAML serialization."""
        endpoints = [make_endpoint()]

        compiler = ContractCompiler(title="Test")
        spec = compiler.compile(endpoints)
        yaml_str = compiler.to_yaml(spec)

        parsed = yaml.safe_load(yaml_str)
        assert parsed["info"]["title"] == "Test"

    def test_to_json(self):
        """Test JSON serialization."""
        endpoints = [make_endpoint()]

        compiler = ContractCompiler(title="Test")
        spec = compiler.compile(endpoints)
        json_str = compiler.to_json(spec)

        parsed = json.loads(json_str)
        assert parsed["info"]["title"] == "Test"


class TestToolManifestGenerator:
    """Tests for ToolManifestGenerator."""

    def test_generate_basic_manifest(self):
        """Test generating a basic tool manifest."""
        endpoints = [
            make_endpoint(method="GET", path="/api/users"),
            make_endpoint(method="GET", path="/api/users/{id}"),
        ]

        generator = ToolManifestGenerator(name="Test Tools")
        manifest = generator.generate(endpoints)

        assert manifest["version"] == "1.0.0"
        assert manifest["schema_version"] == "1.0"
        assert manifest["name"] == "Test Tools"
        assert len(manifest["actions"]) == 2
        assert "api.example.com" in manifest["allowed_hosts"]

    def test_generate_action_names(self):
        """Test that action names are generated correctly."""
        endpoints = [
            make_endpoint(method="GET", path="/api/users"),
            make_endpoint(method="GET", path="/api/users/{id}"),
            make_endpoint(method="POST", path="/api/users"),
            make_endpoint(method="DELETE", path="/api/users/{id}"),
        ]

        generator = ToolManifestGenerator()
        manifest = generator.generate(endpoints)

        names = [a["name"] for a in manifest["actions"]]
        assert "get_users" in names
        assert "get_user" in names
        assert "create_user" in names
        assert "delete_user" in names

    def test_generate_input_schema(self):
        """Test that input schemas are generated."""
        endpoints = [
            make_endpoint(
                parameters=[
                    Parameter(
                        name="id",
                        location=ParameterLocation.PATH,
                        param_type="string",
                        required=True,
                    ),
                ],
            ),
        ]

        generator = ToolManifestGenerator()
        manifest = generator.generate(endpoints)

        action = manifest["actions"][0]
        assert "input_schema" in action
        assert action["input_schema"]["type"] == "object"
        assert "id" in action["input_schema"]["properties"]
        assert "id" in action["input_schema"]["required"]

    def test_generate_confirmation_by_risk(self):
        """Test that confirmation is set by risk tier."""
        endpoints = [
            make_endpoint(risk_tier="safe"),
            make_endpoint(risk_tier="low"),
            make_endpoint(risk_tier="high", method="DELETE"),
            make_endpoint(risk_tier="critical", method="POST", path="/api/login"),
        ]

        generator = ToolManifestGenerator()
        manifest = generator.generate(endpoints)

        by_risk = {a["risk_tier"]: a["confirmation_required"] for a in manifest["actions"]}
        assert by_risk["safe"] == "never"
        assert by_risk["low"] == "never"
        assert by_risk["high"] == "always"
        assert by_risk["critical"] == "always"

    def test_generate_unique_names(self):
        """Test that duplicate names are resolved."""
        endpoints = [
            make_endpoint(method="GET", path="/api/users", host="api1.example.com"),
            make_endpoint(method="GET", path="/api/users", host="api2.example.com"),
        ]

        generator = ToolManifestGenerator()
        manifest = generator.generate(endpoints)

        names = [a["name"] for a in manifest["actions"]]
        assert len(names) == len(set(names))  # All unique

    def test_generate_is_deterministic_for_endpoint_order(self):
        """Manifest action order is stable regardless of endpoint input order."""
        endpoints = [
            make_endpoint(method="POST", path="/api/users"),
            make_endpoint(method="GET", path="/api/users/{id}"),
            make_endpoint(method="GET", path="/api/users"),
            make_endpoint(method="DELETE", path="/api/users/{id}"),
        ]

        generator = ToolManifestGenerator()
        manifest_a = generator.generate(endpoints)
        manifest_b = generator.generate(list(reversed(endpoints)))

        assert manifest_a["actions"] == manifest_b["actions"]

    def test_generate_with_scope(self):
        """Test generating with scope metadata."""
        endpoints = [make_endpoint()]
        scope = get_builtin_scope(ScopeType.AGENT_SAFE_READONLY, ["api.example.com"])

        generator = ToolManifestGenerator()
        manifest = generator.generate(endpoints, scope=scope, capture_id="cap_123")

        assert manifest["scope"] == "agent_safe_readonly"
        assert manifest["capture_id"] == "cap_123"
        assert manifest["default_confirmation"] == "on_risk"  # Not confirmation_required

    def test_graphql_operations_split_into_operation_scoped_tools(self):
        """POST /graphql should split into one tool per observed operationName."""
        endpoint = make_endpoint(
            method="POST",
            path="/api/graphql",
            is_state_changing=True,
            risk_tier="medium",
            request_body_schema={
                "type": "object",
                "properties": {
                    "operationName": {"type": "string"},
                    "query": {"type": "string"},
                    "variables": {"type": "object"},
                },
            },
        )
        endpoint.request_examples = [
            {
                "operationName": "GetProduct",
                "query": "query GetProduct($id: ID!) { product(id: $id) { id } }",
                "variables": {"id": "1"},
            },
            {
                "operationName": "SearchProducts",
                "query": "query SearchProducts($q: String!) { search(q: $q) { id } }",
                "variables": {"q": "shoe"},
            },
        ]

        manifest = ToolManifestGenerator().generate([endpoint])
        actions = manifest["actions"]

        assert [a["name"] for a in actions] == ["query_get_product", "query_search_products"]
        assert len({a["signature_id"] for a in actions}) == 2

        for action in actions:
            assert action["path"] == "/api/graphql"
            assert action["fixed_body"]["operationName"] in {"GetProduct", "SearchProducts"}
            op_schema = action["input_schema"]["properties"]["operationName"]
            assert op_schema["enum"] == [action["fixed_body"]["operationName"]]
            assert op_schema["default"] == action["fixed_body"]["operationName"]
            assert "operationName" not in action["input_schema"].get("required", [])
            assert "query" in action["fixed_body"]
            assert "query" not in action["input_schema"].get("required", [])

    def test_graphql_operation_type_is_inferred_for_split_actions(self):
        """Operation-scoped GraphQL tools should expose inferred operation type."""
        endpoint = make_endpoint(
            method="POST",
            path="/api/graphql",
            is_state_changing=True,
            risk_tier="medium",
            request_body_schema={
                "type": "object",
                "properties": {
                    "operationName": {"type": "string"},
                    "query": {"type": "string"},
                    "variables": {"type": "object"},
                },
            },
        )
        endpoint.request_examples = [
            {
                "operationName": "GetProduct",
                "query": "query GetProduct($id: ID!) { product(id: $id) { id } }",
                "variables": {"id": "1"},
            },
            {
                "operationName": "UpdateBid",
                "query": "mutation UpdateBid($id: ID!, $amount: Int!) { updateBid(id: $id, amount: $amount) { id } }",
                "variables": {"id": "1", "amount": 100},
            },
        ]

        manifest = ToolManifestGenerator().generate([endpoint])
        by_name = {a["name"]: a for a in manifest["actions"]}

        assert "query_get_product" in by_name
        assert "mutate_update_bid" in by_name
        assert by_name["query_get_product"]["graphql_operation_type"] == "query"
        assert by_name["mutate_update_bid"]["graphql_operation_type"] == "mutation"
        assert "read" in by_name["query_get_product"]["tags"]
        assert "write" not in by_name["query_get_product"]["tags"]
        assert "write" in by_name["mutate_update_bid"]["tags"]

    def test_graphql_without_operation_name_stays_single_tool(self):
        """If no operationName is observed, keep one generic GraphQL tool."""
        endpoint = make_endpoint(
            method="POST",
            path="/api/graphql",
            is_state_changing=True,
            risk_tier="medium",
            request_body_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "variables": {"type": "object"},
                },
            },
        )
        endpoint.request_examples = [
            {"query": "query { viewer { id } }"},
        ]

        manifest = ToolManifestGenerator().generate([endpoint])
        actions = manifest["actions"]

        assert len(actions) == 1
        assert actions[0]["name"] == "query"
        assert "fixed_body" not in actions[0]

    def test_nextjs_build_id_param_is_optional_and_annotated(self):
        """Next.js buildId params should be auto-resolved (not required input)."""
        endpoint = make_endpoint(
            method="GET",
            path="/_next/data/{token}/en/search.json",
            parameters=[
                Parameter(
                    name="token",
                    location=ParameterLocation.PATH,
                    param_type="string",
                    required=True,
                ),
            ],
        )

        manifest = ToolManifestGenerator().generate([endpoint])
        action = manifest["actions"][0]

        required = action["input_schema"].get("required", [])
        assert "token" not in required
        token_schema = action["input_schema"]["properties"]["token"]
        assert token_schema["x-toolwright-resolver"]["name"] == "nextjs_build_id"

    def test_graphql_operation_tools_fix_query_when_unique(self):
        """GraphQL operation tools should fix query text and not require it as input."""
        endpoint = make_endpoint(
            method="POST",
            path="/api/graphql",
            is_state_changing=True,
            risk_tier="medium",
            request_body_schema={
                "type": "object",
                "properties": {
                    "operationName": {"type": "string"},
                    "query": {"type": "string"},
                    "variables": {"type": "object"},
                },
                "required": ["operationName", "query", "variables"],
            },
        )
        endpoint.request_examples = [
            {
                "operationName": "GetProduct",
                "query": "query GetProduct($id: ID!) { product(id: $id) { id } }",
                "variables": {"id": "1"},
            },
            {
                "operationName": "SearchProducts",
                "query": "query SearchProducts($q: String!) { search(q: $q) { id } }",
                "variables": {"q": "shoe"},
            },
        ]

        manifest = ToolManifestGenerator().generate([endpoint])
        by_name = {a["name"]: a for a in manifest["actions"]}

        get_product = by_name["query_get_product"]
        search_products = by_name["query_search_products"]

        assert get_product["fixed_body"]["query"].startswith("query GetProduct")
        assert search_products["fixed_body"]["query"].startswith("query SearchProducts")

        for action in (get_product, search_products):
            required = action["input_schema"].get("required", [])
            assert "operationName" not in required
            assert "query" not in required
            assert action["input_schema"]["properties"]["query"]["enum"] == [action["fixed_body"]["query"]]


class TestPolicyGenerator:
    """Tests for PolicyGenerator."""

    def test_generate_basic_policy(self):
        """Test generating a basic policy."""
        endpoints = [
            make_endpoint(method="GET"),
            make_endpoint(method="POST"),
        ]

        generator = PolicyGenerator(name="Test Policy")
        policy = generator.generate(endpoints)

        assert policy["version"] == "1.0.0"
        assert policy["schema_version"] == "1.0"
        assert policy["name"] == "Test Policy"
        assert policy["default_action"] == "deny"
        assert policy["audit_all"] is True
        assert len(policy["rules"]) > 0

    def test_generate_redaction_defaults(self):
        """Test that redaction defaults are set."""
        endpoints = [make_endpoint()]

        generator = PolicyGenerator()
        policy = generator.generate(endpoints)

        assert "authorization" in policy["redact_headers"]
        assert "cookie" in policy["redact_headers"]
        assert len(policy["redact_patterns"]) > 0

    def test_generate_allow_rule(self):
        """Test that allow rule for first-party GET is generated."""
        endpoints = [
            make_endpoint(host="api.example.com"),
        ]

        generator = PolicyGenerator()
        policy = generator.generate(endpoints)

        allow_rules = [r for r in policy["rules"] if r["type"] == "allow"]
        assert len(allow_rules) > 0

        allow_rule = allow_rules[0]
        assert "api.example.com" in allow_rule["match"]["hosts"]
        assert "GET" in allow_rule["match"]["methods"]

    def test_generate_confirm_rule_for_state_changing(self):
        """Test that confirm rule is generated for state-changing endpoints."""
        endpoints = [
            make_endpoint(method="POST", is_state_changing=True),
        ]

        generator = PolicyGenerator()
        policy = generator.generate(endpoints)

        confirm_rules = [r for r in policy["rules"] if r["type"] == "confirm"]
        assert len(confirm_rules) > 0

    def test_generate_graphql_readonly_allow_without_confirmation(self):
        """GraphQL POST should be allowlisted without confirmation in readonly toolset."""
        endpoints = [
            make_endpoint(
                method="POST",
                path="/api/graphql",
                is_state_changing=True,
                host="stockx.com",
            ),
        ]

        generator = PolicyGenerator()
        policy = generator.generate(endpoints)

        allow_rules = [r for r in policy["rules"] if r["type"] == "allow"]
        gql_rule = next((r for r in allow_rules if r.get("id") == "allow_graphql_readonly"), None)
        assert gql_rule is not None
        assert gql_rule["settings"]["allow_without_confirmation"] is True
        assert gql_rule["match"]["methods"] == ["POST"]
        assert "graphql" in gql_rule["match"]["path_pattern"]
        assert gql_rule["match"]["scopes"] == ["readonly"]

    def test_no_deny_admin_rule_generated(self):
        """Admin endpoints must NOT get a deny_admin rule (F-032)."""
        endpoints = [
            make_endpoint(path="/api/admin/users"),
        ]

        generator = PolicyGenerator()
        policy = generator.generate(endpoints)

        rule_ids = [r["id"] for r in policy["rules"]]
        assert "deny_admin" not in rule_ids

    def test_to_yaml(self):
        """Test YAML serialization."""
        endpoints = [make_endpoint()]

        generator = PolicyGenerator()
        policy = generator.generate(endpoints)
        yaml_str = generator.to_yaml(policy)

        parsed = yaml.safe_load(yaml_str)
        assert parsed["default_action"] == "deny"


class TestToolsetGenerator:
    """Tests for ToolsetGenerator."""

    def test_generate_toolsets_from_manifest(self):
        """Generator should produce first-class named toolsets."""
        endpoints = [
            make_endpoint(method="GET", path="/api/users"),
            make_endpoint(method="POST", path="/api/users", is_state_changing=True, risk_tier="high"),
            make_endpoint(method="DELETE", path="/api/users/{id}", is_state_changing=True, risk_tier="critical"),
        ]

        manifest = ToolManifestGenerator().generate(endpoints, capture_id="cap_123")
        toolsets = ToolsetGenerator().generate(manifest)

        assert toolsets["schema_version"] == "1.0"
        assert toolsets["capture_id"] == "cap_123"
        assert toolsets["default_toolset"] == "readonly"
        assert set(toolsets["toolsets"]) == {"readonly", "write_ops", "high_risk", "operator"}

        readonly = toolsets["toolsets"]["readonly"]["actions"]
        write_ops = toolsets["toolsets"]["write_ops"]["actions"]
        high_risk = toolsets["toolsets"]["high_risk"]["actions"]
        operator = toolsets["toolsets"]["operator"]["actions"]

        assert readonly == ["get_users"]
        assert write_ops == ["create_user", "delete_user"]
        assert high_risk == ["create_user", "delete_user"]
        assert sorted(operator) == ["create_user", "delete_user", "get_users"]

    def test_toolsets_exclude_high_risk_reads_from_readonly(self) -> None:
        """Readonly toolset should avoid high/critical risk tools even if method is GET."""
        endpoints = [
            make_endpoint(method="GET", path="/api/mfa", risk_tier="critical"),
            make_endpoint(method="GET", path="/api/users", risk_tier="low"),
        ]

        manifest = ToolManifestGenerator().generate(endpoints, capture_id="cap_123")
        toolsets = ToolsetGenerator().generate(manifest)

        readonly = set(toolsets["toolsets"]["readonly"]["actions"])
        high_risk = set(toolsets["toolsets"]["high_risk"]["actions"])

        assert "get_users" in readonly
        assert "get_mfa" not in readonly
        assert "get_mfa" in high_risk

    def test_generate_toolsets_is_deterministic(self):
        """Toolsets should be stable regardless of action input order."""
        endpoints = [
            make_endpoint(method="DELETE", path="/api/users/{id}", is_state_changing=True, risk_tier="high"),
            make_endpoint(method="GET", path="/api/users"),
            make_endpoint(method="POST", path="/api/users", is_state_changing=True, risk_tier="medium"),
        ]
        manifest_a = ToolManifestGenerator().generate(endpoints)
        manifest_b = ToolManifestGenerator().generate(list(reversed(endpoints)))

        toolsets_a = ToolsetGenerator().generate(manifest_a)
        toolsets_b = ToolsetGenerator().generate(manifest_b)
        assert toolsets_a["toolsets"] == toolsets_b["toolsets"]

    def test_toolsets_classify_graphql_query_as_readonly(self):
        """GraphQL query operations should be eligible for readonly toolsets."""
        endpoint = make_endpoint(
            method="POST",
            path="/api/graphql",
            is_state_changing=True,
            risk_tier="medium",
            request_body_schema={
                "type": "object",
                "properties": {
                    "operationName": {"type": "string"},
                    "query": {"type": "string"},
                    "variables": {"type": "object"},
                },
            },
        )
        endpoint.request_examples = [
            {
                "operationName": "GetProduct",
                "query": "query GetProduct($id: ID!) { product(id: $id) { id } }",
                "variables": {"id": "1"},
            },
            {
                "operationName": "UpdateBid",
                "query": "mutation UpdateBid($id: ID!, $amount: Int!) { updateBid(id: $id, amount: $amount) { id } }",
                "variables": {"id": "1", "amount": 100},
            },
        ]

        manifest = ToolManifestGenerator().generate([endpoint], capture_id="cap_123")
        toolsets = ToolsetGenerator().generate(manifest)

        readonly = set(toolsets["toolsets"]["readonly"]["actions"])
        write_ops = set(toolsets["toolsets"]["write_ops"]["actions"])

        assert "query_get_product" in readonly
        assert "query_get_product" not in write_ops
        assert "mutate_update_bid" in write_ops

    def test_toolsets_classify_persisted_graphql_query_name_as_readonly(self):
        """When query text is missing, operationName heuristics should still classify obvious reads."""
        endpoint = make_endpoint(
            method="POST",
            path="/api/graphql",
            is_state_changing=True,
            risk_tier="medium",
            request_body_schema={
                "type": "object",
                "properties": {
                    "operationName": {"type": "string"},
                    "variables": {"type": "object"},
                    "extensions": {"type": "object"},
                },
            },
        )
        endpoint.request_examples = [
            {
                "operationName": "RecentlyViewedProducts",
                "variables": {"productId": "abc"},
                "extensions": {"persistedQuery": {"version": 1, "sha256Hash": "deadbeef"}},
            },
        ]

        manifest = ToolManifestGenerator().generate([endpoint], capture_id="cap_123")
        action = manifest["actions"][0]
        toolsets = ToolsetGenerator().generate(manifest)

        readonly = set(toolsets["toolsets"]["readonly"]["actions"])
        write_ops = set(toolsets["toolsets"]["write_ops"]["actions"])

        assert action["name"] == "query_recently_viewed_products"
        assert action["graphql_operation_type"] == "query"
        assert "read" in action["tags"]
        assert action["name"] in readonly
        assert action["name"] not in write_ops


class TestBaselineGenerator:
    """Tests for BaselineGenerator."""

    def test_generate_basic_baseline(self):
        """Test generating a basic baseline."""
        endpoints = [
            make_endpoint(method="GET", path="/api/users"),
            make_endpoint(method="POST", path="/api/users"),
        ]

        generator = BaselineGenerator()
        baseline = generator.generate(endpoints, capture_id="cap_123")

        assert baseline["version"] == "1.0.0"
        assert baseline["schema_version"] == "1.0"
        assert baseline["capture_id"] == "cap_123"
        assert baseline["endpoint_count"] == 2
        assert len(baseline["endpoints"]) == 2

    def test_generate_endpoint_snapshot(self):
        """Test that endpoint snapshots include all fields."""
        endpoints = [
            make_endpoint(
                method="GET",
                path="/api/users/{id}",
                parameters=[
                    Parameter(
                        name="id",
                        location=ParameterLocation.PATH,
                        param_type="string",
                        required=True,
                    ),
                ],
                response_status_codes=[200, 404],
            ),
        ]

        generator = BaselineGenerator()
        baseline = generator.generate(endpoints)

        snapshot = baseline["endpoints"][0]
        assert snapshot["method"] == "GET"
        assert snapshot["path"] == "/api/users/{id}"
        assert snapshot["stable_id"] is not None
        assert snapshot["signature_id"] is not None
        assert len(snapshot["parameters"]) == 1
        assert snapshot["response_status_codes"] == [200, 404]

    def test_generate_summary(self):
        """Test that summary statistics are generated."""
        endpoints = [
            make_endpoint(method="GET", risk_tier="low"),
            make_endpoint(method="POST", risk_tier="high", is_state_changing=True),
            make_endpoint(method="GET", risk_tier="low", has_pii=True),
        ]

        generator = BaselineGenerator()
        baseline = generator.generate(endpoints)

        summary = baseline["summary"]
        assert summary["host_count"] == 1
        assert summary["methods"]["GET"] == 2
        assert summary["methods"]["POST"] == 1
        assert summary["risk_tiers"]["low"] == 2
        assert summary["risk_tiers"]["high"] == 1
        assert summary["state_changing_count"] == 1
        assert summary["pii_count"] == 1

    def test_generate_with_scope(self):
        """Test generating with scope metadata."""
        endpoints = [make_endpoint()]
        scope = get_builtin_scope(ScopeType.FIRST_PARTY_ONLY, ["api.example.com"])

        generator = BaselineGenerator()
        baseline = generator.generate(endpoints, scope=scope)

        assert baseline["scope"] == "first_party_only"

    def test_to_json(self):
        """Test JSON serialization."""
        endpoints = [make_endpoint()]

        generator = BaselineGenerator()
        baseline = generator.generate(endpoints)
        json_str = generator.to_json(baseline)

        parsed = json.loads(json_str)
        assert parsed["endpoint_count"] == 1
