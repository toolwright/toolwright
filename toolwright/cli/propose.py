"""Propose CLI commands — manage agent draft proposals."""

from __future__ import annotations

import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

import click
import yaml


def run_propose_list(*, root: str, status: str | None) -> None:
    """List pending proposals."""
    from toolwright.core.proposal.engine import ProposalEngine
    from toolwright.models.proposal import ProposalStatus

    engine = ProposalEngine(Path(root))
    filter_status = ProposalStatus(status) if status else None
    proposals = engine.list_proposals(status=filter_status)

    if not proposals:
        click.echo("No proposals found.")
        return

    for p in proposals:
        cap = p.capability
        click.echo(
            f"  {p.proposal_id}  [{p.status}]  "
            f"tool={cap.suggested_tool or '?'}  "
            f"risk={cap.risk_guess}  "
            f"reason={cap.reason_code}"
        )


def run_propose_show(*, root: str, proposal_id: str) -> None:
    """Show proposal details."""
    from toolwright.core.proposal.engine import ProposalEngine

    engine = ProposalEngine(Path(root))
    proposal = engine.get_proposal(proposal_id)
    if proposal is None:
        click.echo(f"Proposal '{proposal_id}' not found.", err=True)
        sys.exit(1)

    cap = proposal.capability
    click.echo(f"Proposal: {proposal.proposal_id}")
    click.echo(f"  Status: {proposal.status}")
    click.echo(f"  Created: {proposal.created_at}")
    click.echo(f"  Reason code: {cap.reason_code}")
    click.echo(f"  Attempted action: {cap.attempted_action}")
    click.echo(f"  Suggested tool: {cap.suggested_tool or 'none'}")
    click.echo(f"  Suggested host: {cap.suggested_host or 'none'}")
    click.echo(f"  Risk guess: {cap.risk_guess}")
    if cap.agent_context:
        click.echo(f"  Agent context: {cap.agent_context}")
    if proposal.reviewed_at:
        click.echo(f"  Reviewed at: {proposal.reviewed_at}")
        click.echo(f"  Reviewed by: {proposal.reviewed_by}")
    if proposal.rejection_reason:
        click.echo(f"  Rejection reason: {proposal.rejection_reason}")


def run_propose_approve(*, root: str, proposal_id: str, reviewed_by: str) -> None:
    """Approve a proposal."""
    from toolwright.core.proposal.engine import ProposalEngine

    engine = ProposalEngine(Path(root))
    result = engine.approve(proposal_id, reviewed_by=reviewed_by)
    if result is None:
        click.echo(f"Proposal '{proposal_id}' not found.", err=True)
        sys.exit(1)
    click.echo(f"Proposal '{proposal_id}' approved by {reviewed_by}.")


def run_propose_reject(*, root: str, proposal_id: str, reason: str, reviewed_by: str) -> None:
    """Reject a proposal."""
    from toolwright.core.proposal.engine import ProposalEngine

    engine = ProposalEngine(Path(root))
    result = engine.reject(proposal_id, reason=reason, reviewed_by=reviewed_by)
    if result is None:
        click.echo(f"Proposal '{proposal_id}' not found.", err=True)
        sys.exit(1)
    click.echo(f"Proposal '{proposal_id}' rejected.")


