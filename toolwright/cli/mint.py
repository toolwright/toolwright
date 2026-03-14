"""Mint command implementation (capture -> compile -> toolpack)."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
import httpx

from toolwright import __version__
from toolwright.cli.approve import sync_lockfile
from toolwright.cli.compile import compile_capture_session
from toolwright.cli.playwright_errors import emit_playwright_error, emit_playwright_missing_package
from toolwright.core.capture.redactor import Redactor
from toolwright.core.runtime.container import DEFAULT_BASE_IMAGE, emit_container_runtime
from toolwright.core.toolpack import (
    Toolpack,
    ToolpackContainerRuntime,
    ToolpackOrigin,
    ToolpackPaths,
    ToolpackRuntime,
    write_toolpack,
)
from toolwright.models.capture import CaptureSource, HttpExchange, HTTPMethod
from toolwright.storage import Storage
from toolwright.utils.config import build_mcp_config_payload
from toolwright.utils.runtime import is_stable_release
from toolwright.utils.schema_version import resolve_generated_at

# ---------------------------------------------------------------------------
# Result types for auto-approve and rules helpers
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class AutoApproveResult:
    """Summary of auto-approval via smart gate."""

    approved_count: int = 0
    pending_count: int = 0


@dataclasses.dataclass
class DefaultRulesResult:
    """Summary of default rule template application."""

    rule_count: int = 0
    template_name: str = ""


# ---------------------------------------------------------------------------
# Helper functions for mint UX
# ---------------------------------------------------------------------------


def format_capture_message(allowed_hosts: list[str]) -> str:
    """Return the capture progress message with host names."""
    hosts = ", ".join(allowed_hosts) if allowed_hosts else "target"
    return f"  Capturing traffic from {hosts}... Browse normally, then close the browser when done."


def build_scope_warning(
    tool_count: int,
    *,
    groups_index: Any | None,
    toolpack_id: str,  # noqa: ARG001 — reserved for future use in scope warnings
) -> str:
    """Build a scope warning message when tool count exceeds agent-friendly limits.

    Returns an empty string when tool_count <= 30.
    Otherwise returns a multi-line warning with actionable --scope guidance.
    """
    from toolwright.mcp.runtime import TOOL_COUNT_WARN_THRESHOLD

    if tool_count <= TOOL_COUNT_WARN_THRESHOLD:
        return ""

    lines: list[str] = []
    lines.append("")
    lines.append(
        click.style(
            f"  \u26a0 Tool count ({tool_count}) exceeds agent-friendly limits "
            f"(recommended: \u2264{TOOL_COUNT_WARN_THRESHOLD})",
            fg="yellow",
        )
    )

    # Build --scope examples from group data
    has_groups = False
    if groups_index is not None:
        from toolwright.models.groups import ToolGroupIndex

        if isinstance(groups_index, ToolGroupIndex) and groups_index.groups:
            has_groups = True
            top = sorted(
                groups_index.groups, key=lambda g: len(g.tools), reverse=True
            )
            if len(top) >= 2:
                combo2_names = ",".join(g.name for g in top[:2])
                combo2_count = sum(len(g.tools) for g in top[:2])
                combo3_names = ",".join(g.name for g in top[:3]) if len(top) >= 3 else combo2_names
                combo3_count = sum(len(g.tools) for g in top[:3]) if len(top) >= 3 else combo2_count

                lines.append("")
                lines.append("  Serve a focused subset with --scope:")
                lines.append(
                    f"    toolwright serve --scope {combo2_names}"
                    f"    # {combo2_count} tools"
                )
                if len(top) >= 3 and combo3_count != combo2_count:
                    lines.append(
                        f"    toolwright serve --scope {combo3_names}"
                        f"    # {combo3_count} tools"
                    )
            else:
                g = top[0]
                lines.append("")
                lines.append("  Serve a focused subset with --scope:")
                lines.append(
                    f"    toolwright serve --scope {g.name}"
                    f"    # {len(g.tools)} tools"
                )

    if not has_groups:
        lines.append("")
        lines.append("  Use --scope when serving to narrow to useful tool groups.")

    lines.append("")
    lines.append("  See all groups: toolwright groups list --toolpack <path-to-toolpack.yaml>")

    return "\n".join(lines)


def format_example_tool(tool: dict[str, Any]) -> str:
    """Format a single tool for display as an example."""
    name = tool.get("name", "unknown")
    method = tool.get("method", "GET")
    path = tool.get("path", "/")
    schema = tool.get("input_schema", {})
    props = schema.get("properties", {})

    lines = [
        "\n  Example tool:",
        f"    {name}  {method} {path}",
    ]

    if props:
        param_parts = []
        for pname, pinfo in list(props.items())[:5]:
            ptype = pinfo.get("type", "string")
            param_parts.append(f"{pname}: {ptype}")
        lines.append(f"    Parameters: {', '.join(param_parts)}")

    return "\n".join(lines)


def auto_approve_lockfile(lockfile_path: Path) -> AutoApproveResult:
    """Auto-approve low/medium risk tools using smart gate classification.

    Returns counts of approved and still-pending tools.
    """
    from toolwright.core.approval import LockfileManager
    from toolwright.core.approval.smart_gate import classify_approval

    manager = LockfileManager(lockfile_path)
    manager.load()
    assert manager.lockfile is not None

    approved = 0
    pending = 0

    for tool_id, tool in manager.lockfile.tools.items():
        if tool.status.value != "pending":
            continue
        classification = classify_approval(tool.risk_tier)
        if classification.auto_approve:
            manager.approve(
                tool_id,
                approved_by=classification.approved_by,
                reason="auto-approved by risk policy",
            )
            approved += 1
        else:
            pending += 1

    manager.save()
    return AutoApproveResult(approved_count=approved, pending_count=pending)


def apply_default_rules(
    *,
    rules_path: Path,
    apply_rules: bool = True,
    template_name: str = "crud-safety",
) -> DefaultRulesResult:
    """Apply default rule template (crud-safety) to the toolpack.

    Returns count of rules created.
    """
    if not apply_rules:
        return DefaultRulesResult(rule_count=0, template_name="")

    from toolwright.rules.loader import apply_template

    try:
        created = apply_template(template_name, rules_path=rules_path)
        return DefaultRulesResult(
            rule_count=len(created),
            template_name=template_name,
        )
    except ValueError:
        return DefaultRulesResult(rule_count=0, template_name=template_name)


def run_mint(
    *,
    start_url: str,
    allowed_hosts: list[str],
    name: str | None,
    scope_name: str,
    headless: bool,
    script_path: str | None,
    duration_seconds: int,
    output_root: str,
    deterministic: bool,
    print_mcp_config: bool,
    runtime_mode: str = "local",
    runtime_build: bool = False,
    runtime_tag: str | None = None,
    runtime_version_pin: str | None = None,
    auth_profile: str | None = None,
    webmcp: bool = False,
    redaction_profile: str | None = None,
    verbose: bool,
    extra_headers: dict[str, str] | None = None,
    no_probe: bool = False,
    recipe: str | None = None,
    auto_approve: bool = False,
    apply_rules: bool = True,
) -> None:
    """Mint a first-class toolpack from browser traffic capture."""
    if script_path and not Path(script_path).exists():
        click.echo(f"Error: Script not found: {script_path}", err=True)
        sys.exit(1)

    if duration_seconds <= 0:
        click.echo("Error: --duration must be > 0", err=True)
        sys.exit(1)

    if runtime_mode != "container" and (
        runtime_build or runtime_tag or runtime_version_pin
    ):
        click.echo("Error: runtime flags require --runtime=container", err=True)
        sys.exit(1)

    # Phase 3.1 (V-004): Validate URL before Playwright to avoid 60s hangs
    from urllib.parse import urlparse

    parsed = urlparse(start_url)
    if not parsed.scheme or not parsed.netloc:
        click.echo(
            f"Error: Invalid URL '{start_url}'. "
            "Expected format: https://app.example.com",
            err=True,
        )
        sys.exit(1)

    # Phase 3.2 (V-005): Strip protocol prefixes from allowed hosts
    cleaned_hosts: list[str] = []
    for h in allowed_hosts:
        h = h.strip()
        if not h:
            continue
        if "://" in h:
            parsed_host = urlparse(h).netloc or h
            click.echo(
                f"Warning: Stripped protocol from allowed host — using '{parsed_host}'",
                err=True,
            )
            h = parsed_host
        cleaned_hosts.append(h)
    allowed_hosts = cleaned_hosts

    try:
        from toolwright.core.capture.playwright_capture import PlaywrightCapture
    except ImportError:
        emit_playwright_missing_package()
        sys.exit(1)

    click.echo(f"Minting toolpack from {start_url}...")
    if script_path:
        click.echo(f"  Capturing traffic (scripted: {Path(script_path).name})...")
    else:
        click.echo(format_capture_message(allowed_hosts))
    if verbose:
        click.echo(f"  Allowed hosts: {', '.join(allowed_hosts)}")
        click.echo(f"  Headless: {headless}")
        if webmcp:
            click.echo("  WebMCP discovery: enabled")

    # Smart pre-flight probe: auth detection, GraphQL, OpenAPI (advisory only)
    if not no_probe:
        _smart_probe(allowed_hosts, start_url)

    # Resolve auth profile to storage_state path if provided
    storage_state_path: str | None = None
    if auth_profile:
        from toolwright.core.auth.profiles import AuthProfileManager

        auth_manager = AuthProfileManager(Path(output_root))
        state_path = auth_manager.get_storage_state_path(auth_profile)
        if state_path is None:
            click.echo(f"Error: Auth profile '{auth_profile}' not found.", err=True)
            click.echo(f"  Run: toolwright auth login --profile {auth_profile} --url {start_url}", err=True)
            sys.exit(1)
        storage_state_path = str(state_path)
        if verbose:
            click.echo(f"  Auth profile: {auth_profile}")
        auth_manager.update_last_used(auth_profile)

    capture = PlaywrightCapture(
        allowed_hosts=allowed_hosts,
        headless=headless,
        storage_state_path=storage_state_path,
    )
    try:
        session = asyncio.run(
            capture.capture(
                start_url=start_url,
                name=name,
                duration_seconds=duration_seconds if not script_path else None,
                script_path=script_path,
                settle_delay_seconds=1.0 if script_path else 0.0,
            )
        )
    except KeyboardInterrupt:
        click.echo("\nMint interrupted.")
        sys.exit(0)
    except Exception as exc:
        emit_playwright_error(exc, verbose=verbose, operation="capture")
        sys.exit(1)

    click.echo(f"  Captured {len(session.exchanges)} API calls from {len(session.allowed_hosts)} host(s).")

    if webmcp:
        webmcp_exchanges = discover_webmcp_exchanges(
            start_url=start_url,
            headless=headless,
            verbose=verbose,
        )
        if webmcp_exchanges:
            session.exchanges.extend(webmcp_exchanges)
            session.total_requests = len(session.exchanges)
            webmcp_hosts = {exchange.host for exchange in webmcp_exchanges if exchange.host}
            if webmcp_hosts:
                session.allowed_hosts = sorted(set(session.allowed_hosts + list(webmcp_hosts)))
            if verbose:
                click.echo(f"  WebMCP tools discovered: {len(webmcp_exchanges)}")
        elif verbose:
            click.echo("  WebMCP tools discovered: 0")

    redactor_profile = None
    if redaction_profile:
        from toolwright.core.capture.redaction_profiles import get_profile

        redactor_profile = get_profile(redaction_profile)
        if verbose:
            click.echo(f"  Redaction profile: {redaction_profile}")

    redactor = Redactor(profile=redactor_profile)
    session = redactor.redact_session(session)

    # Auth detection
    from toolwright.core.auth.detector import detect_auth_requirements

    auth_req = detect_auth_requirements(session)
    auth_requirements_list = None

    if auth_req.requires_auth and not auth_profile:
        click.echo(click.style("\nAuth detection:", fg="yellow"))
        for ev in auth_req.evidence:
            click.echo(f"  {ev}")
        if auth_req.suggestion:
            click.echo(f"  Suggestion: {auth_req.suggestion}")
        click.echo()

    output_base = Path(output_root)

    from toolwright.utils.state import warn_if_sandboxed_path

    warn_if_sandboxed_path(output_base)

    storage = Storage(base_path=output_base)
    capture_path = storage.save_capture(session)

    click.echo("  Compiling artifacts...")

    try:
        compile_result = compile_capture_session(
            session=session,
            scope_name=scope_name,
            scope_file=None,
            output_format="all",
            output_dir=output_base / "artifacts",
            deterministic=deterministic,
            verbose=verbose,
        )
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not compile_result.tools_path or not compile_result.toolsets_path:
        click.echo("Error: compile did not produce required tools/toolsets artifacts", err=True)
        sys.exit(1)
    if not compile_result.policy_path or not compile_result.baseline_path:
        click.echo("Error: compile did not produce required policy/baseline artifacts", err=True)
        sys.exit(1)

    click.echo("  Packaging toolpack...")

    effective_allowed_hosts = sorted(set(session.allowed_hosts or allowed_hosts))

    # Build auth requirements from detection results
    from toolwright.core.toolpack import build_auth_requirements

    auth_requirements_list = build_auth_requirements(
        hosts=effective_allowed_hosts,
        auth_type=auth_req.auth_type if auth_req.requires_auth else "none",
    )

    # Enrich auth requirements with recipe-specific header names
    if recipe:
        from fnmatch import fnmatch

        from toolwright.recipes.loader import load_recipe as _load_recipe_auth

        _recipe_data = _load_recipe_auth(recipe)
        for recipe_host in _recipe_data.get("hosts", []):
            custom_header = recipe_host.get("auth_header_name")
            if custom_header:
                for ar in auth_requirements_list:
                    if fnmatch(ar.host, recipe_host["pattern"]):
                        ar.header_name = custom_header

    from toolwright.utils.resolve import generate_toolpack_slug

    toolpack_id = generate_toolpack_slug(
        allowed_hosts=effective_allowed_hosts,
        root=output_base,
    )
    toolpack_dir = output_base / "toolpacks" / toolpack_id
    artifact_dir = toolpack_dir / "artifact"
    lockfile_dir = toolpack_dir / "lockfile"
    toolpack_dir.mkdir(parents=True, exist_ok=True)
    lockfile_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(compile_result.output_path, artifact_dir, dirs_exist_ok=True)

    copied_tools = artifact_dir / "tools.json"
    copied_toolsets = artifact_dir / "toolsets.yaml"
    copied_policy = artifact_dir / "policy.yaml"
    copied_baseline = artifact_dir / "baseline.json"
    copied_groups = artifact_dir / "groups.json"
    copied_contracts = artifact_dir / "contracts.yaml"
    copied_contract_yaml = artifact_dir / "contract.yaml"
    copied_contract_json = artifact_dir / "contract.json"

    pending_lockfile = lockfile_dir / "toolwright.lock.pending.yaml"
    sync_result = sync_lockfile(
        tools_path=str(copied_tools),
        policy_path=str(copied_policy),
        toolsets_path=str(copied_toolsets),
        lockfile_path=str(pending_lockfile),
        capture_id=session.id,
        scope=scope_name,
        deterministic=deterministic,
    )

    # Smart gate auto-approval (only if flag is set)
    gate_result: AutoApproveResult | None = None
    if auto_approve:
        gate_result = auto_approve_lockfile(pending_lockfile)

    approved_lockfile = lockfile_dir / "toolwright.lock.yaml"
    lockfiles: dict[str, str] = {
        "pending": str(pending_lockfile.relative_to(toolpack_dir)),
    }
    if approved_lockfile.exists():
        lockfiles["approved"] = str(approved_lockfile.relative_to(toolpack_dir))

    runtime = _build_runtime(
        toolpack_id=toolpack_id,
        mode=runtime_mode,
        tag=runtime_tag,
    )

    toolpack = Toolpack(
        toolpack_id=toolpack_id,
        created_at=resolve_generated_at(
            deterministic=deterministic,
            candidate=session.created_at if deterministic else None,
        ),
        capture_id=session.id,
        artifact_id=compile_result.artifact_id,
        scope=scope_name,
        allowed_hosts=effective_allowed_hosts,
        display_name=name,
        origin=ToolpackOrigin(start_url=start_url, name=name),
        paths=ToolpackPaths(
            tools=str(copied_tools.relative_to(toolpack_dir)),
            toolsets=str(copied_toolsets.relative_to(toolpack_dir)),
            policy=str(copied_policy.relative_to(toolpack_dir)),
            baseline=str(copied_baseline.relative_to(toolpack_dir)),
            contracts=(
                str(copied_contracts.relative_to(toolpack_dir))
                if copied_contracts.exists()
                else None
            ),
            contract_yaml=(
                str(copied_contract_yaml.relative_to(toolpack_dir))
                if copied_contract_yaml.exists()
                else None
            ),
            contract_json=(
                str(copied_contract_json.relative_to(toolpack_dir))
                if copied_contract_json.exists()
                else None
            ),
            groups=(
                str(copied_groups.relative_to(toolpack_dir))
                if copied_groups.exists()
                else None
            ),
            lockfiles=lockfiles,
        ),
        runtime=runtime,
        auth_requirements=auth_requirements_list if auth_requirements_list else None,
        extra_headers=extra_headers,
    )

    toolpack_file = toolpack_dir / "toolpack.yaml"
    write_toolpack(toolpack, toolpack_file)

    # Post-mint: apply recipe rule templates as DRAFT
    if recipe:
        from toolwright.recipes.loader import load_recipe as _load_recipe_rules

        recipe_data = _load_recipe_rules(recipe)
        if recipe_data.get("rule_templates"):
            from toolwright.rules.loader import apply_template

            rules_path = Path(output_root) / ".toolwright" / "rules.json"
            for tmpl_name in recipe_data["rule_templates"]:
                try:
                    created = apply_template(tmpl_name, rules_path=rules_path)
                    click.echo(
                        f"  Applied rule template '{tmpl_name}': {len(created)} DRAFT rules",
                        err=True,
                    )
                except ValueError:
                    pass  # Unknown template -- skip silently

    # Apply default behavioral rules (crud-safety) unless disabled or recipe already applied
    rules_result: DefaultRulesResult | None = None
    if apply_rules and not recipe:
        rules_path = toolpack_dir / "rules.json"
        rules_result = apply_default_rules(rules_path=rules_path)
        if rules_result.rule_count > 0:
            click.echo(f"  Applied default rules '{rules_result.template_name}': {rules_result.rule_count} rules")

    if runtime_mode == "container" and runtime is not None:
        if runtime.container is None:
            click.echo("Error: runtime container configuration missing", err=True)
            sys.exit(1)
        try:
            requirements_line = _resolve_requirements_pin(runtime_version_pin)
        except ValueError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        try:
            emit_container_runtime(
                toolpack_dir=toolpack_dir,
                image=runtime.container.image,
                base_image=runtime.container.base_image,
                requirements_line=requirements_line,
                env_allowlist=runtime.container.env_allowlist,
                healthcheck_cmd=runtime.container.healthcheck.cmd,
                healthcheck_interval_s=runtime.container.healthcheck.interval_s,
                healthcheck_timeout_s=runtime.container.healthcheck.timeout_s,
                healthcheck_retries=runtime.container.healthcheck.retries,
                build=runtime_build,
            )
        except RuntimeError:
            click.echo("Error: docker not available (required for --build)", err=True)
            sys.exit(1)
        except subprocess.CalledProcessError as exc:
            click.echo("Error: docker build failed", err=True)
            if verbose:
                click.echo(exc.stderr or str(exc), err=True)
            sys.exit(1)

    click.echo(f"\nMint complete: {toolpack_id}")
    click.echo(f"  Capture: {session.id}")
    click.echo(f"  Capture location: {capture_path}")
    click.echo(f"  Artifact: {compile_result.artifact_id}")
    click.echo(f"  Toolpack: {toolpack_file}")

    # Show approval summary reflecting auto-approval
    if gate_result and gate_result.approved_count > 0:
        click.echo(f"  Auto-approved: {gate_result.approved_count} (low/medium risk)")
        if gate_result.pending_count > 0:
            click.echo(f"  Pending review: {gate_result.pending_count} (high/critical risk)")
    else:
        click.echo(f"  Pending approvals: {sync_result.pending_count}")

    # Show group summary if groups were generated
    if copied_groups.exists():
        from toolwright.core.compile.grouper import load_groups_index
        groups_idx = load_groups_index(copied_groups)
        if groups_idx and groups_idx.groups:
            total = sum(len(g.tools) for g in groups_idx.groups) + len(groups_idx.ungrouped)
            click.echo(f"\n  {total} tools in {len(groups_idx.groups)} groups")
            top = sorted(groups_idx.groups, key=lambda g: len(g.tools), reverse=True)[:8]
            parts_list = [f"{g.name} ({len(g.tools)})" for g in top]
            for j in range(0, len(parts_list), 4):
                row = "    ".join(f"{p:<20}" for p in parts_list[j : j + 4])
                click.echo(f"    {row}")
            if len(groups_idx.groups) > 8:
                click.echo(f"    ... ({len(groups_idx.groups) - 8} more)")
            click.echo(f"\n  Serve subset: toolwright serve --scope {top[0].name}")
            click.echo("  All groups:  toolwright groups list")

    # Show example tool
    if copied_tools.exists():
        tools_data = json.loads(copied_tools.read_text())
        actions = tools_data.get("actions", [])
        if actions:
            example = next((a for a in actions if a.get("method") == "GET"), actions[0])
            click.echo(format_example_tool(example))

    # Show auth setup info (only when auth was actually detected)
    if auth_requirements_list and any(ar.scheme != "none" for ar in auth_requirements_list):
        click.echo(click.style("\nAuth detected:", fg="cyan"))
        for ar in auth_requirements_list:
            if ar.scheme != "none":
                header_info = f" ({ar.header_name})" if ar.header_name else ""
                click.echo(f"  {ar.host} requires: {ar.scheme}{header_info}")
        click.echo("\nSet before serving:")
        for ar in auth_requirements_list:
            if ar.scheme != "none":
                click.echo(f'  export {ar.env_var_name}="Bearer <your-token>"')

    if extra_headers:
        click.echo(click.style("\nExtra headers stored in toolpack:", fg="cyan"))
        for hdr_name, hdr_value in extra_headers.items():
            click.echo(f"  {hdr_name}: {hdr_value}")

    click.echo("\nNext commands:")
    click.echo("  toolwright gate allow --all --toolset readonly")
    click.echo("  toolwright run                                   # production (with doctor check)")
    click.echo("  toolwright serve                                 # development (fine-grained control)")

    click.echo(build_mcp_integration_output(toolpack_path=toolpack_file))

    if print_mcp_config:
        click.echo("\nClaude Desktop MCP config:")
        click.echo(
            build_mcp_config_snippet(
                toolpack_path=toolpack_file,
                server_name=_server_name(name, toolpack_id),
            )
        )


def build_mcp_integration_output(toolpack_path: str | Path) -> str:
    """Return ready-to-paste MCP integration instructions.

    Primary: guide users to generate a config snippet via `toolwright config`.
    """
    tp = str(toolpack_path)
    return (
        "\nConnect to MCP clients:\n"
        "\n"
        "  Generate a ready-to-paste MCP config snippet:\n"
        f"    toolwright config --toolpack {tp}\n"
        "\n"
        "  Claude Desktop:\n"
        "    Paste the emitted JSON into:\n"
        "      ~/Library/Application Support/Claude/claude_desktop_config.json\n"
        "    under \"mcpServers\", then restart Claude Desktop.\n"
    )


def build_mcp_config_snippet(*, toolpack_path: Path, server_name: str) -> str:
    """Return a ready-to-paste Claude Desktop MCP config snippet."""
    payload = build_mcp_config_payload(
        toolpack_path=toolpack_path,
        server_name=server_name,
    )
    return json.dumps(payload, indent=2, sort_keys=True)


def discover_webmcp_exchanges(
    *,
    start_url: str,
    headless: bool,
    verbose: bool,
) -> list[HttpExchange]:
    """Discover WebMCP tools on the target page and convert them to exchanges."""

    async def _discover() -> list[HttpExchange]:
        from playwright.async_api import async_playwright

        from toolwright.core.capture.webmcp_capture import (
            discover_webmcp_tools,
            webmcp_tools_to_exchanges,
        )

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=headless)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(start_url, timeout=60000)
            tools = await discover_webmcp_tools(page, start_url)
            raw_exchanges = webmcp_tools_to_exchanges(tools, start_url)
            await browser.close()

        exchanges: list[HttpExchange] = []
        for raw in raw_exchanges:
            method_raw = str(raw.get("method", "GET")).upper()
            try:
                method = HTTPMethod(method_raw)
            except ValueError:
                method = HTTPMethod.GET
            raw_notes = raw.get("notes")
            notes: dict[str, object] = (
                raw_notes if isinstance(raw_notes, dict) else {}
            )
            exchange = HttpExchange(
                url=str(raw.get("url", start_url)),
                method=method,
                host=str(raw.get("host", "")),
                path=str(raw.get("path", "/")),
                request_headers={},
                response_status=int(raw.get("response_status", 200)),
                response_headers={},
                response_body_json=raw.get("response_body_json"),
                source=CaptureSource.WEBMCP,
                notes=notes,
            )
            exchanges.append(exchange)
        return exchanges

    try:
        return asyncio.run(_discover())
    except Exception as exc:
        if verbose:
            click.echo(f"  WebMCP discovery skipped: {exc}")
        return []


@dataclasses.dataclass
class ProbeResult:
    """Aggregated results from pre-mint smart probes."""

    # Base URL probe
    base_status: int | None = None
    auth_required: bool = False
    auth_scheme: str | None = None
    www_authenticate_raw: str | None = None

    # GraphQL probe
    graphql_detected: bool = False
    graphql_url: str | None = None

    # OpenAPI probe
    openapi_found: bool = False
    openapi_url: str | None = None

    # Per-host probes
    host_probes: dict[str, dict[str, object]] = dataclasses.field(
        default_factory=dict
    )


def _probe_client(
    *,
    timeout: float = 5.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    if transport is None:
        return httpx.AsyncClient(timeout=timeout)
    return httpx.AsyncClient(timeout=timeout, transport=transport)


async def _probe_base_url(
    start_url: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, object]:
    """Probe the start URL for auth requirements.

    Returns a dict of ProbeResult field updates.
    """
    try:
        async with _probe_client(transport=transport) as client:
            resp = await client.get(
                start_url, headers={"User-Agent": "toolwright-probe/1.0"}
            )
    except (httpx.HTTPError, OSError):
        return {}

    result: dict[str, object] = {"base_status": resp.status_code}
    if resp.status_code in (401, 403):
        result["auth_required"] = True
        www_auth = resp.headers.get("www-authenticate")
        if www_auth:
            result["www_authenticate_raw"] = www_auth
            result["auth_scheme"] = www_auth.split()[0]
    else:
        result["auth_required"] = False
    return result


_GRAPHQL_INTROSPECTION = '{"query":"{ __schema { queryType { name } } }"}'


async def _probe_graphql(
    start_url: str,
    allowed_hosts: list[str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, object]:
    """Probe for GraphQL endpoints via minimal introspection.

    Always probes {scheme}://{host}/graphql for each allowed host.
    Also probes start_url directly if its path contains 'graphql'.
    Returns a dict of ProbeResult field updates.
    """
    from urllib.parse import urlparse

    parsed = urlparse(start_url)

    # Build list of URLs to try (deduplicated)
    urls: list[str] = []
    # Probe start_url itself only if it contains graphql in path
    if "graphql" in parsed.path.lower():
        urls.append(start_url)
    # Always try {scheme}://{host}/graphql for each allowed host
    for host in allowed_hosts:
        proto = "http" if host.startswith(("localhost", "127.")) else "https"
        candidate = f"{proto}://{host}/graphql"
        if candidate not in urls:
            urls.append(candidate)

    try:
        async with _probe_client(transport=transport) as client:
            for url in urls:
                try:
                    resp = await client.post(
                        url,
                        content=_GRAPHQL_INTROSPECTION,
                        headers={
                            "Content-Type": "application/json",
                            "User-Agent": "toolwright-probe/1.0",
                        },
                    )
                except (httpx.HTTPError, OSError):
                    continue
                if resp.status_code == 200 and "__schema" in resp.text:
                    return {"graphql_detected": True, "graphql_url": url}
    except (httpx.HTTPError, OSError):
        pass
    return {}


async def _probe_hosts(
    start_url: str,
    allowed_hosts: list[str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, dict[str, object]]:
    """Probe each allowed host that differs from start_url's netloc.

    Returns a dict keyed by hostname with status, auth, content_type, and error info.
    """
    from urllib.parse import urlparse

    start_netloc = urlparse(start_url).netloc
    results: dict[str, dict[str, object]] = {}

    for host in allowed_hosts[:3]:
        if host == start_netloc:
            continue

        proto = "http" if host.startswith(("localhost", "127.")) else "https"
        url = f"{proto}://{host}/"
        entry: dict[str, object] = {
            "status": None,
            "auth_required": False,
            "auth_scheme": None,
            "content_type": None,
            "error": None,
        }
        try:
            async with _probe_client(transport=transport) as client:
                resp = await client.get(
                    url, headers={"User-Agent": "toolwright-probe/1.0"}
                )
            entry["status"] = resp.status_code

            # Content-Type classification
            ct = resp.headers.get("content-type", "")
            if "application/json" in ct:
                entry["content_type"] = "json"
            elif "text/html" in ct:
                entry["content_type"] = "html"
            else:
                entry["content_type"] = "other"

            # Auth detection
            if resp.status_code in (401, 403):
                entry["auth_required"] = True
                www_auth = resp.headers.get("www-authenticate")
                if www_auth:
                    entry["auth_scheme"] = www_auth.split()[0]
        except httpx.ReadTimeout:
            entry["error"] = "timeout"
        except httpx.ConnectError:
            entry["error"] = "unreachable"
        except (httpx.HTTPError, OSError):
            entry["error"] = "network_error"

        results[host] = entry

    return results


async def _probe_openapi(
    allowed_hosts: list[str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, object]:
    """Probe allowed hosts for OpenAPI specs at well-known paths.

    Lightweight: checks for 200 status only, does not parse the spec.
    Returns a dict of ProbeResult field updates.
    """
    from toolwright.core.discover.openapi import OpenAPIDiscovery

    try:
        async with _probe_client(transport=transport) as client:
            for host in allowed_hosts[:2]:
                proto = "http" if host.startswith(("localhost", "127.")) else "https"
                base = f"{proto}://{host}"
                for path in OpenAPIDiscovery.WELL_KNOWN_PATHS:
                    url = f"{base}{path}"
                    try:
                        resp = await client.get(url)
                    except (httpx.HTTPError, OSError):
                        continue
                    if resp.status_code == 200:
                        return {"openapi_found": True, "openapi_url": url}
    except (httpx.HTTPError, OSError):
        pass
    return {}


async def _smart_probe_async(
    start_url: str,
    allowed_hosts: list[str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ProbeResult:
    """Run all probes concurrently, merge results."""
    base_r, gql_r, openapi_r, hosts_r = await asyncio.gather(
        _probe_base_url(start_url, transport=transport),
        _probe_graphql(start_url, allowed_hosts[:2], transport=transport),
        _probe_openapi(allowed_hosts[:2], transport=transport),
        _probe_hosts(start_url, allowed_hosts[:3], transport=transport),
        return_exceptions=True,
    )

    result = ProbeResult()
    for partial in (base_r, gql_r, openapi_r):
        if isinstance(partial, dict):
            for k, v in partial.items():
                setattr(result, k, v)
    if isinstance(hosts_r, dict):
        result.host_probes = hosts_r
    return result


def _render_probe_results(
    result: ProbeResult,
    start_url: str,
    allowed_hosts: list[str],
) -> None:
    """Render structured advisory messages from probe results. Never blocks."""
    from urllib.parse import urlparse

    from toolwright.utils.auth import host_to_env_var as _host_to_env_var

    CHECK = "\u2713"
    WARN = "\u26A0"
    CROSS = "\u2717"
    EMPTY = "\u25CB"

    parsed = urlparse(start_url)
    primary_host = parsed.netloc or (allowed_hosts[0] if allowed_hosts else "unknown")
    hosts_str = " -a ".join(allowed_hosts) if allowed_hosts else primary_host
    lines: list[str] = []

    lines.append(f"\nProbing {primary_host}...")

    # Base URL status
    if result.base_status is not None:
        if result.auth_required:
            scheme_info = f": {result.auth_scheme}" if result.auth_scheme else ""
            env_var = _host_to_env_var(primary_host)
            if os.environ.get(env_var):
                lines.append(click.style(
                    f"  {WARN} {primary_host} \u2014 Auth required{scheme_info} ({result.base_status}) {CHECK} configured",
                    fg="yellow",
                ))
            else:
                lines.append(click.style(
                    f"  {WARN} {primary_host} \u2014 Auth required{scheme_info} ({result.base_status})",
                    fg="yellow",
                ))
                token_hint = f"{result.auth_scheme} <your-token>" if result.auth_scheme else "<your-token>"
                lines.append(f'    export {env_var}="{token_hint}"')
        else:
            lines.append(click.style(
                f"  {CHECK} Reachable ({result.base_status})",
                fg="green",
            ))

    # Per-host probe results
    for host, info in result.host_probes.items():
        error = info.get("error")
        if error == "timeout":
            lines.append(click.style(
                f"  {CROSS} {host} \u2014 connection timed out (5s)", fg="red",
            ))
            continue
        if error == "unreachable":
            lines.append(click.style(
                f"  {CROSS} {host} \u2014 unreachable", fg="red",
            ))
            continue
        if error:
            lines.append(click.style(
                f"  {CROSS} {host} \u2014 {error}", fg="red",
            ))
            continue

        status = info.get("status")
        ct = info.get("content_type")

        if info.get("auth_required"):
            scheme = info.get("auth_scheme")
            scheme_info = f": {scheme}" if scheme else ""
            env_var = _host_to_env_var(host)
            if os.environ.get(env_var):
                lines.append(click.style(
                    f"  {WARN} {host} \u2014 Auth required{scheme_info} ({status}) {CHECK} configured",
                    fg="yellow",
                ))
            else:
                lines.append(click.style(
                    f"  {WARN} {host} \u2014 Auth required{scheme_info} ({status})",
                    fg="yellow",
                ))
                token_hint = f"{scheme} <your-token>" if scheme else "<your-token>"
                lines.append(f'    export {env_var}="{token_hint}"')
        elif ct == "html":
            lines.append(click.style(
                f"  {WARN} {host} returned HTML (likely web portal, not API root)",
                fg="yellow",
            ))
        elif status is not None:
            lines.append(click.style(
                f"  {CHECK} {host} reachable ({status}, {ct or 'unknown'})",
                fg="green",
            ))

    # OpenAPI detection
    if result.openapi_found:
        lines.append(click.style(
            f"  {CHECK} OpenAPI spec found: {result.openapi_url}",
            fg="green",
        ))
    else:
        lines.append(click.style(
            f"  {EMPTY} No OpenAPI spec detected", fg="bright_black",
        ))

    # GraphQL detection
    if result.graphql_detected:
        lines.append(click.style(
            f"  {CHECK} GraphQL endpoint: {result.graphql_url}",
            fg="cyan",
        ))
        lines.append("  Note: GraphQL minting produces one coarse tool per endpoint.")
    else:
        lines.append(click.style(
            f"  {EMPTY} No GraphQL endpoint detected", fg="bright_black",
        ))

    # Suggestions
    if result.openapi_found:
        lines.append("")
        lines.append("Suggestion: import the OpenAPI spec for richer tool definitions:")
        lines.append(
            f"  toolwright capture import {result.openapi_url} -a {hosts_str}"
        )

    lines.append("")
    click.echo("\n".join(lines))


def _smart_probe(
    allowed_hosts: list[str],
    start_url: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Async smart probe with sync wrapper. Advisory only.

    Safe to call with asyncio.run() here -- the call site (mint.py)
    is before any event loop starts (Playwright capture starts later).
    """
    result = asyncio.run(
        _smart_probe_async(start_url, allowed_hosts, transport=transport)
    )
    _render_probe_results(result, start_url, allowed_hosts)


