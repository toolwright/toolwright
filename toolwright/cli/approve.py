"""Approval command implementation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
import yaml

from toolwright.core.approval import (
    ApprovalStatus,
    LockfileManager,
    compute_artifacts_digest_from_paths,
)
from toolwright.core.approval.signing import ApprovalSigner, resolve_approver
from toolwright.core.approval.snapshot import materialize_snapshot, resolve_toolpack_root
from toolwright.core.toolpack import load_toolpack, write_toolpack
from toolwright.utils.files import atomic_write_text
from toolwright.utils.schema_version import resolve_schema_version


@dataclass(frozen=True)
class ApprovalSyncResult:
    """Result payload for lockfile sync operations."""

    lockfile_path: Path
    artifacts_digest: str
    changes: dict[str, list[str]]
    has_pending: bool
    pending_count: int


def sync_lockfile(
    *,
    tools_path: str,
    policy_path: str | None,
    toolsets_path: str | None,
    lockfile_path: str | None,
    capture_id: str | None,
    scope: str | None,
    deterministic: bool,
    prune_removed: bool = False,
    evidence_summary_sha256: str | None = None,
) -> ApprovalSyncResult:
    """Sync a lockfile from manifest + optional policy/toolsets."""
    if not Path(tools_path).exists():
        raise FileNotFoundError(f"Tools manifest not found: {tools_path}")

    with open(tools_path) as f:
        manifest = json.load(f)
    resolve_schema_version(manifest, artifact="tools manifest", allow_legacy=True)

    toolsets: dict[str, Any] | None = None
    resolved_toolsets: Path | None = None
    if toolsets_path:
        resolved_toolsets = Path(toolsets_path)
    else:
        candidate = Path(tools_path).parent / "toolsets.yaml"
        if candidate.exists():
            resolved_toolsets = candidate

    if resolved_toolsets:
        if not resolved_toolsets.exists():
            raise FileNotFoundError(f"Toolsets artifact not found: {resolved_toolsets}")
        with open(resolved_toolsets) as f:
            toolsets = yaml.safe_load(f) or {}
        resolve_schema_version(toolsets, artifact="toolsets artifact", allow_legacy=False)

    manager = LockfileManager(lockfile_path)
    manager.load()

    resolved_policy: Path | None = None
    if policy_path:
        resolved_policy = Path(policy_path)
    else:
        candidate_policy = Path(tools_path).parent / "policy.yaml"
        if candidate_policy.exists():
            resolved_policy = candidate_policy

    artifacts_digest = compute_artifacts_digest_from_paths(
        tools_path=tools_path,
        toolsets_path=resolved_toolsets,
        policy_path=resolved_policy,
    )

    changes = manager.sync_from_manifest(
        manifest=manifest,
        capture_id=capture_id,
        scope=scope,
        toolsets=toolsets,
        deterministic=deterministic,
        prune_removed=prune_removed,
    )
    manager.set_artifacts_digest(artifacts_digest)
    if evidence_summary_sha256:
        manager.set_evidence_summary_sha256(evidence_summary_sha256)
    manager.save()

    pending = manager.get_pending()
    return ApprovalSyncResult(
        lockfile_path=manager.lockfile_path,
        artifacts_digest=artifacts_digest,
        changes=changes,
        has_pending=bool(pending),
        pending_count=len(pending),
    )


def run_approve_sync(
    tools_path: str,
    policy_path: str | None,
    toolsets_path: str | None,
    lockfile_path: str | None,
    capture_id: str | None,
    scope: str | None,
    verbose: bool,
    prune_removed: bool = False,
    deterministic: bool = True,
) -> None:
    """Sync lockfile with a tools manifest.

    Args:
        tools_path: Path to tools.json manifest
        toolsets_path: Path to toolsets.yaml artifact (optional)
        lockfile_path: Path to lockfile
        capture_id: Optional capture ID
        scope: Optional scope name
        verbose: Enable verbose output
    """
    if not policy_path and not (Path(tools_path).parent / "policy.yaml").exists():
        click.echo(
            "Warning: No policy.yaml provided/found; lockfile digest will not bind policy changes.",
            err=True,
        )

    try:
        result = sync_lockfile(
            tools_path=tools_path,
            policy_path=policy_path,
            toolsets_path=toolsets_path,
            lockfile_path=lockfile_path,
            capture_id=capture_id,
            scope=scope,
            prune_removed=prune_removed,
            deterministic=deterministic,
        )
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Report
    click.echo(f"Synced lockfile: {result.lockfile_path}")
    click.echo(f"  Artifacts digest: {result.artifacts_digest[:16]}...")
    click.echo(f"  New tools: {len(result.changes['new'])}")
    click.echo(f"  Modified: {len(result.changes['modified'])}")
    click.echo(f"  Removed: {len(result.changes['removed'])}")
    click.echo(f"  Unchanged: {len(result.changes['unchanged'])}")

    if verbose:
        manager = LockfileManager(result.lockfile_path)
        manager.load()

        if result.changes["new"]:
            click.echo("\nNew tools (pending approval):")
            for tool_identifier in result.changes["new"]:
                tool = manager.get_tool(tool_identifier)
                if tool:
                    click.echo(f"  - {tool.name} [{tool.risk_tier}] {tool.method} {tool.path}")

        if result.changes["modified"]:
            click.echo("\nModified tools (re-approval required):")
            for tool_identifier in result.changes["modified"]:
                tool = manager.get_tool(tool_identifier)
                if tool:
                    click.echo(f"  - {tool.name} [{tool.change_type}] {tool.method} {tool.path}")

    # Exit code based on pending status
    if result.has_pending:
        click.echo(f"\nWARNING: {result.pending_count} tools pending approval")
        sys.exit(1)
    else:
        click.echo("\nOK: All tools approved")


def run_approve_list(
    lockfile_path: str | None,
    status_filter: str | None,
    verbose: bool,
) -> None:
    """List tool approvals.

    Args:
        lockfile_path: Path to lockfile
        status_filter: Filter by status (pending, approved, rejected)
        verbose: Enable verbose output
    """
    manager = LockfileManager(lockfile_path)

    if not manager.exists():
        click.echo(f"No lockfile found at: {manager.lockfile_path}")
        click.echo("Run 'toolwright gate sync' first to create one.")
        sys.exit(1)

    manager.load()
    lockfile = manager.lockfile
    assert lockfile is not None

    # Filter tools
    if status_filter:
        try:
            status = ApprovalStatus(status_filter)
            tools = [t for t in lockfile.tools.values() if t.status == status]
        except ValueError:
            click.echo(f"Invalid status: {status_filter}", err=True)
            click.echo("Valid statuses: pending, approved, rejected")
            sys.exit(1)
    else:
        tools = list(lockfile.tools.values())

    # Display
    click.echo(f"Lockfile: {manager.lockfile_path}")
    click.echo(f"Total: {lockfile.total_tools} | Approved: {lockfile.approved_count} | Pending: {lockfile.pending_count} | Rejected: {lockfile.rejected_count}")
    click.echo()

    if not tools:
        click.echo("No tools found matching filter.")
        return

    for tool in sorted(tools, key=lambda t: t.name):
        status_icon = {
            ApprovalStatus.APPROVED: "[ok]",
            ApprovalStatus.PENDING: "[ ]",
            ApprovalStatus.REJECTED: "[x]",
        }[tool.status]

        risk_color = {
            "low": "green",
            "medium": "yellow",
            "high": "red",
            "critical": "bright_red",
        }.get(tool.risk_tier, "white")

        click.echo(
            f"  {status_icon} {tool.name} "
            f"[{click.style(tool.risk_tier, fg=risk_color)}] "
            f"{tool.method} {tool.path}"
        )

        if verbose:
            click.echo(f"      Host: {tool.host}")
            click.echo(f"      Signature: {tool.signature_id[:16]}...")
            click.echo(f"      Version: {tool.tool_version}")
            if tool.approved_by:
                click.echo(f"      Approved by: {tool.approved_by} at {tool.approved_at}")
            if tool.change_type:
                click.echo(f"      Change: {tool.change_type} at {tool.changed_at}")
            click.echo()


def run_approve_tool(
    tool_ids: tuple[str, ...],
    lockfile_path: str | None,
    all_pending: bool,
    toolset: str | None,
    approved_by: str | None,
    reason: str | None,
    root_path: str,
    verbose: bool,  # noqa: ARG001
) -> None:
    """Approve one or more tools.

    Args:
        tool_ids: Tool IDs to approve
        lockfile_path: Path to lockfile
        all_pending: Approve all pending tools
        toolset: Optional toolset name for scoped approvals
        approved_by: Who is approving
        reason: Optional reason recorded in approval metadata
        root_path: Canonical state root used for signing key storage
        verbose: Enable verbose output
    """
    manager = LockfileManager(lockfile_path)

    if not manager.exists():
        click.echo(f"No lockfile found at: {manager.lockfile_path}", err=True)
        sys.exit(1)

    manager.load()
    signer = ApprovalSigner(root_path=root_path)

    try:
        actor = resolve_approver(approved_by)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if all_pending:
        pending = manager.get_pending(toolset=toolset)
        count = 0
        for tool in pending:
            approval_time = datetime.now(UTC)
            if manager.approve(
                tool.signature_id or tool.tool_id,
                actor,
                toolset=toolset,
                reason=reason,
                approval_signature="pending",
                approval_alg=signer.algorithm,
                approval_key_id=signer.key_id,
                approved_at=approval_time,
            ):
                signature = signer.sign_approval(
                    tool=tool,
                    approved_by=actor,
                    approved_at=approval_time,
                    reason=reason,
                    mode=tool.approval_mode,
                )
                tool.approval_signature = signature
                tool.approval_alg = signer.algorithm
                tool.approval_key_id = signer.key_id
                count += 1
        manager.save()
        click.echo(f"Approved {count} tools")
        click.echo(f"Lockfile: {manager.lockfile_path}")
        snapshot_ok = _maybe_materialize_snapshot(manager, root_path=Path(root_path))
        if not snapshot_ok and count > 0:
            _print_snapshot_guidance()
        if count > 0:
            _print_next_steps_after_approval()
        return

    if not tool_ids:
        click.echo("Error: Specify tool IDs to approve or use --all", err=True)
        sys.exit(1)

    approved = []
    not_found = []

    for tool_id in tool_ids:
        existing = manager.get_tool(tool_id)
        if existing is None:
            not_found.append(tool_id)
            continue
        approval_time = datetime.now(UTC)
        if manager.approve(
            tool_id,
            actor,
            toolset=toolset,
            reason=reason,
            approval_signature="pending",
            approval_alg=signer.algorithm,
            approval_key_id=signer.key_id,
            approved_at=approval_time,
        ):
            signature = signer.sign_approval(
                tool=existing,
                approved_by=actor,
                approved_at=approval_time,
                reason=reason,
                mode=existing.approval_mode,
            )
            existing.approval_signature = signature
            existing.approval_alg = signer.algorithm
            existing.approval_key_id = signer.key_id
            approved.append(tool_id)
        else:
            not_found.append(tool_id)

    manager.save()

    if approved:
        click.echo(f"Approved: {', '.join(approved)}")
        click.echo(f"Lockfile: {manager.lockfile_path}")

    if not_found:
        click.echo(f"Not found: {', '.join(not_found)}", err=True)
        sys.exit(1)

    snapshot_ok = _maybe_materialize_snapshot(manager, root_path=Path(root_path))
    if not snapshot_ok and approved:
        _print_snapshot_guidance()
    if approved:
        _print_next_steps_after_approval()


def run_approve_reject(
    tool_ids: tuple[str, ...],
    lockfile_path: str | None,
    reason: str | None,
    verbose: bool,  # noqa: ARG001
) -> None:
    """Reject one or more tools.

    Args:
        tool_ids: Tool IDs to reject
        lockfile_path: Path to lockfile
        reason: Rejection reason
        verbose: Enable verbose output
    """
    manager = LockfileManager(lockfile_path)

    if not manager.exists():
        click.echo(f"No lockfile found at: {manager.lockfile_path}", err=True)
        sys.exit(1)

    manager.load()

    if not tool_ids:
        click.echo("Error: Specify tool IDs to reject", err=True)
        sys.exit(1)

    rejected = []
    not_found = []

    for tool_id in tool_ids:
        if manager.reject(tool_id, reason):
            rejected.append(tool_id)
        else:
            not_found.append(tool_id)

    manager.save()

    if rejected:
        click.echo(f"Rejected: {', '.join(rejected)}")

    if not_found:
        click.echo(f"Not found: {', '.join(not_found)}", err=True)
        sys.exit(1)


def run_approve_snapshot(
    lockfile_path: str | None,
    root_path: str,
    verbose: bool,
    snapshot_dir: str | None = None,
) -> None:
    """Materialize baseline snapshot for an approved lockfile."""
    manager = LockfileManager(lockfile_path)

    if not manager.exists():
        click.echo(f"No lockfile found at: {manager.lockfile_path}")
        click.echo("Run 'toolwright gate sync' first.")
        sys.exit(2)

    manager.load()
    approvals_passed, message = manager.check_approvals()
    if not approvals_passed:
        click.echo(f"Cannot snapshot: {message}")
        sys.exit(1)

    _materialize_snapshot(
        manager,
        verbose=verbose,
        require_toolpack=True,
        root_path=Path(root_path),
        snapshot_dir_override=Path(snapshot_dir) if snapshot_dir else None,
    )


def run_approve_check(
    lockfile_path: str | None,
    toolset: str | None,
    verbose: bool,
) -> None:
    """Check if all tools are approved (for CI).

    Args:
        lockfile_path: Path to lockfile
        toolset: Optional toolset name for scoped CI checks
        verbose: Enable verbose output
    """
    manager = LockfileManager(lockfile_path)

    if not manager.exists():
        click.echo(f"No lockfile found at: {manager.lockfile_path}")
        click.echo("Run 'toolwright gate sync' first.")
        sys.exit(2)

    manager.load()

    passed, message = manager.check_ci(toolset=toolset)

    if passed:
        click.echo(f"OK: {message}")
        sys.exit(0)
    else:
        click.echo(f"FAIL: {message}")

        pending = manager.get_pending(toolset=toolset)
        if pending:
            if verbose:
                click.echo("\nPending tools:")
                for tool in pending:
                    click.echo(f"  - {tool.name} [{tool.risk_tier}] {tool.method} {tool.path}")

            pending_names = ", ".join(t.name for t in pending[:5])
            if len(pending) > 5:
                pending_names += f" (and {len(pending) - 5} more)"
            click.echo("\nApprove with:")
            click.echo(f"  toolwright gate allow --all --lockfile {manager.lockfile_path}")

        sys.exit(1)


def run_approve_resign(
    lockfile_path: str | None,
    toolset: str | None,
    root_path: str,
    verbose: bool,
) -> None:
    """Re-sign existing approval signatures (migration / repair helper).

    This is intended for cases where the signature payload changes (for example, to bind
    additional fields like toolset approvals) and existing lockfiles must be re-signed.
    """
    manager = LockfileManager(lockfile_path)

    if not manager.exists():
        click.echo(f"No lockfile found at: {manager.lockfile_path}")
        click.echo("Run 'toolwright gate sync' first.")
        sys.exit(2)

    manager.load()
    assert manager.lockfile is not None

    signer = ApprovalSigner(root_path=root_path)
    count = 0

    for tool in manager.lockfile.tools.values():
        if toolset and toolset not in tool.toolsets:
            continue
        if not tool.approved_by or tool.approved_at is None:
            continue
        if not tool.approval_signature:
            continue

        signature = signer.sign_approval(
            tool=tool,
            approved_by=str(tool.approved_by),
            approved_at=tool.approved_at,
            reason=tool.approval_reason,
            mode=tool.approval_mode,
        )
        tool.approval_signature = signature
        tool.approval_alg = signer.algorithm
        tool.approval_key_id = signer.key_id
        count += 1

    manager.save()
    click.echo(f"Re-signed {count} tools")

    # Make the result portable for MCP clients that run with `--root <toolpack>/.toolwright`.
    from toolwright.core.approval.snapshot import resolve_toolpack_root

    toolpack_root = resolve_toolpack_root(manager.lockfile_path)
    if toolpack_root is not None:
        _seed_toolpack_trust_store(
            source_root=Path(root_path),
            toolpack_root=toolpack_root,
            verbose=verbose,
        )


def _warn_if_gitignored(snapshot_dir: Path) -> None:
    """Emit a warning if *snapshot_dir* is inside a gitignored path."""
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(snapshot_dir)],
            capture_output=True,
            cwd=snapshot_dir.parent if snapshot_dir.parent.exists() else None,
        )
        if result.returncode == 0:
            click.echo(
                "Warning: snapshot dir is gitignored; "
                "CI will not be able to verify the baseline",
                err=True,
            )
    except FileNotFoundError:
        pass  # git not installed -- skip check


def _materialize_snapshot(
    manager: LockfileManager,
    *,
    verbose: bool,
    require_toolpack: bool,
    root_path: Path,
    snapshot_dir_override: Path | None = None,
) -> None:
    toolpack_root = resolve_toolpack_root(manager.lockfile_path)
    if toolpack_root is None:
        if require_toolpack:
            click.echo("toolpack.yaml not found; cannot materialize snapshot", err=True)
            sys.exit(1)
        return

    result = materialize_snapshot(manager.lockfile_path, snapshot_dir=snapshot_dir_override)
    relative_dir = result.snapshot_dir.relative_to(toolpack_root)
    manager.set_baseline_snapshot(str(relative_dir), result.digest)
    manager.save()

    _warn_if_gitignored(result.snapshot_dir)

    if verbose:
        status = "created" if result.created else "reused"
        click.echo(f"Baseline snapshot {status}: {relative_dir}")

    _seed_toolpack_trust_store(
        source_root=root_path,
        toolpack_root=toolpack_root,
        verbose=verbose,
    )

    _promote_toolpack_lockfile(manager, toolpack_root=toolpack_root, verbose=verbose)


def _promote_toolpack_lockfile(
    manager: LockfileManager,
    *,
    toolpack_root: Path,
    verbose: bool,
) -> None:
    """Promote a fully-approved toolpack pending lockfile to canonical name.

    Toolpack minting creates `lockfile/toolwright.lock.pending.yaml`, but runtime rejects
    pending lockfiles (by filename). Once all tools are approved, we write a copy to
    `lockfile/toolwright.lock.yaml` and update toolpack.yaml to reference it.
    """
    approvals_passed, _message = manager.check_approvals()
    if not approvals_passed:
        return

    pending_path = manager.lockfile_path
    if ".pending." not in pending_path.name:
        return

    approved_name = pending_path.name.replace(".pending.", ".")
    if approved_name == pending_path.name:
        approved_name = pending_path.name.replace(".pending", "")
    approved_path = pending_path.with_name(approved_name)

    atomic_write_text(
        approved_path,
        pending_path.read_text(encoding="utf-8"),
    )

    toolpack_file = toolpack_root / "toolpack.yaml"
    try:
        toolpack = load_toolpack(toolpack_file)
    except Exception:
        return

    rel = approved_path.relative_to(toolpack_root)
    toolpack.paths.lockfiles["approved"] = str(rel)
    write_toolpack(toolpack, toolpack_file)

    if verbose:
        click.echo(f"Approved lockfile: {rel}")


def _maybe_materialize_snapshot(manager: LockfileManager, *, root_path: Path) -> bool:
    """Try to materialize a snapshot. Returns True if snapshot was created."""
    approvals_passed, _message = manager.check_approvals()
    if not approvals_passed:
        return False
    toolpack_root = resolve_toolpack_root(manager.lockfile_path)
    if toolpack_root is None:
        return False
    _materialize_snapshot(
        manager,
        verbose=False,
        require_toolpack=False,
        root_path=root_path,
    )
    return True


def _print_snapshot_guidance() -> None:
    """Print guidance when snapshot couldn't be auto-materialized after approval."""
    click.echo(
        "\nNote: No toolpack.yaml found -- baseline snapshot was not materialized."
    )
    click.echo(
        "  If using a toolpack, run: toolwright gate snapshot --lockfile <path>"
    )
    click.echo(
        "  This is required before 'toolwright gate check' will pass."
    )


