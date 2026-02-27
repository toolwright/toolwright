"""Tests for enforcement gateway with proxy mode."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from toolwright.cli.enforce import EnforcementGateway
from toolwright.core.approval import LockfileManager
from toolwright.core.network_safety import RuntimeBlockError
from toolwright.models.decision import ReasonCode


def _align_lockfile_integrity(gateway: EnforcementGateway) -> None:
    """Align lockfile digest with the gateway's currently loaded artifacts."""
    if gateway.lockfile_manager and gateway.lockfile_manager.lockfile:
        gateway.lockfile_manager.lockfile.artifacts_digest = gateway.artifacts_digest_current


@pytest.fixture
def tools_manifest():
    """Create a temporary tools manifest."""
    return {
        "actions": [
            {
                "name": "get_user",
                "description": "Get a user by ID",
                "method": "GET",
                "path": "/api/users/{id}",
                "host": "api.example.com",
                "risk_tier": "low",
                "endpoint": {
                    "method": "GET",
                    "path": "/api/users/{id}",
                    "host": "api.example.com",
                },
            },
            {
                "name": "create_user",
                "description": "Create a new user",
                "method": "POST",
                "path": "/api/users",
                "host": "api.example.com",
                "risk_tier": "medium",
                "endpoint": {
                    "method": "POST",
                    "path": "/api/users",
                    "host": "api.example.com",
                },
            },
        ]
    }


@pytest.fixture
def policy_yaml():
    """Create a policy YAML string."""
    return """
name: test_policy
rules:
  - id: allow_get
    name: Allow GET requests
    type: allow
    match:
      methods: [GET]
  - id: confirm_post
    name: Confirm POST requests
    type: confirm
    match:
      methods: [POST]
    settings:
      message: "Confirm creation?"
default_action: deny
"""


@pytest.fixture
def temp_files(tools_manifest, policy_yaml):
    """Create temporary tools and policy files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tools_path = Path(tmpdir) / "tools.json"
        policy_path = Path(tmpdir) / "policy.yaml"

        tools_path.write_text(json.dumps(tools_manifest))
        policy_path.write_text(policy_yaml)

        yield str(tools_path), str(policy_path)


@pytest.fixture
def temp_files_with_toolsets(tools_manifest, policy_yaml):
    """Create temporary tools, policy, and toolsets files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tools_path = Path(tmpdir) / "tools.json"
        policy_path = Path(tmpdir) / "policy.yaml"
        toolsets_path = Path(tmpdir) / "toolsets.yaml"

        tools_path.write_text(json.dumps(tools_manifest))
        policy_path.write_text(policy_yaml)
        toolsets_path.write_text(
            """
schema_version: "1.0"
toolsets:
  readonly:
    actions:
      - get_user
  operator:
    actions:
      - get_user
      - create_user
""".strip()
        )

        yield str(tools_path), str(policy_path), str(toolsets_path)


