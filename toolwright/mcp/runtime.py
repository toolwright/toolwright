"""Runtime helpers and serve orchestration for Toolwright MCP servers."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import click

from toolwright.utils.deps import require_mcp_dependency

TOOL_COUNT_WARN_THRESHOLD = 30
TOOL_COUNT_BLOCK_THRESHOLD = 200


def check_tool_count_guardrails(
    tool_count: int,
    *,
    groups_index: Any | None,
    no_tool_limit: bool,
    scope: str | None = None,
) -> tuple[list[str], bool]:
    """Check tool count against safety thresholds.

    Returns (warning_messages, should_block).
    - 0-30 tools: no warnings
    - 31-200 tools: warning, server starts
    - 201+ tools: error + block (unless no_tool_limit overrides)
    """
    warnings: list[str] = []
    block = False

    if tool_count <= TOOL_COUNT_WARN_THRESHOLD:
        return warnings, block

    # Build group suggestion text (suppress if scope already specified)
    group_hint = ""
    if scope:
        pass  # Don't suggest --scope when it's already in use
    elif groups_index is not None:
        from toolwright.models.groups import ToolGroupIndex

        if isinstance(groups_index, ToolGroupIndex) and groups_index.groups:
            top = sorted(
                groups_index.groups, key=lambda g: len(g.tools), reverse=True
            )[:8]
            parts = [f"{g.name} ({len(g.tools)})" for g in top]
            group_hint = (
                "\n  Consider narrowing with --scope:\n    "
                + "    ".join(f"{p:<20}" for p in parts)
                + f"\n  Example: toolwright serve --scope {top[0].name}"
            )
        else:
            group_hint = "\n  Run 'toolwright compile' to generate tool groups, then use --scope to narrow."
    else:
        group_hint = "\n  Run 'toolwright compile' to generate tool groups, then use --scope to narrow."

    if tool_count > TOOL_COUNT_BLOCK_THRESHOLD:
        if no_tool_limit:
            warnings.append(
                f"Serving {tool_count} tools (--no-tool-limit override active). "
                f"Agent performance degrades above ~{TOOL_COUNT_WARN_THRESHOLD} tools."
                + group_hint
            )
        else:
            warnings.append(
                f"Refusing to serve {tool_count} tools. "
                f"Agents cannot reliably select from this many tools."
                + group_hint
            )
            block = True
    else:
        warnings.append(
            f"Serving {tool_count} tools. "
            f"Agent performance degrades above ~{TOOL_COUNT_WARN_THRESHOLD} tools."
            + group_hint
        )

    return warnings, block


def stdio_transport_warning() -> str:
    """Return a one-line warning about stdio mode being local-only."""
    return (
        "Running in stdio mode (local only). "
        "Use --http for networked/production deployments."
    )


def check_jsonschema_available() -> str | None:
    """Return a warning if jsonschema is not installed, None otherwise."""
    if importlib.util.find_spec("jsonschema") is not None:
        return None
    return (
        "jsonschema not installed — input validation disabled. "
        "Install with: pip install jsonschema"
    )


def warn_missing_auth(
    tools_path: str | Path,
    auth_header: str | None,
) -> list[str]:
    """Check for missing auth env vars and return warning messages.

    Returns a list of warning strings for hosts without auth configuration.
    """
    if auth_header:
        return []

    path = Path(tools_path)
    if not path.exists():
        return []

    with open(path) as f:
        manifest = json.load(f)

    hosts = manifest.get("allowed_hosts", [])
    warnings: list[str] = []
    for host in hosts:
        normalized = re.sub(r"[^A-Za-z0-9]", "_", host).upper()
        env_key = f"TOOLWRIGHT_AUTH_{normalized}"
        if not os.environ.get(env_key):
            warnings.append(
                f"No auth configured for {host}. "
                f'Set: export {env_key}="Bearer <token>"'
            )
    return warnings


def run_mcp_serve(
    tools_path: str | None,
    toolpack_path: str | None,
    toolsets_path: str | None,
    toolset_name: str | None,
    policy_path: str | None,
    lockfile_path: str | None,
    base_url: str | None,
    auth_header: str | None,
    audit_log: str | None,
    dry_run: bool,
    confirmation_store_path: str,
    allow_private_cidrs: list[str],
    allow_redirects: bool,
    verbose: bool,
    unsafe_no_lockfile: bool = False,
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
) -> None:
    """Run the MCP server command."""
    resolved_toolpack = None
    resolved_toolpack_paths = None
    if toolpack_path:
        from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

        try:
            resolved_toolpack = load_toolpack(toolpack_path)
            resolved_toolpack_paths = resolve_toolpack_paths(
                toolpack=resolved_toolpack,
                toolpack_path=toolpack_path,
            )
        except (FileNotFoundError, ValueError) as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

        from toolwright.utils.state import warn_if_sandboxed_path

        warn_if_sandboxed_path(Path(toolpack_path))

    resolved_tools_path = Path(tools_path) if tools_path else None
    if resolved_tools_path is None and resolved_toolpack_paths is not None:
        resolved_tools_path = resolved_toolpack_paths.tools_path

    if resolved_tools_path is None:
        click.echo("Error: Provide --tools or --toolpack.", err=True)
        sys.exit(1)
    if not resolved_tools_path.exists():
        click.echo(f"Error: Tools manifest not found: {resolved_tools_path}", err=True)
        sys.exit(1)

    resolved_policy_path: Path | None = None
    if policy_path:
        resolved_policy_path = Path(policy_path)
    elif resolved_toolpack_paths is not None:
        resolved_policy_path = resolved_toolpack_paths.policy_path

    # Validate policy file if provided
    if resolved_policy_path and not resolved_policy_path.exists():
        click.echo(f"Error: Policy file not found: {resolved_policy_path}", err=True)
        sys.exit(1)

    require_mcp_dependency()

    resolved_toolsets_path: Path | None = None
    if toolsets_path:
        resolved_toolsets_path = Path(toolsets_path)
    elif resolved_toolpack_paths is not None:
        resolved_toolsets_path = resolved_toolpack_paths.toolsets_path
    else:
        candidate = resolved_tools_path.parent / "toolsets.yaml"
        if candidate.exists():
            resolved_toolsets_path = candidate

    if toolset_name and (resolved_toolsets_path is None or not resolved_toolsets_path.exists()):
        click.echo(
            "Error: Toolset selection requires a toolsets artifact. "
            "Pass --toolsets <path> or compile artifacts including toolsets.yaml.",
            err=True,
        )
        sys.exit(1)

    effective_toolset = toolset_name
    if effective_toolset is None and resolved_toolsets_path and resolved_toolsets_path.exists():
        effective_toolset = "readonly"
        if verbose:
            click.echo(
                "Defaulting to toolset readonly. Use --toolset <name> to change.",
                err=True,
            )

    resolved_lockfile_path: Path | None = None
    if lockfile_path:
        resolved_lockfile_path = Path(lockfile_path)
    elif resolved_toolpack_paths is not None:
        toolpack_root = Path(toolpack_path).resolve().parent if toolpack_path else None
        lockfile_candidates: list[Path] = []
        if resolved_toolpack_paths.approved_lockfile_path is not None:
            lockfile_candidates.append(resolved_toolpack_paths.approved_lockfile_path)
        if toolpack_root is not None:
            lockfile_candidates.extend(
                [
                    toolpack_root / "lockfile" / "toolwright.lock.approved.yaml",
                    toolpack_root / "lockfile" / "toolwright.lock.yaml",
                ]
            )
        for candidate in lockfile_candidates:
            if candidate.exists():
                resolved_lockfile_path = candidate
                break
        if (
            not unsafe_no_lockfile
            and resolved_lockfile_path is None
            and resolved_toolpack_paths.pending_lockfile_path
            and resolved_toolpack_paths.pending_lockfile_path.exists()
        ):
            resolved_lockfile_path = resolved_toolpack_paths.pending_lockfile_path

    if resolved_lockfile_path and not resolved_lockfile_path.exists():
        click.echo(f"Error: Lockfile not found: {resolved_lockfile_path}", err=True)
        sys.exit(1)

    if not unsafe_no_lockfile:
        if resolved_lockfile_path is None:
            if (
                resolved_toolpack is not None
                and resolved_toolpack.paths.lockfiles.get("pending")
            ):
                pending_ref = resolved_toolpack.paths.lockfiles["pending"]
                if resolved_toolpack_paths and resolved_toolpack_paths.pending_lockfile_path:
                    pending_abs = resolved_toolpack_paths.pending_lockfile_path
                elif toolpack_path:
                    pending_abs = Path(toolpack_path).parent / pending_ref
                else:
                    pending_abs = Path(pending_ref)
                # Approved path: same name with .pending. removed
                approved_name = pending_abs.name.replace(".pending.", ".")
                approved_abs = pending_abs.with_name(approved_name)
                tp = toolpack_path or "toolpack.yaml"
                click.echo(
                    "Error: approved lockfile required.\n"
                    "\n"
                    "Your toolpack has pending approvals. Run:\n"
                    "\n"
                    f"  toolwright gate allow --all --lockfile {pending_abs}\n"
                    f"  toolwright gate check --lockfile {approved_abs}\n"
                    "\n"
                    "Then start the server with:\n"
                    "\n"
                    f"  toolwright serve --toolpack {tp} --lockfile {approved_abs}",
                    err=True,
                )
            else:
                tp = toolpack_path or "toolpack.yaml"
                tp_dir = Path(tp).resolve().parent if toolpack_path else Path.cwd()
                default_lockfile = tp_dir / "lockfile" / "toolwright.lock.yaml"
                click.echo(
                    "Error: no lockfile found.\n"
                    "\n"
                    "Create and approve a lockfile first:\n"
                    "\n"
                    f"  toolwright gate sync --tools {resolved_tools_path}\n"
                    f"  toolwright gate allow --all\n"
                    "\n"
                    "Then start the server with:\n"
                    "\n"
                    f"  toolwright serve --toolpack {tp} --lockfile {default_lockfile}",
                    err=True,
                )
            sys.exit(1)
        if ".pending." in resolved_lockfile_path.name:
            if not effective_toolset:
                click.echo(
                    "Error: pending lockfile cannot be used for runtime. "
                    "Pass an approved lockfile or use --unsafe-no-lockfile.",
                    err=True,
                )
                sys.exit(1)
            from toolwright.core.approval import LockfileManager

            manager = LockfileManager(resolved_lockfile_path)
            manager.load()
            approvals_passed, message = manager.check_approvals(toolset=effective_toolset)
            if not approvals_passed:
                click.echo(
                    f"Error: pending lockfile is not fully approved for toolset '{effective_toolset}'. "
                    f"{message}",
                    err=True,
                )
                sys.exit(1)

    if verbose:
        click.echo("Starting Toolwright MCP Server...", err=True)
        click.echo(f"  Tools: {resolved_tools_path}", err=True)
        if toolpack_path:
            click.echo(f"  Toolpack: {toolpack_path}", err=True)
        if resolved_toolsets_path:
            click.echo(f"  Toolsets: {resolved_toolsets_path}", err=True)
        if effective_toolset:
            click.echo(f"  Selected toolset: {effective_toolset}", err=True)
        if resolved_policy_path:
            click.echo(f"  Policy: {resolved_policy_path}", err=True)
        if resolved_lockfile_path:
            click.echo(f"  Lockfile: {resolved_lockfile_path}", err=True)
        elif (
            resolved_toolpack is not None
            and resolved_toolpack.paths.lockfiles.get("pending")
        ):
            click.echo(
                "  Lockfile: none selected (toolpack has pending approvals only)",
                err=True,
            )
        if base_url:
            click.echo(f"  Base URL: {base_url}", err=True)
        if audit_log:
            click.echo(f"  Audit log: {audit_log}", err=True)
        if dry_run:
            click.echo("  Mode: DRY RUN (no actual requests)", err=True)
        if unsafe_no_lockfile:
            click.echo("  WARNING: unsafe no-lockfile mode enabled", err=True)
        if watch:
            click.echo("  Watch mode: ENABLED (reconciliation loop active)", err=True)
            if watch_config_path:
                click.echo(f"  Watch config: {watch_config_path}", err=True)

    # Merge extra headers: toolpack stored headers as base, CLI flags override
    merged_extra_headers: dict[str, str] | None = None
    if resolved_toolpack and resolved_toolpack.extra_headers:
        merged_extra_headers = dict(resolved_toolpack.extra_headers)
    if extra_headers:
        if merged_extra_headers is None:
            merged_extra_headers = {}
        merged_extra_headers.update(extra_headers)

    # Check for empty tool manifest
    try:
        with open(resolved_tools_path) as f:
            _manifest = json.load(f)
        _actions = _manifest.get("actions", [])
        if not _actions:
            click.echo(
                "Error: Toolpack has 0 tools. "
                "Run 'toolwright create' first to generate tools.",
                err=True,
            )
            sys.exit(1)
    except (json.JSONDecodeError, OSError):
        pass  # Let downstream code handle invalid manifests

    # Warn about missing auth env vars
    auth_warnings = warn_missing_auth(
        tools_path=resolved_tools_path,
        auth_header=auth_header,
    )
    for warning in auth_warnings:
        click.echo(f"  WARNING: {warning}", err=True)

    # Render startup card with governance layers
    from toolwright.mcp.startup_card import render_startup_card

    _tools_manifest = {}
    try:
        with open(resolved_tools_path) as _tf:
            _tools_manifest = json.load(_tf)
    except (json.JSONDecodeError, OSError):
        pass
    _tool_actions = _tools_manifest.get("actions", [])
    _total_compiled = len(_tool_actions)

    # Pre-filter by scope for accurate startup card counts
    _display_actions = _tool_actions
    if scope:
        _groups_file = resolved_tools_path.parent / "groups.json"
        if _groups_file.exists():
            try:
                from toolwright.core.compile.grouper import ToolGroupIndex, filter_by_scope

                _groups_data = json.loads(_groups_file.read_text())
                _groups_index = ToolGroupIndex.from_dict(_groups_data)
                _display_actions = filter_by_scope(_tool_actions, scope, _groups_index)
            except (json.JSONDecodeError, OSError, ValueError, ImportError):
                pass  # Fall back to showing all tools

    # M1: Filter by max_risk before computing banner counts
    if max_risk:
        _risk_order = ["low", "medium", "high", "critical"]
        _max_idx = _risk_order.index(max_risk) if max_risk in _risk_order else len(_risk_order) - 1
        _display_actions = [
            a for a in _display_actions
            if _risk_order.index(a.get("risk_tier", "low")) <= _max_idx
            if a.get("risk_tier", "low") in _risk_order
        ]

    _tool_categories: dict[str, int] = {}
    _risk_counts: dict[str, int] = {}
    for _action in _display_actions:
        method = _action.get("method", "GET").upper()
        cat = "read" if method == "GET" else "write" if method in ("POST", "PUT", "PATCH") else "admin"
        _tool_categories[cat] = _tool_categories.get(cat, 0) + 1
        tier = _action.get("risk_tier", "low")
        _risk_counts[tier] = _risk_counts.get(tier, 0) + 1

    _total_tokens = len(_display_actions) * 500  # rough estimate
    _tokens_per = 500 if _display_actions else 0

    # Build governance dict
    _governance: dict[str, str | None] = {
        "lockfile": "active" if resolved_lockfile_path else None,
        "rules": None,
        "policy": None,
        "breakers": None,
        "watch": None,
    }
    if rules_path and Path(rules_path).exists():
        try:
            _rules_data = json.loads(Path(rules_path).read_text())
            _governance["rules"] = f"{len(_rules_data)} rules"
        except (json.JSONDecodeError, OSError):
            _governance["rules"] = "configured"
    if resolved_policy_path and resolved_policy_path.exists():
        _governance["policy"] = "active"
    if circuit_breaker_path and Path(circuit_breaker_path).exists():
        _governance["breakers"] = "configured"
    if watch:
        _governance["watch"] = auto_heal_override or "on"

    _card_name = ""
    if resolved_toolpack:
        _card_name = resolved_toolpack.display_name or resolved_toolpack.toolpack_id
    else:
        _card_name = str(resolved_tools_path.stem)

    card = render_startup_card(
        name=_card_name,
        tools=_tool_categories,
        risk_counts=_risk_counts,
        context_tokens=_total_tokens,
        tokens_per_tool=_tokens_per,
        auto_heal=auto_heal_override if watch else None,
        scope_info=scope,
        total_compiled=_total_compiled if scope else None,
        governance=_governance,
    )
    click.echo(card, err=True)

    # Import here to avoid loading MCP dependencies unless needed
    from toolwright.mcp.server import run_mcp_server

    # Extract auth requirements from toolpack for per-host header name resolution
    auth_requirements = None
    if resolved_toolpack and resolved_toolpack.auth_requirements:
        auth_requirements = resolved_toolpack.auth_requirements

    try:
        run_mcp_server(
            tools_path=str(resolved_tools_path),
            toolsets_path=str(resolved_toolsets_path) if resolved_toolsets_path else None,
            toolset_name=effective_toolset,
            policy_path=str(resolved_policy_path) if resolved_policy_path else None,
            lockfile_path=str(resolved_lockfile_path) if resolved_lockfile_path else None,
            base_url=base_url,
            auth_header=auth_header,
            audit_log=audit_log,
            dry_run=dry_run,
            confirmation_store_path=confirmation_store_path,
            allow_private_cidrs=allow_private_cidrs,
            allow_redirects=allow_redirects,
            rules_path=rules_path,
            circuit_breaker_path=circuit_breaker_path,
            watch=watch,
            watch_config_path=watch_config_path,
            auto_heal_override=auto_heal_override,
            verbose_tools=verbose_tools,
            tool_filter=tool_filter,
            max_risk=max_risk,
            transport=transport,
            host=host,
            port=port,
            extra_headers=merged_extra_headers,
            schema_validation=schema_validation,
            scope=scope,
            no_tool_limit=no_tool_limit,
            shape_baselines_path=shape_baselines_path,
            shape_probe_interval=shape_probe_interval,
            auth_requirements=auth_requirements,
        )
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
