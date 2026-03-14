"""Tests for the Toolwright MCP server."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from toolwright.core.approval import LockfileManager
from toolwright.core.network_safety import RuntimeBlockError
from toolwright.mcp.server import ToolwrightMCPServer


@pytest.fixture
def sample_tools_manifest() -> dict:
    """Create a sample tools manifest."""
    return {
        "version": "1.0.0",
        "schema_version": "1.0",
        "name": "Test Tools",
        "allowed_hosts": ["api.example.com"],
        "actions": [
            {
                "name": "get_users",
                "description": "Get list of users",
                "method": "GET",
                "path": "/api/users",
                "host": "api.example.com",
                "endpoint_id": "ep_123",
                "risk_tier": "low",
                "confirmation_required": "never",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer"},
                    },
                },
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "users": {"type": "array"},
                    },
                },
            },
            {
                "name": "create_user",
                "description": "Create a new user",
                "method": "POST",
                "path": "/api/users",
                "host": "api.example.com",
                "endpoint_id": "ep_456",
                "risk_tier": "high",
                "confirmation_required": "always",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                    },
                },
            },
            {
                "name": "get_user",
                "description": "Get user by ID",
                "method": "GET",
                "path": "/api/users/{user_id}",
                "host": "api.example.com",
                "endpoint_id": "ep_789",
                "risk_tier": "low",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                    },
                },
            },
        ],
    }


@pytest.fixture
def sample_policy() -> dict:
    """Create a sample policy."""
    return {
        "name": "Test Policy",
        "default_action": "deny",
        "audit_all": True,
        "rules": [
            {
                "id": "allow_get",
                "name": "Allow GET requests",
                "type": "allow",
                "priority": 100,
                "match": {"methods": ["GET"]},
            },
            {
                "id": "confirm_post",
                "name": "Confirm POST requests",
                "type": "confirm",
                "priority": 90,
                "match": {"methods": ["POST"]},
                "settings": {"message": "This will create data. Proceed?"},
            },
        ],
    }


@pytest.fixture
def tools_file(sample_tools_manifest: dict, tmp_path: Path) -> Path:
    """Create a temporary tools.json file."""
    tools_path = tmp_path / "tools.json"
    with open(tools_path, "w") as f:
        json.dump(sample_tools_manifest, f)
    return tools_path


@pytest.fixture
def lockfile_file(
    sample_tools_manifest: dict,
    toolsets_file: Path,
    tmp_path: Path,
) -> Path:
    """Create lockfile with partial scoped approvals."""
    import yaml

    lockfile_path = tmp_path / "toolwright.lock.yaml"
    manager = LockfileManager(lockfile_path)
    manager.load()
    with open(toolsets_file) as f:
        toolsets_payload = yaml.safe_load(f)

    manager.sync_from_manifest(sample_tools_manifest, toolsets=toolsets_payload)
    manager.approve("get_users", "security@example.com", toolset="readonly")
    manager.approve("get_user", "security@example.com", toolset="readonly")
    manager.save()
    return lockfile_path


@pytest.fixture
def toolsets_file(tmp_path: Path) -> Path:
    """Create a temporary toolsets.yaml file."""
    import yaml

    payload = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "default_toolset": "readonly",
        "toolsets": {
            "readonly": {
                "description": "Readonly actions",
                "actions": ["get_users", "get_user"],
            },
            "operator": {
                "description": "Full action surface",
                "actions": ["get_users", "create_user", "get_user"],
            },
        },
    }
    path = tmp_path / "toolsets.yaml"
    with open(path, "w") as f:
        yaml.dump(payload, f)
    return path


@pytest.fixture
def policy_file(sample_policy: dict, tmp_path: Path) -> Path:
    """Create a temporary policy.yaml file."""
    import yaml

    policy_path = tmp_path / "policy.yaml"
    with open(policy_path, "w") as f:
        yaml.dump(sample_policy, f)
    return policy_path


class TestToolwrightMCPServer:
    """Tests for ToolwrightMCPServer."""

    def test_init_loads_manifest(self, tools_file: Path) -> None:
        """Test server loads tools manifest."""
        server = ToolwrightMCPServer(tools_path=tools_file)

        assert len(server.actions) == 3
        assert "get_users" in server.actions
        assert "create_user" in server.actions
        assert "get_user" in server.actions

    def test_init_without_policy(self, tools_file: Path) -> None:
        """Test server initializes without policy."""
        server = ToolwrightMCPServer(tools_path=tools_file)

        assert server.enforcer is None

    def test_init_with_toolset_filters_actions(
        self,
        tools_file: Path,
        toolsets_file: Path,
    ) -> None:
        """Server should expose only actions in selected toolset."""
        server = ToolwrightMCPServer(
            tools_path=tools_file,
            toolsets_path=toolsets_file,
            toolset_name="readonly",
        )

        assert len(server.actions) == 2
        assert "get_users" in server.actions
        assert "get_user" in server.actions
        assert "create_user" not in server.actions

    def test_init_with_missing_toolset_raises(
        self,
        tools_file: Path,
        toolsets_file: Path,
    ) -> None:
        """Unknown toolset should fail server initialization."""
        with pytest.raises(ValueError, match="Unknown toolset"):
            ToolwrightMCPServer(
                tools_path=tools_file,
                toolsets_path=toolsets_file,
                toolset_name="does_not_exist",
            )

    def test_init_with_lockfile_enforces_approvals(
        self,
        tools_file: Path,
        toolsets_file: Path,
        lockfile_file: Path,
    ) -> None:
        """When lockfile is provided, only approved tools are exposed."""
        server = ToolwrightMCPServer(
            tools_path=tools_file,
            toolsets_path=toolsets_file,
            toolset_name="readonly",
            lockfile_path=lockfile_file,
        )

        assert set(server.actions) == {"get_users", "get_user"}

    def test_init_without_lockfile_does_not_require_approvals(
        self,
        tools_file: Path,
        toolsets_file: Path,
    ) -> None:
        """Without lockfile, all tools in toolset are exposed (no approval gate)."""
        server = ToolwrightMCPServer(
            tools_path=tools_file,
            toolsets_path=toolsets_file,
            toolset_name="operator",
        )

        assert set(server.actions) == {"get_users", "get_user", "create_user"}

    def test_init_with_policy(self, tools_file: Path, policy_file: Path) -> None:
        """Test server initializes with policy."""
        server = ToolwrightMCPServer(
            tools_path=tools_file,
            policy_path=policy_file,
        )

        assert server.enforcer is not None
        assert server.enforcer.policy.name == "Test Policy"

    def test_build_description_low_risk(self, tools_file: Path) -> None:
        """Test description building for low-risk tool (compact mode default)."""
        server = ToolwrightMCPServer(tools_path=tools_file)
        action = server.actions["get_users"]

        desc = server._build_description(action)

        assert "Get list of users" in desc
        assert "GET" in desc
        assert "[Risk:" not in desc

    def test_build_description_high_risk(self, tools_file: Path) -> None:
        """Test description building for high-risk tool."""
        server = ToolwrightMCPServer(tools_path=tools_file)
        action = server.actions["create_user"]

        desc = server._build_description(action)

        assert "Create a new user" in desc
        assert "[Risk: high]" in desc
        assert "[Requires confirmation]" in desc


    def test_build_description_hard_cap(self, tools_file: Path) -> None:
        """C1: descriptions must never exceed _DESCRIPTION_HARD_CAP chars."""
        server = ToolwrightMCPServer(tools_path=tools_file)
        # Force verbose mode with a very long description
        server.compact_descriptions = False
        action = dict(server.actions["get_users"])
        action["description"] = "A" * 1000

        desc = server._build_description(action)

        assert len(desc) <= server._DESCRIPTION_HARD_CAP
        assert desc.endswith("...")

    def test_base_url_host_added_to_allowlist(self, tools_file: Path) -> None:
        """H3: --base-url host must be auto-added to the session allowlist."""
        server = ToolwrightMCPServer(
            tools_path=tools_file,
            base_url="https://petstore3.swagger.io/api/v3",
        )
        allowed = server._allowed_app_hosts()
        assert "petstore3.swagger.io" in allowed


class TestMCPServerHandlers:
    """Tests for MCP protocol handlers."""

    @pytest.mark.asyncio
    async def test_list_tools(self, tools_file: Path) -> None:
        """Test listing available tools."""
        server = ToolwrightMCPServer(tools_path=tools_file)

        # Get the list_tools handler from registered handlers
        # We need to access the internal handler
        tools = []
        for action in server.actions.values():
            from mcp import types

            tool = types.Tool(
                name=action["name"],
                description=server._build_description(action),
                inputSchema=action.get("input_schema", {"type": "object", "properties": {}}),
            )
            tools.append(tool)

        assert len(tools) == 3
        tool_names = [t.name for t in tools]
        assert "get_users" in tool_names
        assert "create_user" in tool_names
        assert "get_user" in tool_names


class TestMCPServerDryRun:
    """Tests for dry run mode."""

    def test_dry_run_flag(self, tools_file: Path) -> None:
        """Test dry run flag is set."""
        server = ToolwrightMCPServer(
            tools_path=tools_file,
            dry_run=True,
        )

        assert server.dry_run is True

    def test_base_url_override(self, tools_file: Path) -> None:
        """Test base URL override."""
        server = ToolwrightMCPServer(
            tools_path=tools_file,
            base_url="https://custom.api.com",
        )

        assert server.base_url == "https://custom.api.com"

    def test_auth_header(self, tools_file: Path) -> None:
        """Test auth header configuration."""
        server = ToolwrightMCPServer(
            tools_path=tools_file,
            auth_header="Bearer test_token",
        )

        assert server.auth_header == "Bearer test_token"


class TestMCPRuntimeSafety:
    """Tests for MCP runtime network safety checks."""

    def test_validate_url_scheme_blocks_non_http(self, tools_file: Path) -> None:  # noqa: ARG002
        from toolwright.core.network_safety import validate_url_scheme

        with pytest.raises(RuntimeBlockError, match="Unsupported URL scheme"):
            validate_url_scheme("ftp://api.example.com/resource")

    def test_idp_hosts_are_not_runtime_allowlisted(self, tmp_path: Path) -> None:
        manifest = {
            "version": "1.0.0",
            "schema_version": "1.0",
            "allowed_hosts": {
                "app": ["api.example.com"],
                "idp": ["auth.example.com"],
            },
            "actions": [
                {
                    "name": "get_users",
                    "method": "GET",
                    "path": "/api/users",
                    "host": "api.example.com",
                    "risk_tier": "low",
                }
            ],
        }
        tools_path = tmp_path / "tools.json"
        tools_path.write_text(json.dumps(manifest), encoding="utf-8")
        server = ToolwrightMCPServer(tools_path=tools_path)

        server._validate_host_allowlist("api.example.com", "api.example.com")
        with pytest.raises(RuntimeBlockError, match="not allowlisted"):
            server._validate_host_allowlist("auth.example.com", "api.example.com")

    def test_host_allowlist_with_port_allows_matching_hostname(self, tmp_path: Path) -> None:
        manifest = {
            "version": "1.0.0",
            "schema_version": "1.0",
            "allowed_hosts": ["127.0.0.1:8443"],
            "actions": [
                {
                    "name": "get_products",
                    "method": "GET",
                    "path": "/api/products",
                    "host": "127.0.0.1:8443",
                    "risk_tier": "low",
                }
            ],
        }
        tools_path = tmp_path / "tools.json"
        tools_path.write_text(json.dumps(manifest), encoding="utf-8")
        server = ToolwrightMCPServer(tools_path=tools_path)

        server._validate_host_allowlist("127.0.0.1", "127.0.0.1:8443")
        with pytest.raises(RuntimeBlockError, match="not allowlisted"):
            server._validate_host_allowlist("192.168.1.10", "127.0.0.1:8443")

    def test_validate_network_target_allows_loopback_when_cidr_allowlisted(
        self,
        tmp_path: Path,  # noqa: ARG002
    ) -> None:
        import ipaddress

        from toolwright.core.network_safety import validate_network_target

        allow_private = [ipaddress.ip_network("127.0.0.0/8")]
        # Should not raise — loopback is allowed when CIDR covers it
        validate_network_target("127.0.0.1", allow_private)

    @pytest.mark.asyncio
    async def test_execute_request_applies_fixed_graphql_operation(self, tmp_path: Path) -> None:
        """Runtime should enforce fixed GraphQL operationName for split actions."""
        manifest = {
            "version": "1.0.0",
            "schema_version": "1.0",
            "allowed_hosts": ["api.example.com"],
            "actions": [
                {
                    "name": "query_get_product",
                    "tool_id": "abcd1234efgh5678",
                    "signature_id": "abcd1234efgh5678",
                    "description": "GraphQL GetProduct",
                    "method": "POST",
                    "path": "/api/graphql",
                    "host": "api.example.com",
                    "risk_tier": "medium",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "operationName": {"type": "string"},
                            "query": {"type": "string"},
                        },
                    },
                    "fixed_body": {"operationName": "GetProduct"},
                }
            ],
        }
        tools_path = tmp_path / "tools.json"
        tools_path.write_text(json.dumps(manifest), encoding="utf-8")

        server = ToolwrightMCPServer(tools_path=tools_path, base_url="https://api.example.com")

        captured: dict[str, object] = {}
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json = lambda: {"ok": True}

        async def mock_get_client() -> AsyncMock:
            client = AsyncMock()

            async def request(method: str, url: str, **kwargs: object) -> AsyncMock:
                captured["method"] = method
                captured["url"] = url
                captured["json"] = kwargs.get("json")
                return mock_response

            client.request = AsyncMock(side_effect=request)
            return client

        with (
            patch.object(server, "_get_http_client", mock_get_client),
            patch("toolwright.mcp.server.validate_network_target"),
        ):
            await server._execute_request(
                server.actions["query_get_product"],
                {"operationName": "WrongOp", "query": "query { product { id } }"},
            )

        sent_body = captured["json"]
        assert isinstance(sent_body, dict)
        assert sent_body["operationName"] == "GetProduct"

    @pytest.mark.asyncio
    async def test_execute_request_resolves_nextjs_build_id_token(self, tmp_path: Path) -> None:
        """Runtime should auto-resolve Next.js buildId tokens when omitted by caller."""
        manifest = {
            "version": "1.0.0",
            "schema_version": "1.0",
            "allowed_hosts": ["api.example.com"],
            "actions": [
                {
                    "name": "get_next_data_search",
                    "tool_id": "sig_next_data",
                    "signature_id": "sig_next_data",
                    "description": "Next.js data route",
                    "method": "GET",
                    "path": "/_next/data/{token}/en/search.json",
                    "host": "api.example.com",
                    "risk_tier": "low",
                    "input_schema": {
                        "type": "object",
                        "properties": {"token": {"type": "string"}},
                    },
                }
            ],
        }
        tools_path = tmp_path / "tools.json"
        tools_path.write_text(json.dumps(manifest), encoding="utf-8")

        server = ToolwrightMCPServer(tools_path=tools_path, base_url="https://api.example.com")

        build_id = "build123"
        html = (
            '<html><head><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"buildId": build_id})
            + "</script></head></html>"
        )

        captured_urls: list[str] = []
        mock_html_response = AsyncMock()
        mock_html_response.status_code = 200
        mock_html_response.headers = {"content-type": "text/html"}
        mock_html_response.text = html

        mock_json_response = AsyncMock()
        mock_json_response.status_code = 200
        mock_json_response.headers = {"content-type": "application/json"}
        mock_json_response.json = lambda: {"ok": True}

        async def mock_get_client() -> AsyncMock:
            client = AsyncMock()

            async def request(_method: str, url: str, **_kwargs: object) -> AsyncMock:
                captured_urls.append(url)
                if "/_next/data/" in url:
                    assert f"/_next/data/{build_id}/" in url
                    return mock_json_response
                return mock_html_response

            client.request = AsyncMock(side_effect=request)
            return client

        with (
            patch.object(server, "_get_http_client", mock_get_client),
            patch("toolwright.mcp.server.validate_network_target"),
        ):
            await server._execute_request(
                server.actions["get_next_data_search"],
                {"q": "jordan"},
            )

        assert any("/_next/data/" in url for url in captured_urls)

    @pytest.mark.asyncio
    async def test_execute_request_prefers_default_nextjs_build_id_token(self, tmp_path: Path) -> None:
        """If a Next.js buildId token has a default, runtime should use it without probing HTML."""
        default_build_id = "default_build_123"
        manifest = {
            "version": "1.0.0",
            "schema_version": "1.0",
            "allowed_hosts": ["api.example.com"],
            "actions": [
                {
                    "name": "get_next_data_search",
                    "tool_id": "sig_next_data",
                    "signature_id": "sig_next_data",
                    "description": "Next.js data route",
                    "method": "GET",
                    "path": "/_next/data/{token}/en/search.json",
                    "host": "api.example.com",
                    "risk_tier": "low",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "token": {"type": "string", "default": default_build_id},
                        },
                    },
                }
            ],
        }
        tools_path = tmp_path / "tools.json"
        tools_path.write_text(json.dumps(manifest), encoding="utf-8")

        server = ToolwrightMCPServer(tools_path=tools_path, base_url="https://api.example.com")

        captured_urls: list[str] = []
        mock_json_response = AsyncMock()
        mock_json_response.status_code = 200
        mock_json_response.headers = {"content-type": "application/json"}
        mock_json_response.json = lambda: {"ok": True}

        async def mock_get_client() -> AsyncMock:
            client = AsyncMock()

            async def request(_method: str, url: str, **_kwargs: object) -> AsyncMock:
                captured_urls.append(url)
                return mock_json_response

            client.request = AsyncMock(side_effect=request)
            return client

        with (
            patch.object(server, "_get_http_client", mock_get_client),
            patch("toolwright.mcp.server.validate_network_target"),
            patch.object(
                server,
                "_resolve_nextjs_build_id",
                AsyncMock(side_effect=AssertionError("nextjs_build_id probe should not run")),
            ),
        ):
            await server._execute_request(
                server.actions["get_next_data_search"],
                {"q": "jordan"},
            )

        assert any(f"/_next/data/{default_build_id}/" in url for url in captured_urls)

    @pytest.mark.asyncio
    async def test_execute_request_refreshes_nextjs_build_id_token_on_404(self, tmp_path: Path) -> None:
        """If a default buildId drifts, runtime should refresh via resolver and retry once."""
        default_build_id = "default_build_123"
        refreshed_build_id = "refreshed_build_456"
        manifest = {
            "version": "1.0.0",
            "schema_version": "1.0",
            "allowed_hosts": ["api.example.com"],
            "actions": [
                {
                    "name": "get_next_data_search",
                    "tool_id": "sig_next_data",
                    "signature_id": "sig_next_data",
                    "description": "Next.js data route",
                    "method": "GET",
                    "path": "/_next/data/{token}/en/search.json",
                    "host": "api.example.com",
                    "risk_tier": "low",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "token": {"type": "string", "default": default_build_id},
                        },
                    },
                }
            ],
        }
        tools_path = tmp_path / "tools.json"
        tools_path.write_text(json.dumps(manifest), encoding="utf-8")

        server = ToolwrightMCPServer(tools_path=tools_path, base_url="https://api.example.com")

        captured_urls: list[str] = []
        mock_404 = AsyncMock()
        mock_404.status_code = 404
        mock_404.headers = {"content-type": "application/json"}
        mock_404.json = lambda: {"error": "not found"}

        mock_200 = AsyncMock()
        mock_200.status_code = 200
        mock_200.headers = {"content-type": "application/json"}
        mock_200.json = lambda: {"ok": True}

        async def mock_get_client() -> AsyncMock:
            client = AsyncMock()

            async def request(_method: str, url: str, **_kwargs: object) -> AsyncMock:
                captured_urls.append(url)
                if f"/_next/data/{default_build_id}/" in url:
                    return mock_404
                if f"/_next/data/{refreshed_build_id}/" in url:
                    return mock_200
                raise AssertionError(f"unexpected url {url}")

            client.request = AsyncMock(side_effect=request)
            return client

        resolver = AsyncMock(return_value=refreshed_build_id)
        with (
            patch.object(server, "_get_http_client", mock_get_client),
            patch("toolwright.mcp.server.validate_network_target"),
            patch.object(server, "_resolve_nextjs_build_id", resolver),
        ):
            result = await server._execute_request(
                server.actions["get_next_data_search"],
                {"q": "jordan"},
            )

        assert result["status_code"] == 200
        assert resolver.await_count == 1
        assert any(f"/_next/data/{default_build_id}/" in url for url in captured_urls)
        assert any(f"/_next/data/{refreshed_build_id}/" in url for url in captured_urls)


class TestCrossHostRedirectAuthStripping:
    """Auth headers must be stripped when a redirect goes to a different host."""

    @pytest.mark.asyncio
    async def test_auth_stripped_on_cross_host_redirect(self, tmp_path: Path) -> None:
        """When a redirect crosses to a different host, auth headers must not leak."""
        import httpx

        manifest = {
            "version": "1.0.0",
            "schema_version": "1.0",
            "allowed_hosts": ["api.example.com", "cdn.example.com"],
            "actions": [
                {
                    "name": "get_data",
                    "method": "GET",
                    "path": "/data",
                    "host": "api.example.com",
                    "parameters": [],
                },
            ],
        }
        tools_file = tmp_path / "tools.json"
        tools_file.write_text(json.dumps(manifest))

        server = ToolwrightMCPServer(
            tools_path=tools_file,
            auth_header="Bearer secret_token",
            allow_redirects=True,
        )

        # Track headers sent per request
        captured_headers: list[dict[str, str]] = []

        redirect_response = httpx.Response(
            302,
            headers={"location": "https://cdn.example.com/data"},
            request=httpx.Request("GET", "https://api.example.com/data"),
        )
        final_response = httpx.Response(
            200,
            json={"result": "ok"},
            request=httpx.Request("GET", "https://cdn.example.com/data"),
        )

        call_count = 0

        async def mock_request(_method: str, _url: str, **kwargs: Any) -> httpx.Response:
            nonlocal call_count
            captured_headers.append(dict(kwargs.get("headers", {})))
            call_count += 1
            if call_count == 1:
                return redirect_response
            return final_response

        mock_client = AsyncMock()
        mock_client.request = mock_request

        with (
            patch.object(server, "_get_http_client", return_value=mock_client),
            patch("toolwright.mcp.server.validate_network_target"),
        ):
            result = await server._execute_request(
                server.actions["get_data"],
                {},
            )

        assert result["status_code"] == 200
        # First request should have auth
        assert "Authorization" in captured_headers[0]
        assert captured_headers[0]["Authorization"] == "Bearer secret_token"
        # Second request (different host) should NOT have auth
        assert "Authorization" not in captured_headers[1]
