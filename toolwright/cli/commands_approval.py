"""Gate command group for approval workflows."""

from __future__ import annotations

from collections.abc import Callable

import click

from toolwright.utils.state import resolve_root


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
        required=True,
        type=click.Path(exists=True),
        help="Path to tools.json manifest",
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
    @click.pass_context
    def gate_sync(
        ctx: click.Context,
        tools: str,
        policy: str | None,
        toolsets: str | None,
        lockfile: str | None,
        capture_id: str | None,
        scope: str | None,
        deterministic: bool,
        prune_removed: bool,
    ) -> None:
        """Sync lockfile with a tools manifest.

        Compares the manifest against the lockfile and tracks changes:
        new tools are added as pending, modified tools require re-approval,
        removed tools are tracked but not deleted.

        \b
        Examples:
          toolwright gate sync --tools tools.json
          toolwright gate sync --tools tools.json --lockfile custom.lock.yaml
        """
        from toolwright.cli.approve import run_approve_sync

        run_with_lock(
            ctx,
            "gate sync",
            lambda: run_approve_sync(
                tools_path=tools,
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
    @click.pass_context
    def gate_status(
        ctx: click.Context,
        lockfile: str | None,
        status_filter: str | None,
    ) -> None:
        """List tool approvals from the lockfile.

        \b
        Examples:
          toolwright gate status
          toolwright gate status --status pending
        """
        from toolwright.cli.approve import run_approve_list

        run_approve_list(
            lockfile_path=lockfile,
            status_filter=status_filter,
            verbose=ctx.obj.get("verbose", False),
        )

    @gate.command("allow")
    @click.argument("tool_ids", nargs=-1)
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
    @click.pass_context
    def gate_allow(
        ctx: click.Context,
        tool_ids: tuple[str, ...],
        lockfile: str | None,
        all_pending: bool,
        toolset: str | None,
        approved_by: str | None,
        reason: str | None,
    ) -> None:
        """Approve one or more tools for use.

        \b
        Examples:
          toolwright gate allow get_users create_user
          toolwright gate allow --all
          toolwright gate allow get_users --by security@example.com
        """
        # Interactive: no tool_ids, no --all, no --toolset → review flow
        if not tool_ids and not all_pending and not toolset and ctx.obj.get("interactive"):
            from toolwright.ui.flows.gate_review import gate_review_flow

            gate_review_flow(
                lockfile_path=lockfile,
                root_path=str(ctx.obj.get("root", resolve_root())),
                verbose=ctx.obj.get("verbose", False),
            )
            return

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
            ),
        )

    @gate.command("block")
    @click.argument("tool_ids", nargs=-1, required=True)
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
        lockfile: str | None,
        reason: str | None,
    ) -> None:
        """Block one or more tools. Blocked tools cause CI checks to fail.

        \b
        Examples:
          toolwright gate block delete_all_users --reason "Too dangerous"
          toolwright gate block tool1 tool2
        """
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
          toolwright gate check --lockfile custom.lock.yaml
        """
        from toolwright.cli.approve import run_approve_check

        run_approve_check(
            lockfile_path=lockfile,
            toolset=toolset,
            verbose=ctx.obj.get("verbose", False),
        )

    @gate.command("snapshot")
    @click.option(
        "--lockfile", "-l",
        type=click.Path(),
        help="Path to lockfile (default: ./toolwright.lock.yaml)",
    )
    @click.option(
        "--snapshot-dir",
        type=click.Path(),
        default=None,
        help="Override snapshot destination directory (default: .toolwright/approvals/…).",
    )
    @click.pass_context
    def gate_snapshot(ctx: click.Context, lockfile: str | None, snapshot_dir: str | None) -> None:
        """Materialize a baseline snapshot for an approved lockfile."""
        # Interactive: no --lockfile → snapshot flow
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
        "--lockfile", "-l",
        type=click.Path(),
        help="Path to lockfile (default: ./toolwright.lock.yaml)",
    )
    @click.option("--toolset", help="Re-sign approvals for tools within a specific toolset only")
    @click.pass_context
    def gate_reseal(ctx: click.Context, lockfile: str | None, toolset: str | None) -> None:
        """Re-sign existing approval signatures (migration / repair helper)."""
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