def _print_next_steps_after_approval() -> None:
    """Print what the user should do after approving tools."""
    click.echo("\nNext: toolwright serve --toolpack <path>")
    click.echo("  Or:  toolwright config --toolpack <path>  (prints MCP client snippet)")


def _seed_toolpack_trust_store(
    *,
    source_root: Path,
    toolpack_root: Path,
    verbose: bool,
) -> None:
    """Seed portable trust material into a toolpack-local root.

    Claude Desktop configs intentionally use a toolpack-local `--root <toolpack_root>/.toolwright`
    so the MCP server can start regardless of its current working directory. For signed approvals
    to verify under that root, we must copy the trust store containing the signer public keys.
    """
    resolved_source = source_root.resolve()
    source_trust_store = resolved_source / "state" / "keys" / "trusted_signers.json"
    if not source_trust_store.exists():
        if verbose:
            click.echo(
                f"Warning: trust store not found, cannot seed toolpack root: {source_trust_store}",
                err=True,
            )
        return

    toolpack_state_root = (toolpack_root / ".toolwright").resolve()
    dest_trust_store = toolpack_state_root / "state" / "keys" / "trusted_signers.json"
    dest_trust_store.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        dest_trust_store,
        source_trust_store.read_text(encoding="utf-8"),
    )
    os.chmod(dest_trust_store, 0o600)
