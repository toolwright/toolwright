"""Governance-oriented hidden command registration."""

from __future__ import annotations

from collections.abc import Callable

import click

from toolwright.cli.command_helpers import (
    cli_root_str,
    default_root_path,
    resolve_confirmation_store,
)


def register_governance_commands(
    *,
    cli: click.Group,
    run_with_lock: Callable[..., None],
) -> None:
    """Register hidden governance workflow commands."""

    @cli.group(hidden=True)
    def scope() -> None:
        """Scope authoring and merge workflows."""

    @scope.command("merge")
    @click.option(
        "--suggested",
        type=click.Path(),
        help="Path to generated scopes.suggested.yaml (defaults to <root>/scopes/scopes.suggested.yaml)",
    )
    @click.option(
        "--authoritative",
        type=click.Path(),
        help="Path to authoritative scopes.yaml (defaults to <root>/scopes/scopes.yaml)",
    )
    @click.option(
        "--output",
        type=click.Path(),
        help="Path to write merge proposal (defaults to sibling scopes.merge.proposed.yaml)",
    )
    @click.option("--apply", is_flag=True, help="Apply merged proposal into authoritative scopes.yaml")
    @click.pass_context
    def scope_merge(
        ctx: click.Context,
        suggested: str | None,
        authoritative: str | None,
        output: str | None,
        apply: bool,
    ) -> None:
        """Merge suggested scopes into authoritative scopes via explicit proposal."""
        from toolwright.cli.scopes import run_scopes_merge

        resolved_suggested = suggested or str(default_root_path(ctx, "scopes", "scopes.suggested.yaml"))
        resolved_authoritative = authoritative or str(default_root_path(ctx, "scopes", "scopes.yaml"))

        def _merge_scopes() -> None:
            run_scopes_merge(
                suggested_path=resolved_suggested,
                authoritative_path=resolved_authoritative,
                output_path=output,
                apply=apply,
                verbose=ctx.obj.get("verbose", False),
            )

        if apply:
            run_with_lock(ctx, "scope merge", _merge_scopes)
        else:
            _merge_scopes()

    @cli.group(hidden=True)
    def confirm() -> None:
        """Out-of-band confirmation workflow for state-changing actions."""

    @confirm.command("grant")
    @click.argument("token_id", required=True)
    @click.option(
        "--store",
        "store_path",
        type=click.Path(),
        help="Path to confirmation store",
    )
    @click.pass_context
    def confirm_grant(ctx: click.Context, token_id: str, store_path: str | None) -> None:
        """Grant a pending confirmation token."""
        from toolwright.cli.confirm import run_confirm_grant

        run_with_lock(
            ctx,
            "confirm grant",
            lambda: run_confirm_grant(
                token_id=token_id,
                db_path=resolve_confirmation_store(ctx, store_path),
                verbose=ctx.obj.get("verbose", False),
            ),
        )

    @confirm.command("deny")
    @click.argument("token_id", required=True)
    @click.option(
        "--store",
        "store_path",
        type=click.Path(),
        help="Path to confirmation store",
    )
    @click.option("--reason", help="Optional denial reason")
    @click.pass_context
    def confirm_deny(
        ctx: click.Context,
        token_id: str,
        store_path: str | None,
        reason: str | None,
    ) -> None:
        """Deny a pending confirmation token."""
        from toolwright.cli.confirm import run_confirm_deny

        run_with_lock(
            ctx,
            "confirm deny",
            lambda: run_confirm_deny(
                token_id=token_id,
                db_path=resolve_confirmation_store(ctx, store_path),
                reason=reason,
                verbose=ctx.obj.get("verbose", False),
            ),
        )

    @confirm.command("list")
    @click.option(
        "--store",
        "store_path",
        type=click.Path(),
        help="Path to confirmation store",
    )
    @click.pass_context
    def confirm_list(ctx: click.Context, store_path: str | None) -> None:
        """List pending confirmation tokens."""
        from toolwright.cli.confirm import run_confirm_list

        run_confirm_list(
            db_path=resolve_confirmation_store(ctx, store_path),
            verbose=ctx.obj.get("verbose", False),
        )

    @cli.group(hidden=True)
    def propose() -> None:
        """Manage agent draft proposals for new capabilities."""

    @propose.command("create")
    @click.argument("capture_id")
    @click.option(
        "--scope",
        "-s",
        default="first_party_only",
        show_default=True,
        help="Scope to apply before generating proposals",
    )
    @click.option(
        "--scope-file",
        type=click.Path(exists=True),
        default=None,
        help="Optional custom scope file",
    )
    @click.option(
        "--output",
        "-o",
        type=click.Path(file_okay=False),
        default=None,
        help="Directory to write proposal artifacts (defaults to <root>/proposals)",
    )
    @click.option(
        "--deterministic/--volatile-metadata",
        default=True,
        show_default=True,
        help="Deterministic proposal artifact IDs by default",
    )
    @click.pass_context
    def propose_create(
        ctx: click.Context,
        capture_id: str,
        scope: str,
        scope_file: str | None,
        output: str | None,
        deterministic: bool,
    ) -> None:
        """Generate endpoint catalog and tool proposals from a capture."""
        from toolwright.cli.propose import run_propose_from_capture

        run_propose_from_capture(
            root=cli_root_str(ctx),
            capture_id=capture_id,
            scope_name=scope,
            scope_file=scope_file,
            output_dir=output,
            deterministic=deterministic,
            verbose=ctx.obj.get("verbose", False) if ctx.obj else False,
        )

    @propose.command("publish")
    @click.argument("proposal_input", type=click.Path(exists=True))
    @click.option(
        "--output",
        "-o",
        type=click.Path(file_okay=False),
        default=None,
        help="Directory root for published bundle output (defaults to <root>/published)",
    )
    @click.option(
        "--min-confidence",
        type=float,
        default=0.75,
        show_default=True,
        help="Minimum proposal confidence to include",
    )
    @click.option(
        "--max-risk",
        type=click.Choice(["safe", "low", "medium", "high", "critical"]),
        default="high",
        show_default=True,
        help="Maximum risk tier to include",
    )
    @click.option(
        "--include-review-required",
        is_flag=True,
        help="Include proposals flagged as requires_review",
    )
    @click.option(
        "--proposal-id",
        "proposal_ids",
        multiple=True,
        help="Restrict publish to specific proposal IDs (repeatable)",
    )
    @click.option(
        "--sync-lockfile",
        is_flag=True,
        help="Sync generated tools into lockfile after publish",
    )
    @click.option(
        "--lockfile",
        default=None,
        help="Lockfile path override (used with --sync-lockfile)",
    )
    @click.option(
        "--deterministic/--volatile-metadata",
        default=True,
        show_default=True,
        help="Deterministic bundle IDs and timestamps by default",
    )
    @click.pass_context
    def propose_publish(
        ctx: click.Context,
        proposal_input: str,
        output: str | None,
        min_confidence: float,
        max_risk: str,
        include_review_required: bool,
        proposal_ids: tuple[str, ...],
        sync_lockfile: bool,
        lockfile: str | None,
        deterministic: bool,
    ) -> None:
        """Publish tools.proposed.yaml into runtime-ready bundle artifacts."""
        from toolwright.cli.propose import run_propose_publish

        run_propose_publish(
            root=cli_root_str(ctx),
            proposal_input=proposal_input,
            output_dir=output,
            min_confidence=min_confidence,
            max_risk=max_risk,
            include_review_required=include_review_required,
            proposal_ids=proposal_ids,
            sync_lockfile_enabled=sync_lockfile,
            lockfile_path=lockfile,
            deterministic=deterministic,
            verbose=ctx.obj.get("verbose", False) if ctx.obj else False,
        )

    @propose.command("list")
    @click.option("--status", type=click.Choice(["pending", "approved", "rejected"]), default=None)
    @click.pass_context
    def propose_list(ctx: click.Context, status: str | None) -> None:
        """List agent draft proposals."""
        from toolwright.cli.propose import run_propose_list

        run_propose_list(root=cli_root_str(ctx), status=status)

    @propose.command("show")
    @click.argument("proposal_id")
    @click.pass_context
    def propose_show(ctx: click.Context, proposal_id: str) -> None:
        """Show details of a specific proposal."""
        from toolwright.cli.propose import run_propose_show

        run_propose_show(root=cli_root_str(ctx), proposal_id=proposal_id)

    @propose.command("approve")
    @click.argument("proposal_id")
    @click.option("--by", "reviewed_by", default="human", help="Who is approving")
    @click.pass_context
    def propose_approve(ctx: click.Context, proposal_id: str, reviewed_by: str) -> None:
        """Approve a proposal for future capture."""
        from toolwright.cli.propose import run_propose_approve

        run_propose_approve(
            root=cli_root_str(ctx),
            proposal_id=proposal_id,
            reviewed_by=reviewed_by,
        )

    @propose.command("reject")
    @click.argument("proposal_id")
    @click.option("--reason", "-r", default="", help="Rejection reason")
    @click.option("--by", "reviewed_by", default="human", help="Who is rejecting")
    @click.pass_context
    def propose_reject(
        ctx: click.Context,
        proposal_id: str,
        reason: str,
        reviewed_by: str,
    ) -> None:
        """Reject a proposal with an optional reason."""
        from toolwright.cli.propose import run_propose_reject

        run_propose_reject(
            root=cli_root_str(ctx),
            proposal_id=proposal_id,
            reason=reason,
            reviewed_by=reviewed_by,
        )