def run_propose_from_capture(
    *,
    root: str,
    capture_id: str,
    scope_name: str,
    scope_file: str | None,
    output_dir: str | None,
    deterministic: bool,
    verbose: bool,
) -> None:
    """Generate endpoint catalog + tool proposals from a capture."""
    from toolwright.core.normalize import EndpointAggregator
    from toolwright.core.proposal.compiler import ProposalCompiler
    from toolwright.core.scope import ScopeEngine
    from toolwright.storage import Storage

    storage = Storage(base_path=root)
    session = storage.load_capture(capture_id)
    if not session:
        click.echo(f"Error: Capture not found: {capture_id}", err=True)
        sys.exit(1)

    aggregator = EndpointAggregator(first_party_hosts=session.allowed_hosts)
    endpoints = aggregator.aggregate(session)

    scope_engine = ScopeEngine(first_party_hosts=session.allowed_hosts)
    try:
        scope = scope_engine.load_scope(scope_name, scope_file)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    filtered = scope_engine.filter_endpoints(endpoints, scope)
    filtered = sorted(
        filtered,
        key=lambda ep: (ep.host, ep.method.upper(), ep.path, ep.signature_id),
    )

    compiler = ProposalCompiler()
    catalog = compiler.build_endpoint_catalog(
        capture_id=session.id,
        scope_name=scope.name,
        endpoints=filtered,
        session=session,
    )
    proposals = compiler.build_tool_proposals(catalog)
    questions = compiler.build_questions(catalog, proposals)

    output_root = Path(output_dir) if output_dir else Path(root) / "proposals"
    output_root.mkdir(parents=True, exist_ok=True)
    proposal_dir = output_root / _proposal_artifact_id(
        capture_id=session.id,
        scope_name=scope.name,
        deterministic=deterministic,
    )
    proposal_dir.mkdir(parents=True, exist_ok=True)

    endpoint_catalog_path = proposal_dir / "endpoint_catalog.yaml"
    tools_proposed_path = proposal_dir / "tools.proposed.yaml"
    questions_path = proposal_dir / "questions.yaml"

    endpoint_catalog_path.write_text(
        yaml.safe_dump(catalog.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    tools_proposed_path.write_text(
        yaml.safe_dump(proposals.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    questions_path.write_text(
        yaml.safe_dump(questions.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )

    click.echo(f"Generated proposal artifacts: {proposal_dir}")
    click.echo(f"  Endpoint families: {len(catalog.families)}")
    click.echo(f"  Tool proposals: {len(proposals.proposals)}")
    click.echo(f"  Questions: {len(questions.questions)}")
    click.echo("Artifacts:")
    click.echo("  - endpoint_catalog.yaml")
    click.echo("  - tools.proposed.yaml")
    click.echo("  - questions.yaml")

    if verbose and questions.questions:
        click.echo("\nFollow-up capture questions:")
        for question in questions.questions:
            click.echo(f"  - {question.prompt}")


def run_propose_publish(
    *,
    root: str,
    proposal_input: str,
    output_dir: str | None,
    min_confidence: float,
    max_risk: str,
    include_review_required: bool,
    proposal_ids: tuple[str, ...],
    sync_lockfile_enabled: bool,
    lockfile_path: str | None,
    deterministic: bool,
    verbose: bool,
) -> None:
    """Publish proposal artifacts into runtime-ready tools/policy/toolsets."""
    from toolwright.cli.approve import sync_lockfile
    from toolwright.core.proposal.publisher import ProposalPublisher

    proposals_path = _resolve_proposal_input(Path(proposal_input))
    output_root = Path(output_dir) if output_dir else Path(root) / "published"

    try:
        result = ProposalPublisher().publish(
            proposals_path=proposals_path,
            output_root=output_root,
            min_confidence=min_confidence,
            max_risk=max_risk,
            include_review_required=include_review_required,
            proposal_ids=proposal_ids,
            deterministic=deterministic,
        )
    except (ValueError, FileNotFoundError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    click.echo(f"Published proposal bundle: {result.bundle_path}")
    click.echo(f"  Selected tools: {result.selected_count}")
    click.echo(f"  Excluded proposals: {len(result.excluded)}")
    click.echo("Artifacts:")
    click.echo("  - tools.json")
    click.echo("  - toolsets.yaml")
    click.echo("  - policy.yaml")
    click.echo("  - publish_report.json")

    if verbose and result.excluded:
        click.echo("\nExcluded proposals:")
        for proposal in result.excluded:
            reason = ",".join(proposal.reasons)
            click.echo(f"  - {proposal.proposal_id} ({proposal.name}): {reason}")

    if not sync_lockfile_enabled:
        return

    sync_result = sync_lockfile(
        tools_path=str(result.tools_path),
        policy_path=str(result.policy_path),
        toolsets_path=str(result.toolsets_path),
        lockfile_path=lockfile_path,
        capture_id=result.capture_id,
        scope=result.scope,
        deterministic=deterministic,
    )
    click.echo(f"\nLockfile synced: {sync_result.lockfile_path}")
    click.echo(f"  New tools: {len(sync_result.changes['new'])}")
    click.echo(f"  Modified: {len(sync_result.changes['modified'])}")
    click.echo(f"  Removed: {len(sync_result.changes['removed'])}")
    click.echo(f"  Pending approvals: {sync_result.pending_count}")


def _proposal_artifact_id(
    *,
    capture_id: str,
    scope_name: str,
    deterministic: bool,
) -> str:
    """Build deterministic or volatile proposal artifact directory names."""
    if deterministic:
        canonical = f"{capture_id}:{scope_name}:proposal"
        return f"proposal_{hashlib.sha256(canonical.encode()).hexdigest()[:12]}"
    return f"proposal_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"


def _resolve_proposal_input(proposal_input: Path) -> Path:
    """Resolve proposal file path from input (dir or tools.proposed.yaml path)."""
    if proposal_input.is_dir():
        candidate = proposal_input / "tools.proposed.yaml"
        if not candidate.exists():
            raise FileNotFoundError(
                f"Proposal directory does not contain tools.proposed.yaml: {proposal_input}"
            )
        return candidate

    if proposal_input.name != "tools.proposed.yaml":
        raise FileNotFoundError(
            f"Expected tools.proposed.yaml, got: {proposal_input}"
        )
    return proposal_input