@pytest.fixture
def temp_files_top_level_only(tools_manifest, policy_yaml):
    """Create temporary files with actions using only top-level endpoint fields."""
    top_level_only_manifest = {
        "actions": [
            {k: v for k, v in action.items() if k != "endpoint"}
            for action in tools_manifest["actions"]
        ]
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tools_path = Path(tmpdir) / "tools.json"
        policy_path = Path(tmpdir) / "policy.yaml"

        tools_path.write_text(json.dumps(top_level_only_manifest))
        policy_path.write_text(policy_yaml)

        yield str(tools_path), str(policy_path)


@pytest.fixture
def temp_files_bad_manifest_schema(tools_manifest, policy_yaml):
    """Create temporary files with unsupported manifest schema version."""
    bad_manifest = dict(tools_manifest)
    bad_manifest["schema_version"] = "999.0"

    with tempfile.TemporaryDirectory() as tmpdir:
        tools_path = Path(tmpdir) / "tools.json"
        policy_path = Path(tmpdir) / "policy.yaml"

        tools_path.write_text(json.dumps(bad_manifest))
        policy_path.write_text(policy_yaml)

        yield str(tools_path), str(policy_path)


@pytest.fixture
def approved_lockfile(tools_manifest):
    """Create a lockfile where all tools are approved."""
    with tempfile.TemporaryDirectory() as tmpdir:
        lockfile_path = Path(tmpdir) / "toolwright.lock.yaml"
        manager = LockfileManager(lockfile_path)
        manager.load()
        manager.sync_from_manifest(tools_manifest)
        manager.approve_all("tests")
        manager.save()
        yield str(lockfile_path)


@pytest.fixture
def lockfile_with_pending_write(tools_manifest):
    """Create a lockfile with write actions left pending."""
    with tempfile.TemporaryDirectory() as tmpdir:
        lockfile_path = Path(tmpdir) / "toolwright.lock.yaml"
        manager = LockfileManager(lockfile_path)
        manager.load()
        manager.sync_from_manifest(tools_manifest)
        manager.approve("get_user", "tests")
        manager.save()
        yield str(lockfile_path)


class TestEnforcementGatewayInit:
    """Tests for gateway initialization."""

    def test_init_evaluate_mode(self, temp_files):
        """Gateway initializes in evaluate mode by default."""
        tools_path, policy_path = temp_files
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
        )
        assert gateway.mode == "evaluate"
        assert gateway.base_url is None
        assert len(gateway.actions) == 2

    def test_init_proxy_mode(self, temp_files, approved_lockfile):
        """Gateway initializes in proxy mode with base URL."""
        tools_path, policy_path = temp_files
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
            mode="proxy",
            base_url="https://api.example.com",
            auth_header="Bearer test123",
            lockfile_path=approved_lockfile,
        )
        assert gateway.mode == "proxy"
        assert gateway.base_url == "https://api.example.com"
        assert gateway.auth_header == "Bearer test123"

    def test_init_rejects_unsupported_manifest_schema(
        self,
        temp_files_bad_manifest_schema,
    ):
        """Gateway rejects unsupported tools manifest schema versions."""
        tools_path, policy_path = temp_files_bad_manifest_schema
        with pytest.raises(ValueError, match="Unsupported tools manifest schema_version"):
            EnforcementGateway(
                tools_path=tools_path,
                policy_path=policy_path,
            )

    def test_init_with_toolset_filters_actions(self, temp_files_with_toolsets):
        """Gateway should load only actions in selected toolset."""
        tools_path, policy_path, toolsets_path = temp_files_with_toolsets
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
            toolsets_path=toolsets_path,
            toolset_name="readonly",
        )
        assert set(gateway.actions.keys()) == {"get_user"}


class TestEnforcementGatewayEvaluate:
    """Tests for gateway evaluate_action."""

    def test_evaluate_allowed_action(self, temp_files):
        """Evaluate allows GET requests."""
        tools_path, policy_path = temp_files
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
        )

        result = gateway.evaluate_action("get_user", {"id": "123"})
        assert result["allowed"] is True

    def test_evaluate_unknown_action(self, temp_files):
        """Evaluate returns error for unknown action."""
        tools_path, policy_path = temp_files
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
        )

        result = gateway.evaluate_action("unknown_action")
        assert result["allowed"] is False
        assert "Unknown action" in result["error"]

    def test_evaluate_confirmation_required(self, temp_files):
        """Evaluate returns confirmation required for POST."""
        tools_path, policy_path = temp_files
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
        )

        result = gateway.evaluate_action("create_user", {"name": "John"})
        assert result["allowed"] is False
        assert result["requires_confirmation"] is True
        assert result["confirmation_token"] is not None

    def test_evaluate_top_level_contract_when_endpoint_missing(
        self,
        temp_files_top_level_only,
    ):
        """Evaluate uses top-level method/path/host fields if endpoint is missing."""
        tools_path, policy_path = temp_files_top_level_only
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
        )

        read_result = gateway.evaluate_action("get_user", {"id": "123"})
        assert read_result["allowed"] is True
        assert read_result["rule_id"] == "allow_get"

        result = gateway.evaluate_action("create_user", {"name": "John"})
        assert result["allowed"] is False
        assert result["requires_confirmation"] is True

        pending = gateway.get_pending()
        assert len(pending) == 1
        assert pending[0]["action_id"] == "create_user"
        assert pending[0]["method"] == "POST"
        assert pending[0]["path"] == "/api/users"
        assert pending[0]["host"] == "api.example.com"