def _build_runtime(
    *,
    toolpack_id: str,
    mode: str,
    tag: str | None,
) -> ToolpackRuntime | None:
    if mode != "container":
        return ToolpackRuntime(mode=mode, container=None)
    image = tag or f"toolwright-toolpack:{toolpack_id}"
    container = ToolpackContainerRuntime(
        image=image,
        base_image=DEFAULT_BASE_IMAGE,
    )
    return ToolpackRuntime(mode=mode, container=container)


def _resolve_requirements_pin(runtime_version_pin: str | None) -> str:
    if runtime_version_pin:
        return runtime_version_pin
    if is_stable_release(__version__):
        return f"toolwright[mcp]=={__version__}"
    raise ValueError(
        "Runtime version pin required for pre-release builds. "
        "Pass --runtime-version-pin to toolwright mint."
    )


def _generate_toolpack_id(
    *,
    capture_id: str,
    artifact_id: str,
    scope_name: str,
    start_url: str,
    allowed_hosts: list[str],
    deterministic: bool,
) -> str:
    """Generate a deterministic or volatile toolpack id."""
    if deterministic:
        canonical = ":".join(
            [
                capture_id,
                artifact_id,
                scope_name,
                start_url,
                ",".join(sorted(set(allowed_hosts))),
            ]
        )
        digest = hashlib.sha256(canonical.encode()).hexdigest()[:12]
        return f"tp_{digest}"

    return f"tp_{datetime.now(UTC).strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"


def _server_name(name: str | None, toolpack_id: str) -> str:
    """Create a stable MCP server name from user input."""
    base = (name or toolpack_id).strip().lower().replace(" ", "_")
    sanitized = "".join(ch for ch in base if ch.isalnum() or ch in {"_", "-"})
    return sanitized or toolpack_id
