"""Gate command group for approval workflows."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import click

from toolwright.utils.state import resolve_root


def _resolve_gate_paths(toolpack_path: str) -> dict[str, str | None]:
    """Resolve gate paths (tools, lockfile, policy, toolsets) from a toolpack.yaml."""
    import sys

    from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

    try:
        toolpack = load_toolpack(Path(toolpack_path))
        resolved = resolve_toolpack_paths(toolpack=toolpack, toolpack_path=toolpack_path)
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"Error loading toolpack: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error loading toolpack {toolpack_path}: {e}", err=True)
        sys.exit(1)

    lockfile = str(resolved.approved_lockfile_path or resolved.pending_lockfile_path)
    return {
        "tools": str(resolved.tools_path),
        "policy": str(resolved.policy_path) if resolved.policy_path else None,
        "toolsets": str(resolved.toolsets_path) if resolved.toolsets_path else None,
        "lockfile": lockfile,
    }


def _auto_resolve_toolpack(
    toolpack: str | None,
    root: Path | None = None,
) -> str | None:
    """Auto-resolve toolpack path if not explicitly provided.

    Returns the resolved path as a string, or None if resolution fails
    (letting the caller handle the error case).
    """
    if toolpack:
        return toolpack
    try:
        from toolwright.utils.resolve import resolve_toolpack_path

        return str(resolve_toolpack_path(root=root))
    except (FileNotFoundError, click.UsageError):
        return None


def register_approval_commands(
    *,
    cli: click.Group,
    run_with_lock: Callable[..., None],
) -> None:
    """Register the gate command group on the provided CLI group."""

    @cli.group()
    def gate() -> None:
        """Approve or block tools via lockfile-based governance."""

    @gate.command("sync")
    @click.option(
        "--tools", "-t",
        required=False,
        type=click.Path(exists=True),
        help="Path to tools.json manifest",
    )
    @click.option(
        "--toolpack",
        type=click.Path(exists=True),
        help="Path to toolpack.yaml (auto-resolves tools, lockfile, policy, toolsets)",
    )
    @click.option(
        "--policy",
        type=click.Path(exists=True),
        help="Path to policy.yaml artifact (defaults to sibling of --tools if present)",
    )
    @click.option(
        "--toolsets",
        type=click.Path(exists=True),
        help="Path to toolsets.yaml artifact (optional)",
    )
    @click.option(
        "--lockfile", "-l",
        type=click.Path(),
        help="Path to lockfile (default: ./toolwright.lock.yaml)",
    )
    @click.option(
        "--capture-id",
        help="Capture ID to associate with this sync",
    )
    @click.option(
        "--scope",
        help="Scope name to associate with this sync",
    )
    @click.option(
        "--deterministic/--volatile-metadata",
        default=True,
        show_default=True,
        help="Deterministic lockfile metadata by default; use --volatile-metadata for ephemeral timestamps",
    )
    @click.option(
        "--prune-removed/--keep-removed",
        default=False,
        show_default=True,
        help="Remove tools no longer present in the manifest from the lockfile",
    )
    @click.option(
        "--yes", "-y",
        is_flag=True,
        help="Skip confirmation prompt (required with --prune-removed)",
    )
    @click.pass_context
    def gate_sync(
        ctx: click.Context,
        tools: str | None,
        toolpack: str | None,
        policy: str | None,
        toolsets: str | None,
        lockfile: str | None,
        capture_id: str | None,
        scope: str | None,
        deterministic: bool,
        prune_removed: bool,
        yes: bool,
    ) -> None:
        """Sync lockfile with a tools manifest.

        Compares the manifest against the lockfile and tracks changes:
        new tools are added as pending, modified tools require re-approval,
        removed tools are tracked but not deleted.

        \b
        Examples:
          toolwright gate sync --tools tools.json
          toolwright gate sync --toolpack toolpack.yaml
          toolwright gate sync --tools tools.json --lockfile custom.lock.yaml
        """
        if toolpack and tools:
            raise click.UsageError("Cannot use both --toolpack and --tools. They are mutually exclusive.")

        # Auto-resolve toolpack if neither --toolpack nor --tools provided
        if not toolpack and not tools:
            resolved_tp = _auto_resolve_toolpack(None, root=ctx.obj.get("root"))
            if resolved_tp:
                toolpack = resolved_tp
            else:
                from toolwright.utils.resolve import resolve_toolpack_path

                # Let it raise with the actionable error message
                resolve_toolpack_path(root=ctx.obj.get("root"))

        if toolpack:
            resolved = _resolve_gate_paths(toolpack)
            tools = resolved["tools"]  # type: ignore[assignment]
            policy = policy or resolved["policy"]
            toolsets = toolsets or resolved["toolsets"]
            lockfile = lockfile or resolved["lockfile"]

        no_interactive = ctx.obj.get("no_interactive_explicit", False) if ctx.obj else False
        if prune_removed and not yes and not no_interactive:
            click.echo("This will remove approval records for tools no longer in the manifest.")
            if not click.confirm("Proceed?", default=False):
                click.echo("Aborted.")
                raise SystemExit(0)

        from toolwright.cli.approve import run_approve_sync

        run_with_lock(
            ctx,
            "gate sync",
            lambda: run_approve_sync(
                tools_path=tools,  # type: ignore[arg-type]
                policy_path=policy,
                toolsets_path=toolsets,
                lockfile_path=lockfile,
                capture_id=capture_id,
                scope=scope,
                verbose=ctx.obj.get("verbose", False),
                prune_removed=prune_removed,
                deterministic=deterministic,
            ),
        )

    @gate.command("status")
    @click.option(
        "--toolpack",
        type=click.Path(exists=True),
        help="Path to toolpack.yaml (auto-resolves lockfile path)",
    )
    @click.option(
        "--lockfile", "-l",
        type=click.Path(),
        help="Path to lockfile (default: ./toolwright.lock.yaml)",
    )
    @click.option(
        "--status", "-s",
        "status_filter",
        type=click.Choice(["pending", "approved", "rejected"]),
        help="Filter by approval status",
    )
    @click.option(
        "--by-group",
        is_flag=True,
        help="Show approval summary grouped by tool group",
    )
    @click.pass_context
    def gate_status(
        ctx: click.Context,
        toolpack: str | None,
        lockfile: str | None,
        status_filter: str | None,
        by_group: bool,
    ) -> None:
        """List tool approvals from the lockfile.

        \b
        Examples:
          toolwright gate status
          toolwright gate status --toolpack toolpack.yaml
          toolwright gate status --status pending
          toolwright gate status --by-group --toolpack toolpack.yaml
        """
        if by_group:
            # Resolve groups path from toolpack
            groups_path = None
            resolved_toolpack = _auto_resolve_toolpack(toolpack, root=ctx.obj.get("root"))
            if resolved_toolpack:
                from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

                try:
                    tp = load_toolpack(resolved_toolpack)
                    resolved = resolve_toolpack_paths(toolpack=tp, toolpack_path=resolved_toolpack)
                    groups_path = resolved.groups_path
                    if not lockfile:
                        lockfile = str(resolved.approved_lockfile_path or resolved.pending_lockfile_path)
                except Exception:
                    pass

            if groups_path is None or not groups_path.exists():
                click.echo("No tool groups found. Run 'toolwright compile' to generate groups.", err=True)
                ctx.exit(1)
                return

            from toolwright.core.compile.grouper import load_groups_index

            groups_index = load_groups_index(groups_path)
            if groups_index is None or not groups_index.groups:
                click.echo("No tool groups found.", err=True)
                ctx.exit(1)
                return

            # Load lockfile for status info
            from toolwright.core.approval import LockfileManager

            if not lockfile:
                click.echo("No lockfile found. Run 'toolwright gate sync' first.", err=True)
                ctx.exit(1)
                return

            manager = LockfileManager(lockfile)
            if not manager.exists():
                click.echo(f"No lockfile found at: {manager.lockfile_path}", err=True)
                ctx.exit(1)
                return

            manager.load()
            lf = manager.lockfile
            assert lf is not None

            # Build tool -> status map
            tool_statuses: dict[str, str] = {}
            for tool in lf.tools.values():
                tool_statuses[tool.name] = tool.status.value

            click.echo("\nApproval status by group:\n")
            for group in groups_index.groups:
                approved = sum(1 for t in group.tools if tool_statuses.get(t) == "approved")
                pending = sum(1 for t in group.tools if tool_statuses.get(t, "pending") == "pending")
                rejected = sum(1 for t in group.tools if tool_statuses.get(t) == "rejected")

                parts = []
                if approved:
                    parts.append(f"{approved} approved")
                if pending:
                    parts.append(f"{pending} pending")
                if rejected:
                    parts.append(f"{rejected} rejected")

                status_str = ", ".join(parts) if parts else "unknown"
                from toolwright.utils.text import pluralize

                click.echo(f"  {group.name} ({pluralize(len(group.tools), 'tool')})    {status_str}")

            if groups_index.ungrouped:
                click.echo(f"\n  Ungrouped: {len(groups_index.ungrouped)} tools")

            return

        if not toolpack and not lockfile:
            toolpack = _auto_resolve_toolpack(None, root=ctx.obj.get("root"))
        if toolpack and not lockfile:
            resolved = _resolve_gate_paths(toolpack)
            lockfile = resolved["lockfile"]

        from toolwright.cli.approve import run_approve_list

        run_approve_list(
            lockfile_path=lockfile,
            status_filter=status_filter,
            verbose=ctx.obj.get("verbose", False),
        )

    @gate.command("allow")
    @click.argument("tool_ids", nargs=-1)
    @click.option(
        "--toolpack",
        type=click.Path(exists=True),
        help="Path to toolpack.yaml (auto-resolves lockfile path)",
    )
    @click.option(
        "--lockfile", "-l",
        type=click.Path(),
        help="Path to lockfile (default: ./toolwright.lock.yaml)",
    )
    @click.option(
        "--all", "all_pending",
        is_flag=True,
        help="Approve all pending tools",
    )
    @click.option(
        "--yes", "-y",
        is_flag=True,
        help="Skip confirmation prompt (required with --all)",
    )
    @click.option(
        "--toolset",
        help="Approve tools within a specific toolset",
    )
    @click.option(
        "--by",
        "approved_by",
        help="Who is approving (default: $USER)",
    )
    @click.option(
        "--reason",
        help="Approval reason (recorded in lockfile signature metadata)",
    )
    @click.option(
        "--include-rejected",
        is_flag=True,
        help="Also approve rejected tools when using --all",
    )
    @click.pass_context
    def gate_allow(
        ctx: click.Context,
        tool_ids: tuple[str, ...],
        toolpack: str | None,
        lockfile: str | None,
        all_pending: bool,
        yes: bool,
        toolset: str | None,
        approved_by: str | None,
        reason: str | None,
        include_rejected: bool,
    ) -> None:
        """Approve one or more tools for use.

        \b
        Examples:
          toolwright gate allow get_users create_user
          toolwright gate allow --all --toolpack toolpack.yaml
          toolwright gate allow --all
          toolwright gate allow get_users --by security@example.com
        """
        if not toolpack and not lockfile:
            toolpack = _auto_resolve_toolpack(None, root=ctx.obj.get("root"))
        if toolpack and not lockfile:
            resolved = _resolve_gate_paths(toolpack)
            lockfile = resolved["lockfile"]

        # Interactive: no tool_ids, no --all, no --toolset -> review flow
        if not tool_ids and not all_pending and not toolset and ctx.obj.get("interactive"):
            from toolwright.ui.flows.gate_review import gate_review_flow

            gate_review_flow(
                lockfile_path=lockfile,
                root_path=str(ctx.obj.get("root", resolve_root())),
                verbose=ctx.obj.get("verbose", False),
            )
            return

        no_interactive = ctx.obj.get("no_interactive_explicit", False) if ctx.obj else False
        if all_pending and not yes and not no_interactive:
            click.echo("This will approve ALL pending tools.")
            if not click.confirm("Proceed?", default=False):
                click.echo("Aborted.")
                raise SystemExit(0)

        from toolwright.cli.approve import run_approve_tool

        run_with_lock(
            ctx,
            "gate allow",
            lambda: run_approve_tool(
                tool_ids=tool_ids,
                lockfile_path=lockfile,
                all_pending=all_pending,
                toolset=toolset,
                approved_by=approved_by,
                reason=reason,
                root_path=str(ctx.obj.get("root", resolve_root())),
                verbose=ctx.obj.get("verbose", False),
                include_rejected=include_rejected,
            ),
        )

    @gate.command("block")
    @click.argument("tool_ids", nargs=-1, required=True)
    @click.option(
        "--toolpack",
        type=click.Path(exists=True),
        help="Path to toolpack.yaml (auto-resolves lockfile path)",
    )
    @click.option(
        "--lockfile", "-l",
        type=click.Path(),
        help="Path to lockfile (default: ./toolwright.lock.yaml)",
    )
    @click.option(
        "--reason", "-r",
        help="Reason for rejection",
    )
    @click.pass_context
    def gate_block(
        ctx: click.Context,
        tool_ids: tuple[str, ...],
        toolpack: str | None,
        lockfile: str | None,
        reason: str | None,
    ) -> None:
        """Block one or more tools. Blocked tools cause CI checks to fail.

        \b
        Examples:
          toolwright gate block delete_all_users --reason "Too dangerous"
          toolwright gate block tool1 tool2 --toolpack toolpack.yaml
          toolwright gate block tool1 tool2
        """
        if not toolpack and not lockfile:
            toolpack = _auto_resolve_toolpack(None, root=ctx.obj.get("root"))
        if toolpack and not lockfile:
            resolved = _resolve_gate_paths(toolpack)
            lockfile = resolved["lockfile"]

        from toolwright.cli.approve import run_approve_reject

        run_with_lock(
            ctx,
            "gate block",
            lambda: run_approve_reject(
                tool_ids=tool_ids,
                lockfile_path=lockfile,
                reason=reason,
                verbose=ctx.obj.get("verbose", False),
            ),
        )

    @gate.command("check")
    @click.option(
        "--toolpack",
        type=click.Path(exists=True),
        help="Path to toolpack.yaml (auto-resolves lockfile path)",
    )
    @click.option(
        "--lockfile", "-l",
        type=click.Path(),
        help="Path to lockfile (default: ./toolwright.lock.yaml)",
    )
    @click.option(
        "--toolset",
        help="Check approval status for a specific toolset only",
    )
    @click.pass_context
    def gate_check(
        ctx: click.Context,
        toolpack: str | None,
        lockfile: str | None,
        toolset: str | None,
    ) -> None:
        """Check if all tools are approved (CI gate).

        Exit codes:
          0 - All tools approved
          1 - Pending or rejected tools exist
          2 - No lockfile found

        \b
        Examples:
          toolwright gate check
          toolwright gate check --toolpack toolpack.yaml
          toolwright gate check --lockfile custom.lock.yaml
        """
        if not toolpack and not lockfile:
            toolpack = _auto_resolve_toolpack(None, root=ctx.obj.get("root"))
        if toolpack and not lockfile:
            resolved = _resolve_gate_paths(toolpack)
            lockfile = resolved["lockfile"]

        from toolwright.cli.approve import run_approve_check

        run_approve_check(
            lockfile_path=lockfile,
            toolset=toolset,
            verbose=ctx.obj.get("verbose", False),
        )

    @gate.command("snapshot")
    @click.option(
        "--toolpack",
        type=click.Path(exists=True),
        help="Path to toolpack.yaml (auto-resolves lockfile path)",
    )
    @click.option(
        "--lockfile", "-l",
        type=click.Path(),
        help="Path to lockfile (default: ./toolwright.lock.yaml)",
    )
    @click.option(
        "--snapshot-dir",
        type=click.Path(),
        default=None,
        help="Override snapshot destination directory (default: .toolwright/approvals/...).",
    )
    @click.pass_context
    def gate_snapshot(
        ctx: click.Context,
        toolpack: str | None,
        lockfile: str | None,
        snapshot_dir: str | None,
    ) -> None:
        """Materialize a baseline snapshot for an approved lockfile.

        \b
        Examples:
          toolwright gate snapshot --toolpack toolpack.yaml
          toolwright gate snapshot --lockfile custom.lock.yaml
        """
        if not toolpack and not lockfile:
            toolpack = _auto_resolve_toolpack(None, root=ctx.obj.get("root"))
        if toolpack and not lockfile:
            resolved = _resolve_gate_paths(toolpack)
            lockfile = resolved["lockfile"]

        # Interactive: no --lockfile -> snapshot flow
        if lockfile is None and snapshot_dir is None and ctx.obj.get("interactive"):
            from toolwright.ui.flows.gate_snapshot import gate_snapshot_flow

            gate_snapshot_flow(
                root_path=str(ctx.obj.get("root", resolve_root())),
                verbose=ctx.obj.get("verbose", False),
            )
            return

        from toolwright.cli.approve import run_approve_snapshot

        run_with_lock(
            ctx,
            "gate snapshot",
            lambda: run_approve_snapshot(
                lockfile_path=lockfile,
                root_path=str(ctx.obj.get("root", resolve_root())),
                verbose=ctx.obj.get("verbose", False),
                snapshot_dir=snapshot_dir,
            ),
        )

    @gate.command("reseal")
    @click.option(
        "--toolpack",
        type=click.Path(exists=True),
        help="Path to toolpack.yaml (auto-resolves lockfile path)",
    )
    @click.option(
        "--lockfile", "-l",
        type=click.Path(),
        help="Path to lockfile (default: ./toolwright.lock.yaml)",
    )
    @click.option("--toolset", help="Re-sign approvals for tools within a specific toolset only")
    @click.pass_context
    def gate_reseal(
        ctx: click.Context,
        toolpack: str | None,
        lockfile: str | None,
        toolset: str | None,
    ) -> None:
        """Re-sign existing approval signatures (migration / repair helper).

        \b
        Examples:
          toolwright gate reseal --toolpack toolpack.yaml
          toolwright gate reseal --lockfile custom.lock.yaml
        """
        if not toolpack and not lockfile:
            toolpack = _auto_resolve_toolpack(None, root=ctx.obj.get("root"))
        if toolpack and not lockfile:
            resolved = _resolve_gate_paths(toolpack)
            lockfile = resolved["lockfile"]

        from toolwright.cli.approve import run_approve_resign

        run_with_lock(
            ctx,
            "gate reseal",
            lambda: run_approve_resign(
                lockfile_path=lockfile,
                toolset=toolset,
                root_path=str(ctx.obj.get("root", resolve_root())),
                verbose=ctx.obj.get("verbose", False),
            ),
        )
