"""CLI transport serve orchestration.

Resolves toolpack paths and starts the CLI transport adapter.
Mirrors the path resolution from mcp/runtime.py but without MCP dependencies.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from toolwright.cli_transport.adapter import CLITransportAdapter
from toolwright.core.governance.runtime import GovernanceRuntime


def run_cli_serve(
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
    unsafe_no_lockfile: bool = False,
    rules_path: str | None = None,
    circuit_breaker_path: str | None = None,
    extra_headers: dict[str, str] | None = None,
    schema_validation: str = "warn",
    verbose: bool = False,
) -> None:
    """Resolve paths and start the CLI transport adapter."""
    # ── Resolve toolpack paths ────────────────────────────────────────
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

    resolved_tools_path = Path(tools_path) if tools_path else None
    if resolved_tools_path is None and resolved_toolpack_paths is not None:
        resolved_tools_path = resolved_toolpack_paths.tools_path

    if resolved_tools_path is None:
        click.echo(
            "Error: No tools found. Provide --tools or --toolpack, "
            "or run 'toolwright create' first.",
            err=True,
        )
        sys.exit(1)
    if not resolved_tools_path.exists():
        click.echo(f"Error: Tools manifest not found: {resolved_tools_path}", err=True)
        sys.exit(1)

    resolved_policy_path: Path | None = None
    if policy_path:
        resolved_policy_path = Path(policy_path)
    elif resolved_toolpack_paths is not None:
        resolved_policy_path = resolved_toolpack_paths.policy_path

    resolved_toolsets_path: Path | None = None
    if toolsets_path:
        resolved_toolsets_path = Path(toolsets_path)
    elif resolved_toolpack_paths is not None:
        resolved_toolsets_path = resolved_toolpack_paths.toolsets_path

    effective_toolset = toolset_name
    if effective_toolset is None and resolved_toolsets_path and resolved_toolsets_path.exists():
        effective_toolset = "readonly"

    resolved_lockfile_path: Path | None = None
    if lockfile_path:
        resolved_lockfile_path = Path(lockfile_path)
    elif resolved_toolpack_paths is not None:
        toolpack_root = Path(toolpack_path).resolve().parent if toolpack_path else None
        candidates: list[Path] = []
        if resolved_toolpack_paths.approved_lockfile_path is not None:
            candidates.append(resolved_toolpack_paths.approved_lockfile_path)
        if toolpack_root is not None:
            candidates.extend(
                [
                    toolpack_root / "lockfile" / "toolwright.lock.approved.yaml",
                    toolpack_root / "lockfile" / "toolwright.lock.yaml",
                ]
            )
        for candidate in candidates:
            if candidate.exists():
                resolved_lockfile_path = candidate
                break

    if not unsafe_no_lockfile and resolved_lockfile_path is None:
        click.echo(
            "Error: No approved lockfile found. Run 'toolwright gate approve' "
            "or use --unsafe-no-lockfile.",
            err=True,
        )
        sys.exit(1)

    # ── Load dotenv auth ──────────────────────────────────────────────
    from toolwright.mcp.runtime import inject_dotenv_auth

    inject_dotenv_auth(root=Path.cwd())

    # ── Auth requirements ─────────────────────────────────────────────
    auth_requirements = None
    if resolved_toolpack and resolved_toolpack.auth_requirements:
        auth_requirements = resolved_toolpack.auth_requirements

    if verbose:
        click.echo("Starting Toolwright CLI Transport...", err=True)
        click.echo(f"  Tools: {resolved_tools_path}", err=True)
        if resolved_lockfile_path:
            click.echo(f"  Lockfile: {resolved_lockfile_path}", err=True)
        if dry_run:
            click.echo("  Mode: DRY RUN (no actual requests)", err=True)

    # ── Build runtime + adapter ───────────────────────────────────────
    try:
        runtime = GovernanceRuntime(
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
            extra_headers=extra_headers,
            schema_validation=schema_validation,
            auth_requirements=auth_requirements,
            transport_type="cli",
        )
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    click.echo(
        f"Toolwright CLI transport ready ({runtime.tool_count} tools). "
        f"Send JSONL to stdin.",
        err=True,
    )

    adapter = CLITransportAdapter(runtime)
    adapter.run()