class TestEnforcementGatewayExecute:
    """Tests for gateway execute_action in proxy mode."""

    def test_execute_dry_run(self, temp_files, approved_lockfile):
        """Execute in dry run mode returns without calling upstream."""
        tools_path, policy_path = temp_files
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
            mode="proxy",
            dry_run=True,
            lockfile_path=approved_lockfile,
        )
        _align_lockfile_integrity(gateway)

        result = gateway.execute_action("get_user", {"id": "123"})
        assert result["allowed"] is True
        assert result["dry_run"] is True
        assert "would be sent" in result["message"]

    def test_execute_not_allowed(self, temp_files, approved_lockfile):
        """Execute returns policy denial for unauthorized requests."""
        tools_path, policy_path = temp_files
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
            mode="proxy",
            lockfile_path=approved_lockfile,
        )
        _align_lockfile_integrity(gateway)

        # create_user requires confirmation, so it's not immediately allowed
        result = gateway.execute_action("create_user", {"name": "John"})
        assert result["allowed"] is False
        assert result["requires_confirmation"] is True

    def test_execute_unknown_action(self, temp_files, approved_lockfile):
        """Execute returns error for unknown action."""
        tools_path, policy_path = temp_files
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
            mode="proxy",
            lockfile_path=approved_lockfile,
        )
        _align_lockfile_integrity(gateway)

        result = gateway.execute_action("unknown")
        assert result["allowed"] is False
        assert "Unknown action" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_upstream_success(self, temp_files, approved_lockfile):
        """Execute forwards request to upstream and returns response."""
        tools_path, policy_path = temp_files
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
            mode="proxy",
            base_url="https://api.example.com",
            lockfile_path=approved_lockfile,
        )
        _align_lockfile_integrity(gateway)

        # Mock the HTTP client with proper async return values
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        # json() is a sync method on httpx.Response, not async
        mock_response.json = lambda: {"id": "123", "name": "John"}

        async def mock_get_client():
            client = AsyncMock()
            client.request = AsyncMock(return_value=mock_response)
            return client

        with (
            patch.object(gateway, "_get_http_client", mock_get_client),
            patch("toolwright.cli.enforce.validate_network_target"),
        ):
            response = await gateway._execute_upstream(
                gateway.actions["get_user"],
                {"id": "123"}
            )

        assert response["status_code"] == 200
        assert response["body"]["id"] == "123"

    @pytest.mark.asyncio
    async def test_execute_upstream_applies_fixed_graphql_operation(self, tmp_path):
        """Proxy execution should enforce fixed GraphQL operationName for split tools."""
        tools_manifest = {
            "actions": [
                {
                    "name": "query_get_product",
                    "description": "GraphQL GetProduct",
                    "method": "POST",
                    "path": "/api/graphql",
                    "host": "api.example.com",
                    "risk_tier": "medium",
                    "fixed_body": {"operationName": "GetProduct"},
                }
            ]
        }
        tools_path = tmp_path / "tools.json"
        policy_path = tmp_path / "policy.yaml"
        tools_path.write_text(json.dumps(tools_manifest))
        policy_path.write_text(
            """
name: test_policy
rules:
  - id: allow_post
    name: Allow POST requests
    type: allow
    match:
      methods: [POST]
default_action: deny
""".strip()
        )

        gateway = EnforcementGateway(
            tools_path=str(tools_path),
            policy_path=str(policy_path),
            mode="proxy",
            base_url="https://api.example.com",
            unsafe_no_lockfile=True,
        )

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
            patch.object(gateway, "_get_http_client", mock_get_client),
            patch("toolwright.cli.enforce.validate_network_target"),
        ):
            await gateway._execute_upstream(
                gateway.actions_by_name["query_get_product"],
                {"operationName": "WrongOp", "query": "query { product { id } }"},
            )

        sent_body = captured["json"]
        assert isinstance(sent_body, dict)
        assert sent_body["operationName"] == "GetProduct"

    @pytest.mark.asyncio
    async def test_execute_upstream_resolves_nextjs_build_id_token(self, tmp_path):
        """Proxy execution should auto-resolve Next.js buildId tokens when omitted."""
        tools_manifest = {
            "allowed_hosts": ["api.example.com"],
            "actions": [
                {
                    "name": "get_next_data_search",
                    "description": "Next.js data route",
                    "method": "GET",
                    "path": "/_next/data/{token}/en/search.json",
                    "host": "api.example.com",
                    "risk_tier": "low",
                }
            ],
        }
        tools_path = tmp_path / "tools.json"
        policy_path = tmp_path / "policy.yaml"
        tools_path.write_text(json.dumps(tools_manifest))
        policy_path.write_text(
            """
name: test_policy
rules:
  - id: allow_get
    name: Allow GET requests
    type: allow
    match:
      methods: [GET]
default_action: deny
""".strip()
        )

        gateway = EnforcementGateway(
            tools_path=str(tools_path),
            policy_path=str(policy_path),
            mode="proxy",
            base_url="https://api.example.com",
            unsafe_no_lockfile=True,
        )

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
            patch.object(gateway, "_get_http_client", mock_get_client),
            patch("toolwright.cli.enforce.validate_network_target"),
        ):
            await gateway._execute_upstream(
                gateway.actions_by_name["get_next_data_search"],
                {"q": "jordan"},
            )

        assert any("/_next/data/" in url for url in captured_urls)


