"""MCP server implementation for Toolwright."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

import httpx

from toolwright.core.approval import (
    ApprovalStatus,
    compute_lockfile_digest,
)
from toolwright.core.network_safety import (
    RuntimeBlockError,
    host_matches_allowlist,
    normalize_host_for_allowlist,
    validate_network_target,
    validate_url_scheme,
)
from toolwright.core.toolpack import ToolpackAuthRequirement
from toolwright.mcp._compat import (
    InitializationOptions,
    NotificationOptions,
    Server,
    mcp_stdio,
)
from toolwright.mcp._compat import (
    mcp_types as types,
)
from toolwright.models.decision import (
    ReasonCode,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESPONSE_BYTES: int = 10 * 1024 * 1024  # 10 MB


def get_max_response_bytes() -> int:
    """Return max response size from env or default."""
    return int(os.environ.get("TOOLWRIGHT_MAX_RESPONSE_BYTES", DEFAULT_MAX_RESPONSE_BYTES))


def _check_response_size(
    content_length: int | None,
    max_bytes: int,
) -> None:
    """Raise RuntimeBlockError if content_length exceeds max_bytes.

    Does nothing when content_length is None (header absent) or max_bytes is 0
    (unlimited).
    """
    if max_bytes == 0 or content_length is None:
        return
    if content_length > max_bytes:
        from toolwright.core.network_safety import RuntimeBlockError

        raise RuntimeBlockError(
            ReasonCode.DENIED_RESPONSE_TOO_LARGE,
            f"Response size {content_length} bytes exceeds limit of {max_bytes} bytes",
        )


_NEXTJS_DATA_PLACEHOLDER_RE = re.compile(r"/_next/data/\{([^}]+)\}/", re.IGNORECASE)
_NEXTJS_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


class ToolwrightMCPServer:
    """MCP server that exposes Toolwright tools with runtime enforcement."""

    def __init__(
        self,
        tools_path: str | Path,
        toolsets_path: str | Path | None = None,
        toolset_name: str | None = None,
        policy_path: str | Path | None = None,
        lockfile_path: str | Path | None = None,
        base_url: str | None = None,
        auth_header: str | None = None,
        audit_log: str | Path | None = None,
        dry_run: bool = False,
        confirmation_store_path: str | Path = ".toolwright/state/confirmations.db",
        allow_private_cidrs: list[str] | None = None,
        allow_redirects: bool = False,
        rules_path: str | Path | None = None,
        circuit_breaker_path: str | Path | None = None,
        extra_headers: dict[str, str] | None = None,
        schema_validation: str = "warn",
        auth_requirements: list[ToolpackAuthRequirement] | None = None,
    ) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        # ── Build transport-agnostic governance runtime ────────────────
        self._runtime = GovernanceRuntime(
            tools_path=tools_path,
            toolsets_path=toolsets_path,
            toolset_name=toolset_name,
            policy_path=policy_path,
            lockfile_path=lockfile_path,
            base_url=base_url,
            auth_header=auth_header,
            audit_log=audit_log,
            dry_run=dry_run,
            confirmation_store_path=confirmation_store_path,
            allow_private_cidrs=allow_private_cidrs,
            allow_redirects=allow_redirects,
            rules_path=rules_path,
            circuit_breaker_path=circuit_breaker_path,
            extra_headers=extra_headers,
            schema_validation=schema_validation,
            auth_requirements=auth_requirements,
            transport_type="mcp",
            execute_request_fn=lambda action, args: self._execute_request(action, args),
        )

        # ── Expose governance attributes for backward compatibility ────
        # These delegate to the runtime so existing tests and callers
        # continue to work unchanged.
        self.schema_validation = schema_validation
        self._auth_requirements = auth_requirements or []
        self.tools_path = self._runtime.tools_path
        self.toolsets_path = self._runtime.toolsets_path
        self.toolset_name = self._runtime.toolset_name
        self.policy_path = self._runtime.policy_path
        self.lockfile_path = self._runtime.lockfile_path
        self.base_url = self._runtime.base_url
        self.auth_header = self._runtime.auth_header
        self.extra_headers = self._runtime.extra_headers
        self.dry_run = self._runtime.dry_run
        self.allow_private_networks = self._runtime.allow_private_networks
        self.allow_redirects = self._runtime.allow_redirects
        self.approval_root_path = self._runtime.approval_root_path
        self.run_id = self._runtime.run_id

        self.manifest = self._runtime.manifest
        self.toolsets_payload = self._runtime.toolsets_payload
        self.lockfile_manager = self._runtime.lockfile_manager
        self.lockfile_digest_current = self._runtime.lockfile_digest_current
        self._lockfile_mtime = self._runtime._lockfile_mtime
        self._last_lockfile_check = self._runtime._last_lockfile_check
        self.actions = self._runtime.actions
        self.actions_by_tool_id = self._runtime.actions_by_tool_id

        self.audit_logger = self._runtime.audit_logger
        self.policy_digest = self._runtime.policy_digest
        self.decision_trace = self._runtime.decision_trace
        self.policy_engine = self._runtime.policy_engine
        self.enforcer = self._runtime.enforcer
        self.artifacts_digest_current = self._runtime.artifacts_digest_current
        self.confirmation_store = self._runtime.confirmation_store
        self.decision_engine = self._runtime.decision_engine
        self.decision_context = self._runtime.decision_context
        self.rule_engine = self._runtime.rule_engine
        self.session_history = self._runtime.session_history
        self.circuit_breaker = self._runtime.circuit_breaker

        self.pipeline = self._runtime.engine

        # ── MCP-specific setup ─────────────────────────────────────────
        self.compact_descriptions: bool = True
        self.server = Server("toolwright")
        self._register_handlers()
        self._register_signal_handlers()
        self._http_client: httpx.AsyncClient | None = None
        self._nextjs_build_id_cache: dict[str, str] = {}

        logger.info(
            "Initialized Toolwright MCP server with %s tools",
            len(self.actions),
        )

    def _maybe_reload_lockfile(self) -> None:
        """Delegate lockfile reload to GovernanceRuntime."""
        self._runtime.maybe_reload_lockfile()
        # Sync mutable state back from runtime for backward-compat
        self.lockfile_digest_current = self._runtime.lockfile_digest_current

    def _register_signal_handlers(self) -> None:
        """Register graceful shutdown handlers (SIGTERM)."""
        if sys.platform == "win32":
            return  # signal.SIGTERM not reliably supported on Windows

        def _handle_sigterm(_signum: int, _frame: Any) -> None:
            logger.info("Received SIGTERM, shutting down gracefully")
            # Use os._exit to ensure immediate clean termination even inside
            # asyncio event loops which may catch or defer SystemExit.
            os._exit(0)

        signal.signal(signal.SIGTERM, _handle_sigterm)

    def _register_handlers(self) -> None:
        @self.server.list_tools()  # type: ignore
        async def handle_list_tools() -> list[types.Tool]:
            tools = []
            for action in self.actions.values():
                tool = types.Tool(
                    name=action["name"],
                    description=self._build_description(action),
                    inputSchema=action.get("input_schema", {"type": "object", "properties": {}}),
                )
                if self.schema_validation == "strict":
                    output_schema = action.get("output_schema")
                    if isinstance(output_schema, dict):
                        # MCP structuredContent is object-only in practice (and in the reference
                        # `mcp` types). Avoid advertising an outputSchema for non-object payloads
                        # (arrays/scalars), since clients will require structuredContent when an
                        # outputSchema is present.
                        schema_type = output_schema.get("type")
                        is_object_schema = schema_type == "object" or (
                            schema_type is None and "properties" in output_schema
                        )
                        if is_object_schema:
                            tool.outputSchema = output_schema
                tools.append(tool)
            return tools

        @self.server.call_tool()  # type: ignore
        async def handle_call_tool(
            name: str,
            arguments: dict[str, Any] | None,
        ) -> Any:
            self._maybe_reload_lockfile()
            try:
                result = await self.pipeline.execute(
                    name,
                    arguments or {},
                    toolset_name=self.toolset_name,
                )
                return self._format_mcp_result(result)
            except Exception as exc:
                logger.error("Unhandled error in tool call '%s': %s", name, exc, exc_info=True)
                text = f"Internal error: {type(exc).__name__}: {exc}"
                if hasattr(types, "CallToolResult"):
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=text)],
                        isError=True,
                    )
                return [types.TextContent(type="text", text=text)]

    def _format_mcp_result(self, result: Any) -> Any:
        """Convert a PipelineResult to MCP wire format."""
        from toolwright.mcp.pipeline import PipelineResult

        if not isinstance(result, PipelineResult):
            return result

        # Structured output: return raw dict for MCP structuredContent
        # Only when outputSchema is advertised (strict mode); otherwise
        # fall through to text content so the client doesn't choke.
        if result.is_structured and self.schema_validation == "strict":
            return result.payload

        # Raw (non-envelope dict): return as-is for MCP
        if result.is_raw:
            return result.payload

        # Standard success/error: wrap in CallToolResult with TextContent
        payload = result.payload
        text = json.dumps(payload) if not isinstance(payload, str) else payload
        if hasattr(types, "CallToolResult"):
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text)],
                isError=result.is_error,
            )
        return [types.TextContent(type="text", text=text)]

    def _emit_decision_trace(
        self,
        *,
        tool_id: str | None,
        scope_id: str | None,
        request_fingerprint: str | None,
        decision: str,
        reason_code: str,
        reason: str | None,
    ) -> None:
        self.decision_trace.emit(
            tool_id=tool_id,
            scope_id=scope_id,
            request_fingerprint=request_fingerprint,
            decision=decision,
            reason_code=reason_code,
            provenance_mode="runtime",
            extra={"reason": reason} if reason else None,
        )

    _DESCRIPTION_HARD_CAP = 500

    def _build_description(self, action: dict[str, Any]) -> str:
        from toolwright.mcp.description import optimize_description

        compact = getattr(self, "compact_descriptions", True)
        desc = optimize_description(action, compact=compact)
        if action.get("confirmation_required") == "always":
            desc += " [Requires confirmation]"
        # Hard cap to prevent token bombs in LLM context windows
        cap = ToolwrightMCPServer._DESCRIPTION_HARD_CAP
        if len(desc) > cap:
            desc = desc[: cap - 3] + "..."
        return desc

    def _resolve_auth_for_host(self, host: str) -> str | None:
        """Resolve auth header for a specific host.

        Priority: self.auth_header (--auth / TOOLWRIGHT_AUTH_HEADER) >
                  TOOLWRIGHT_AUTH_<NORMALIZED_HOST> > None
        """
        if self.auth_header:
            return self.auth_header
        # Check per-host env var: api.example.com -> TOOLWRIGHT_AUTH_API_EXAMPLE_COM
        normalized = re.sub(r"[^A-Za-z0-9]", "_", host).upper()
        env_key = f"TOOLWRIGHT_AUTH_{normalized}"
        return os.environ.get(env_key)

    def _resolve_auth_header_name(self, host: str) -> str:
        """Resolve which header name to use for auth on this host.

        Checks ToolpackAuthRequirement entries for a custom header_name.
        Falls back to 'Authorization'.
        """
        for req in self._auth_requirements:
            if req.host == host and req.header_name:
                return req.header_name
        return "Authorization"

    def _resolve_action_endpoint(self, action: dict[str, Any]) -> tuple[str, str, str]:
        endpoint = action.get("endpoint")
        endpoint_data = endpoint if isinstance(endpoint, dict) else {}

        method = endpoint_data.get("method") or action.get("method") or "GET"
        path = endpoint_data.get("path") or action.get("path") or "/"
        host = endpoint_data.get("host") or action.get("host") or ""
        return str(method), str(path), str(host)

    def _apply_fixed_body(
        self,
        action: dict[str, Any],
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge action-level fixed body fields into tool arguments."""
        resolved = dict(arguments)
        fixed_body = action.get("fixed_body")
        if not isinstance(fixed_body, dict):
            return resolved

        for key, value in fixed_body.items():
            resolved[str(key)] = value
        return resolved

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def _resolve_nextjs_build_id(
        self,
        *,
        action_host: str,
        path_template: str,
        params: dict[str, Any],
    ) -> str:
        cached = self._nextjs_build_id_cache.get(action_host)
        if cached:
            return cached

        probe_path = self._nextjs_probe_path(path_template, params)
        base = (self.base_url or f"https://{action_host}").rstrip("/") + "/"
        probe_url = urljoin(base, probe_path.lstrip("/"))

        headers: dict[str, str] = {"User-Agent": "Toolwright/1.0"}
        auth = self._resolve_auth_for_host(action_host)
        if auth:
            headers[self._resolve_auth_header_name(action_host)] = auth
        if self.extra_headers:
            headers.update(self.extra_headers)

        client = await self._get_http_client()
        current_url = probe_url
        for _ in range(2):
            validate_url_scheme(current_url)
            parsed = urlparse(current_url)
            target_host = parsed.hostname or action_host
            self._validate_host_allowlist(target_host, action_host)
            validate_network_target(target_host, self.allow_private_networks)

            response = await client.request(
                "GET",
                current_url,
                headers=headers,
                follow_redirects=False,
            )
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    break
                next_url = urljoin(current_url, location)
                next_host = urlparse(next_url).hostname
                if not next_host:
                    break
                self._validate_host_allowlist(next_host, action_host)
                validate_network_target(next_host, self.allow_private_networks)
                current_url = next_url
                continue

            html = response.text or ""
            match = _NEXTJS_NEXT_DATA_RE.search(html)
            if not match:
                raise RuntimeBlockError(
                    ReasonCode.DENIED_PARAM_VALIDATION,
                    f"Failed to resolve Next.js build ID from {current_url}: __NEXT_DATA__ not found",
                )
            raw = match.group(1).strip()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeBlockError(
                    ReasonCode.DENIED_PARAM_VALIDATION,
                    f"Failed to parse __NEXT_DATA__ JSON from {current_url}: {exc}",
                ) from exc

            build_id = payload.get("buildId")
            if not isinstance(build_id, str) or not build_id.strip():
                raise RuntimeBlockError(
                    ReasonCode.DENIED_PARAM_VALIDATION,
                    f"Failed to resolve Next.js build ID from {current_url}: buildId missing",
                )

            resolved = build_id.strip()
            self._nextjs_build_id_cache[action_host] = resolved
            return resolved

        raise RuntimeBlockError(
            ReasonCode.DENIED_PARAM_VALIDATION,
            f"Failed to resolve Next.js build ID for host '{action_host}'",
        )

    @staticmethod
    def _nextjs_probe_path(path_template: str, params: dict[str, Any]) -> str:
        """Pick a lightweight HTML page path for extracting __NEXT_DATA__ buildId."""
        segments = [s for s in (path_template or "").split("/") if s]
        try:
            idx = next(
                i for i in range(len(segments) - 2)
                if segments[i].lower() == "_next" and segments[i + 1].lower() == "data"
            )
        except StopIteration:
            return "/"

        tail = segments[idx + 3 :]  # skip `_next/data/{token}`
        if not tail:
            return "/"

        last = tail[-1]
        if last.lower().endswith(".json"):
            tail[-1] = last[:-5]

        page_path = "/" + "/".join(tail)
        for key, value in params.items():
            page_path = page_path.replace(f"{{{key}}}", str(value))

        # Prefer locale roots like `/en` to avoid redirects and placeholders.
        parts = [p for p in page_path.split("/") if p]
        if parts and re.fullmatch(r"[a-z]{2}", parts[0].lower()):
            return "/" + parts[0]
        return "/"

    def _validate_host_allowlist(self, target_host: str, action_host: str) -> None:
        allowed_hosts = self._allowed_app_hosts()
        if host_matches_allowlist(target_host, allowed_hosts):
            return
        if not allowed_hosts and normalize_host_for_allowlist(target_host) == normalize_host_for_allowlist(action_host):
            return
        raise RuntimeBlockError(
            ReasonCode.DENIED_REDIRECT_NOT_ALLOWLISTED,
            f"Host '{target_host}' is not allowlisted for action host '{action_host}'",
        )

    def _allowed_app_hosts(self) -> set[str]:
        raw_allowed = self.manifest.get("allowed_hosts", [])
        if isinstance(raw_allowed, dict):
            app_hosts = raw_allowed.get("app", [])
            if not isinstance(app_hosts, list):
                hosts: set[str] = set()
            else:
                hosts = {str(host).lower() for host in app_hosts}
        elif isinstance(raw_allowed, list):
            hosts = {str(host).lower() for host in raw_allowed}
        else:
            hosts = set()
        # H3: When --base-url is specified, auto-add its host to the allowlist
        if self.base_url:
            from urllib.parse import urlparse
            parsed = urlparse(self.base_url)
            if parsed.netloc:
                hosts.add(parsed.netloc.lower())
        return hosts

    async def _execute_request(
        self,
        action: dict[str, Any],
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        arguments = self._apply_fixed_body(action, arguments)
        method, path, action_host = self._resolve_action_endpoint(action)

        # Derived runtime parameters (e.g., Next.js buildId) are resolved on demand.
        nextjs_token_name: str | None = None
        nextjs_token_user_supplied = False
        match = _NEXTJS_DATA_PLACEHOLDER_RE.search(path)
        if match:
            token_name = match.group(1)
            if token_name and token_name.lower() in {"token", "build_id", "buildid"}:
                nextjs_token_name = token_name
                nextjs_token_user_supplied = token_name in arguments
                if not nextjs_token_user_supplied and token_name not in arguments:
                    # Prefer an explicit default build id from the action schema (captured value)
                    # to avoid probing HTML on hostile/bot-protected sites. If the default drifts,
                    # we refresh on-demand (retry once on 404).
                    default_token: str | None = None
                    schema = action.get("input_schema")
                    if isinstance(schema, dict):
                        props = schema.get("properties")
                        if isinstance(props, dict):
                            token_spec = props.get(token_name)
                            if isinstance(token_spec, dict):
                                raw_default = token_spec.get("default")
                                if isinstance(raw_default, str) and raw_default.strip():
                                    default_token = raw_default.strip()

                    if default_token is not None:
                        arguments = dict(arguments)
                        arguments[token_name] = default_token
                    else:
                        resolved = await self._resolve_nextjs_build_id(
                            action_host=action_host,
                            path_template=path,
                            params=arguments,
                        )
                        arguments = dict(arguments)
                        arguments[token_name] = resolved

        def build_url_and_kwargs(args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            url = urljoin(self.base_url, path) if self.base_url else f"https://{action_host}{path}"

            for param_name, param_value in args.items():
                placeholder = f"{{{param_name}}}"
                if placeholder in path:
                    url = url.replace(placeholder, str(param_value))

            headers: dict[str, str] = {"User-Agent": "Toolwright/1.0"}
            auth = self._resolve_auth_for_host(action_host)
            if auth:
                headers[self._resolve_auth_header_name(action_host)] = auth
            if self.extra_headers:
                headers.update(self.extra_headers)

            kwargs: dict[str, Any] = {"headers": headers, "follow_redirects": False}
            if method.upper() in ("POST", "PUT", "PATCH"):
                body_params = {k: v for k, v in args.items() if f"{{{k}}}" not in path}
                if body_params:
                    wrapper = action.get("request_body_wrapper")
                    if wrapper:
                        body_params = {wrapper: body_params}
                    headers["Content-Type"] = "application/json"
                    kwargs["json"] = body_params
            elif method.upper() in ("GET", "HEAD", "OPTIONS"):
                query_params = {k: v for k, v in args.items() if f"{{{k}}}" not in path}
                if query_params:
                    url = f"{url}?{urlencode(query_params)}"

            return url, kwargs

        async def fetch(url: str, kwargs: dict[str, Any]) -> tuple[httpx.Response, str]:
            client = await self._get_http_client()
            current_url = url

            for _ in range(4):
                validate_url_scheme(current_url)
                parsed = urlparse(current_url)
                target_host = parsed.hostname or action_host
                self._validate_host_allowlist(target_host, action_host)
                validate_network_target(target_host, self.allow_private_networks)

                response = await client.request(method.upper(), current_url, **kwargs)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        break
                    if not self.allow_redirects:
                        raise RuntimeBlockError(
                            ReasonCode.DENIED_REDIRECT_NOT_ALLOWLISTED,
                            f"Redirect blocked for {current_url} -> {location}",
                        )
                    next_url = urljoin(current_url, location)
                    validate_url_scheme(next_url)
                    next_host = urlparse(next_url).hostname
                    if not next_host:
                        raise RuntimeBlockError(
                            ReasonCode.DENIED_REDIRECT_NOT_ALLOWLISTED,
                            f"Redirect target '{location}' has no host",
                        )
                    self._validate_host_allowlist(next_host, action_host)
                    validate_network_target(next_host, self.allow_private_networks)
                    # Strip auth headers on cross-host redirects to prevent
                    # credential leaking to a different domain.
                    if next_host != target_host:
                        redirect_headers = dict(kwargs.get("headers", {}))
                        # Strip well-known auth headers
                        for hdr in ("Authorization", "authorization",
                                    "X-Api-Key", "x-api-key"):
                            redirect_headers.pop(hdr, None)
                        # Also strip any custom auth header configured for the
                        # original host (e.g. X-Custom-Token).
                        custom_hdr = self._resolve_auth_header_name(action_host)
                        if custom_hdr.lower() not in ("authorization",):
                            redirect_headers.pop(custom_hdr, None)
                            redirect_headers.pop(custom_hdr.lower(), None)
                        kwargs = {**kwargs, "headers": redirect_headers}
                    current_url = next_url
                    continue

                return response, target_host

            raise RuntimeBlockError(
                ReasonCode.DENIED_REDIRECT_NOT_ALLOWLISTED,
                "Maximum redirect hops exceeded",
            )

        response: httpx.Response
        target_host: str
        refreshed = False
        for _attempt in range(2):
            url, kwargs = build_url_and_kwargs(arguments)
            response, target_host = await fetch(url, kwargs)

            if (
                nextjs_token_name
                and not nextjs_token_user_supplied
                and not refreshed
                and response.status_code == 404
            ):
                try:
                    resolved = await self._resolve_nextjs_build_id(
                        action_host=action_host,
                        path_template=path,
                        params=arguments,
                    )
                except RuntimeBlockError:
                    break
                arguments = dict(arguments)
                arguments[nextjs_token_name] = resolved
                refreshed = True
                continue

            break

        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/octet-stream"):
            raise RuntimeBlockError(
                ReasonCode.DENIED_CONTENT_TYPE_NOT_ALLOWED,
                f"Blocked response content type: {content_type}",
            )

        # KILL pillar: response size limit
        raw_cl = response.headers.get("content-length")
        _check_response_size(
            content_length=int(raw_cl) if raw_cl else None,
            max_bytes=get_max_response_bytes(),
        )

        result: dict[str, Any] = {
            "status": "success",
            "status_code": response.status_code,
            "action": action["name"],
        }
        if "application/json" in content_type:
            try:
                result["data"] = response.json()
            except json.JSONDecodeError:
                result["data"] = response.text
        else:
            result["data"] = response.text

        self.audit_logger.log_enforce_decision(
            action_id=action["name"],
            endpoint_id=action.get("endpoint_id"),
            method=method,
            path=path,
            host=target_host,
            decision="allowed",
            confirmation_required=False,
        )
        return result

    async def run_stdio(self) -> None:
        async with mcp_stdio.stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="toolwright",
                    server_version="1.0.0",
                    capabilities=self.server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )

    def run_http(self, *, host: str = "127.0.0.1", port: int = 8745) -> None:
        """Start the HTTP transport (StreamableHTTP via Starlette/uvicorn)."""
        from toolwright.mcp.event_store import EventStore
        from toolwright.mcp.http_transport import ToolwrightHTTPApp

        # Create console EventStore in the state directory
        state_dir = Path(self.approval_root_path) / ".toolwright" / "state" / "console"
        console_event_store = EventStore(state_dir=state_dir)

        # Create TOOL_APPROVAL work items for pending tools
        self._create_startup_work_items(console_event_store)

        app = ToolwrightHTTPApp(
            self,
            host=host,
            port=port,
            console_event_store=console_event_store,
            confirmation_store=self.confirmation_store,
            lockfile_manager=self.lockfile_manager,
            circuit_breaker=self.circuit_breaker,
            rule_engine=self.rule_engine,
        )
        app.run()

    def _create_startup_work_items(self, event_store: Any) -> None:
        """Create TOOL_APPROVAL work items for pending tools at serve startup."""
        if self.lockfile_manager is None:
            return

        from toolwright.core.work_items import create_tool_approval_item

        lockfile = self.lockfile_manager.lockfile
        if lockfile is None:
            return

        for tool_id, tool in lockfile.tools.items():
            if tool.status == ApprovalStatus.PENDING:
                item = create_tool_approval_item(
                    tool_id=tool.tool_id or tool_id,
                    method=tool.method,
                    path=tool.path,
                    risk_tier=tool.risk_tier,
                    description=f"{tool.name} ({tool.host})",
                )
                event_store.publish_work_item(item)

    async def close(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None


def run_mcp_server(
    tools_path: str,
    toolsets_path: str | None = None,
    toolset_name: str | None = None,
    policy_path: str | None = None,
    lockfile_path: str | None = None,
    base_url: str | None = None,
    auth_header: str | None = None,
    audit_log: str | None = None,
    dry_run: bool = False,
    confirmation_store_path: str = ".toolwright/state/confirmations.db",
    allow_private_cidrs: list[str] | None = None,
    allow_redirects: bool = False,
    rules_path: str | None = None,
    circuit_breaker_path: str | None = None,
    watch: bool = False,
    watch_config_path: str | None = None,
    auto_heal_override: str | None = None,
    verbose_tools: bool = False,
    tool_filter: str | None = None,
    max_risk: str | None = None,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8745,
    extra_headers: dict[str, str] | None = None,
    schema_validation: str = "warn",
    scope: str | None = None,
    no_tool_limit: bool = False,
    shape_baselines_path: str | None = None,
    shape_probe_interval: int = 300,
    auth_requirements: list[ToolpackAuthRequirement] | None = None,
) -> None:
    """Run the Toolwright MCP server."""
    server = ToolwrightMCPServer(
        tools_path=tools_path,
        toolsets_path=toolsets_path,
        toolset_name=toolset_name,
        policy_path=policy_path,
        lockfile_path=lockfile_path,
        base_url=base_url,
        auth_header=auth_header,
        audit_log=audit_log,
        dry_run=dry_run,
        confirmation_store_path=confirmation_store_path,
        allow_private_cidrs=allow_private_cidrs,
        allow_redirects=allow_redirects,
        rules_path=rules_path,
        circuit_breaker_path=circuit_breaker_path,
        extra_headers=extra_headers,
        schema_validation=schema_validation,
        auth_requirements=auth_requirements,
    )

    # Context efficiency: apply tool filters and description mode
    server.compact_descriptions = not verbose_tools
    if tool_filter or max_risk:
        from toolwright.mcp.description import filter_actions

        server.actions = filter_actions(
            server.actions, tools_glob=tool_filter, max_risk=max_risk
        )
        server.pipeline.actions = server.actions

    # Scope filtering (requires groups.json from compile output)
    groups_index = None
    groups_json_path = Path(tools_path).parent / "groups.json"
    if groups_json_path.exists():
        from toolwright.core.compile.grouper import load_groups_index

        groups_index = load_groups_index(groups_json_path)

    if scope:
        if groups_index is None:
            import click as _click

            from toolwright.utils.text import pluralize

            _click.echo(
                "Warning: No tool groups found. Run 'toolwright compile' to generate groups.\n"
                f"Serving all {pluralize(len(server.actions), 'tool')}.",
                err=True,
            )
        else:
            import click as _click

            from toolwright.core.compile.grouper import filter_by_scope

            try:
                # filter_by_scope expects list[dict], server.actions is dict[str, dict]
                filtered_list = filter_by_scope(
                    list(server.actions.values()), scope, groups_index
                )
                server.actions = {a["name"]: a for a in filtered_list}
                server.pipeline.actions = server.actions
            except ValueError as exc:
                _click.echo(f"Error: {exc}", err=True)
                sys.exit(1)

    # Tool count guardrails
    import click as _click

    from toolwright.mcp.runtime import check_tool_count_guardrails

    tool_count = len(server.actions)
    guardrail_warnings, should_block = check_tool_count_guardrails(
        tool_count, groups_index=groups_index, no_tool_limit=no_tool_limit, scope=scope,
    )
    for warning in guardrail_warnings:
        _click.echo(f"  {warning}", err=True)
    if should_block:
        sys.exit(1)

    from toolwright.mcp.runtime import check_jsonschema_available

    jsonschema_warning = check_jsonschema_available()
    if jsonschema_warning:
        _click.echo(f"  WARNING: {jsonschema_warning}", err=True)

    reconcile_loop = None
    shape_probe_loop = None
    if watch:
        from toolwright.core.reconcile.loop import ReconcileLoop
        from toolwright.models.reconcile import WatchConfig

        tools_dir = Path(tools_path).resolve().parent
        project_root = str(tools_dir)

        config_path = watch_config_path or str(tools_dir / ".toolwright" / "watch.yaml")
        config = WatchConfig.from_yaml(config_path)

        if auto_heal_override is not None:
            from toolwright.models.reconcile import AutoHealPolicy
            config.auto_heal = AutoHealPolicy(auto_heal_override)

        actions = list(server.actions.values())
        risk_tiers = {a["name"]: "medium" for a in actions}

        reconcile_loop = ReconcileLoop(
            project_root=project_root,
            actions=actions,
            risk_tiers=risk_tiers,
            config=config,
            breaker_registry=server.circuit_breaker,
        )

        # Shape probe loop: autonomous drift detection via probe templates
        if shape_baselines_path:
            from toolwright.core.drift.shape_probe_loop import ShapeProbeLoop
            from toolwright.models.baseline import BaselineIndex

            sb_path = Path(shape_baselines_path)
            if sb_path.exists():
                baseline_index = BaselineIndex.load(sb_path)
                if baseline_index.baselines:
                    # Extract host from first action (all actions share the same API host)
                    first_action = actions[0] if actions else {}
                    probe_host = str(first_action.get("host", ""))

                    events_path = Path(project_root) / ".toolwright" / "state" / "drift_events.jsonl"

                    shape_probe_loop = ShapeProbeLoop(
                        baseline_index=baseline_index,
                        baselines_path=sb_path,
                        events_path=events_path,
                        host=probe_host,
                        auth_header=auth_header,
                        extra_headers=extra_headers,
                        base_url=base_url,
                        probe_interval=shape_probe_interval,
                    )
                    _click.echo(
                        f"  Shape probes: {len(baseline_index.baselines)} tools, "
                        f"interval={shape_probe_interval}s",
                        err=True,
                    )
                else:
                    _click.echo("  WARNING: shape_baselines.json has no baselines", err=True)
            else:
                _click.echo(f"  WARNING: shape baselines not found: {sb_path}", err=True)

    if transport == "http":
        # HTTP transport runs its own event loop via uvicorn
        server.run_http(host=host, port=port)
    else:
        from toolwright.mcp.runtime import stdio_transport_warning

        _click.echo(f"  {stdio_transport_warning()}", err=True)
        async def main() -> None:
            shape_probe_task: asyncio.Task[None] | None = None
            try:
                if reconcile_loop is not None:
                    await reconcile_loop.start()
                    logger.info("Reconciliation loop started (watch mode)")
                if shape_probe_loop is not None:
                    shape_probe_task = asyncio.create_task(
                        _run_shape_probe_loop(shape_probe_loop, shape_probe_interval)
                    )
                    logger.info("Shape probe loop started")
                await server.run_stdio()
            finally:
                if shape_probe_task is not None:
                    shape_probe_task.cancel()
                    with __import__("contextlib").suppress(asyncio.CancelledError):
                        await shape_probe_task
                    logger.info("Shape probe loop stopped")
                if reconcile_loop is not None:
                    await reconcile_loop.stop()
                    logger.info("Reconciliation loop stopped")
                await server.close()

        asyncio.run(main())


async def _run_shape_probe_loop(
    loop: object,
    interval: int,
) -> None:
    """Run shape probe cycles at the given interval until cancelled."""
    from toolwright.core.drift.shape_probe_loop import ShapeProbeLoop

    assert isinstance(loop, ShapeProbeLoop)
    while True:
        try:
            await loop.probe_cycle()
        except Exception:
            logger.exception("Shape probe cycle error")
        await asyncio.sleep(interval)