class TestEnforcementGatewayConfirmation:
    """Tests for confirmation workflow."""

    def test_confirm_action(self, temp_files):
        """Confirm grants confirmation token."""
        tools_path, policy_path = temp_files
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
        )

        # First get a confirmation token
        result = gateway.evaluate_action("create_user", {"name": "John"})
        token = result["confirmation_token"]

        # Confirm it
        confirm_result = gateway.confirm_action(token)
        assert confirm_result["confirmed"] is True

    def test_deny_action(self, temp_files):
        """Deny removes confirmation request."""
        tools_path, policy_path = temp_files
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
        )

        # First get a confirmation token
        result = gateway.evaluate_action("create_user", {"name": "John"})
        token = result["confirmation_token"]

        # Deny it
        deny_result = gateway.deny_action(token, "Not authorized")
        assert deny_result["denied"] is True
        assert deny_result["reason"] == "Not authorized"

    def test_get_pending(self, temp_files):
        """Get pending returns all pending confirmations."""
        tools_path, policy_path = temp_files
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
        )

        # Create a pending confirmation
        gateway.evaluate_action("create_user", {"name": "John"})

        pending = gateway.get_pending()
        assert len(pending) == 1


class TestEnforcementGatewayRuntimeApproval:
    """Tests for lockfile runtime approval gating."""

    def test_proxy_mode_requires_lockfile(self, temp_files):
        """Proxy mode requires lockfile unless unsafe override is enabled."""
        tools_path, policy_path = temp_files

        with pytest.raises(ValueError, match="Proxy mode requires lockfile"):
            EnforcementGateway(
                tools_path=tools_path,
                policy_path=policy_path,
                mode="proxy",
            )

    def test_proxy_mode_allows_unsafe_no_lockfile(self, temp_files):
        """Unsafe override permits proxy startup without lockfile."""
        tools_path, policy_path = temp_files

        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
            mode="proxy",
            unsafe_no_lockfile=True,
        )
        assert gateway.mode == "proxy"

    def test_proxy_mode_blocks_unapproved_write(
        self,
        temp_files,
        lockfile_with_pending_write,
    ):
        """State-changing actions are blocked until approved in lockfile."""
        tools_path, policy_path = temp_files
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
            mode="proxy",
            lockfile_path=lockfile_with_pending_write,
        )
        _align_lockfile_integrity(gateway)

        result = gateway.evaluate_action("create_user", {"name": "John"})
        assert result["allowed"] is False
        assert result["reason_code"] == "denied_not_approved"

    def test_proxy_mode_allows_approved_read_with_lockfile(
        self,
        temp_files,
        lockfile_with_pending_write,
    ):
        """Read actions remain available when lockfile exists."""
        tools_path, policy_path = temp_files
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
            mode="proxy",
            lockfile_path=lockfile_with_pending_write,
        )
        _align_lockfile_integrity(gateway)

        result = gateway.evaluate_action("get_user", {"id": "123"})
        assert result["allowed"] is True

    def test_proxy_mode_toolset_restricts_action_surface(
        self,
        temp_files_with_toolsets,
        approved_lockfile,
    ):
        """Selected toolset should hide actions outside its membership."""
        tools_path, policy_path, toolsets_path = temp_files_with_toolsets
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
            toolsets_path=toolsets_path,
            toolset_name="readonly",
            mode="proxy",
            lockfile_path=approved_lockfile,
        )

        result = gateway.evaluate_action("create_user", {"name": "John"})
        assert result["allowed"] is False
        assert "Unknown action" in result["error"]


class TestEnforcementGatewayNetworkSafety:
    """Tests for scheme and DNS/IP safety hardening."""

    @pytest.mark.asyncio
    async def test_execute_blocks_non_http_scheme(self, temp_files, approved_lockfile):
        tools_path, policy_path = temp_files
        gateway = EnforcementGateway(
            tools_path=tools_path,
            policy_path=policy_path,
            mode="proxy",
            base_url="ftp://api.example.com",
            lockfile_path=approved_lockfile,
        )
        _align_lockfile_integrity(gateway)

        with pytest.raises(RuntimeBlockError, match="Unsupported URL scheme"):
            await gateway._execute_upstream(gateway.actions["get_user"], {"id": "123"})

    def test_validate_network_target_blocks_metadata_ip(self, temp_files, approved_lockfile):  # noqa: ARG002
        from toolwright.core.network_safety import validate_network_target

        with (
            patch(
                "toolwright.core.network_safety.socket.getaddrinfo",
                return_value=[(None, None, None, None, ("169.254.169.254", 443))],
            ),
            pytest.raises(RuntimeBlockError, match="metadata"),
        ):
            validate_network_target("api.example.com", [])

    def test_idp_hosts_are_not_runtime_allowlisted(self, tmp_path: Path, approved_lockfile):
        tools_path = tmp_path / "tools.json"
        policy_path = tmp_path / "policy.yaml"
        tools_path.write_text(
            json.dumps(
                {
                    "allowed_hosts": {
                        "app": ["api.example.com"],
                        "idp": ["auth.example.com"],
                    },
                    "actions": [
                        {
                            "name": "get_user",
                            "method": "GET",
                            "path": "/api/users/{id}",
                            "host": "api.example.com",
                            "risk_tier": "low",
                            "endpoint": {
                                "method": "GET",
                                "path": "/api/users/{id}",
                                "host": "api.example.com",
                            },
                        }
                    ],
                }
            )
        )
        policy_path.write_text(
            """
name: test_policy
rules:
  - id: allow_get
    name: Allow GET requests
    type: allow
    match:
      methods: [GET]
default_action: deny
""".strip()
        )
        gateway = EnforcementGateway(
            tools_path=str(tools_path),
            policy_path=str(policy_path),
            mode="proxy",
            lockfile_path=approved_lockfile,
        )
        gateway._validate_host_allowlist("api.example.com", "api.example.com")
        with pytest.raises(RuntimeBlockError, match="not allowlisted"):
            gateway._validate_host_allowlist("auth.example.com", "api.example.com")


class TestDecisionTraceAudit:
    """Tests for strict DecisionTrace audit emission."""

    def test_evaluate_emits_decision_trace_with_required_fields(self, temp_files):
        tools_path, policy_path = temp_files
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_log = Path(tmpdir) / "audit.log.jsonl"
            gateway = EnforcementGateway(
                tools_path=tools_path,
                policy_path=policy_path,
                mode="evaluate",
                audit_log=str(audit_log),
            )
            result = gateway.evaluate_action("get_user", {"id": "123"})
            assert result["allowed"] is True

            lines = audit_log.read_text(encoding="utf-8").strip().splitlines()
            assert lines
            event = json.loads(lines[-1])
            required_keys = {
                "timestamp",
                "run_id",
                "tool_id",
                "scope_id",
                "request_fingerprint",
                "decision",
                "reason_code",
                "evidence_refs",
                "lockfile_digest",
                "policy_digest",
                "confirmation_issuer",
                "provenance_mode",
            }
            assert required_keys.issubset(event.keys())

    def test_decision_trace_one_record_per_decision_with_stable_schema(self, temp_files):
        tools_path, policy_path = temp_files
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_log = Path(tmpdir) / "audit.log.jsonl"
            gateway = EnforcementGateway(
                tools_path=tools_path,
                policy_path=policy_path,
                mode="evaluate",
                audit_log=str(audit_log),
            )
            allow_result = gateway.evaluate_action("get_user", {"id": "123"})
            unknown_result = gateway.evaluate_action("missing_action", {})

            assert allow_result["allowed"] is True
            assert unknown_result["allowed"] is False

            lines = [line for line in audit_log.read_text(encoding="utf-8").splitlines() if line]
            assert len(lines) == 2

            expected_keys = {
                "confirmation_issuer",
                "decision",
                "evidence_refs",
                "lockfile_digest",
                "policy_digest",
                "provenance_mode",
                "reason",
                "reason_code",
                "request_fingerprint",
                "run_id",
                "scope_id",
                "timestamp",
                "tool_id",
            }
            valid_reason_codes = {reason.value for reason in ReasonCode}
            for line in lines:
                event = json.loads(line)
                assert set(event.keys()) == expected_keys
                assert event["reason_code"] in valid_reason_codes
