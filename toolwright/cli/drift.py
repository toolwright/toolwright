"""Drift command implementation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from toolwright.core.drift import DriftEngine
from toolwright.core.normalize import EndpointAggregator
from toolwright.models.drift import DriftReport
from toolwright.storage import Storage
from toolwright.utils.schema_version import resolve_schema_version


def run_drift(
    from_capture: str | None,
    to_capture: str | None,
    baseline: str | None,
    capture_id: str | None,
    capture_path: str | None,
    output_dir: str,
    output_format: str,
    verbose: bool,
    deterministic: bool = True,
    root_path: str = ".toolwright",
) -> None:
    """Run the drift command.

    Args:
        from_capture: ID of the 'from' capture for comparison
        to_capture: ID of the 'to' capture for comparison
        baseline: Path to baseline.json file
        capture_id: Capture ID to compare against baseline
        output_dir: Directory for output files
        output_format: Output format (json, markdown, both)
        verbose: Enable verbose output
        deterministic: Use deterministic report IDs and generated_at metadata
    """
    storage = Storage(base_path=root_path)
    engine = DriftEngine()

    if from_capture and to_capture:
        # Compare two captures
        report = _compare_captures(
            storage, engine, from_capture, to_capture, verbose, deterministic
        )
    elif baseline and (capture_id or capture_path):
        if capture_id and capture_path:
            click.echo(
                "Error: Provide only one of --capture-id or --capture-path for baseline comparison",
                err=True,
            )
            sys.exit(1)
        # Compare capture against baseline
        report = _compare_to_baseline(
            storage,
            engine,
            baseline,
            capture_id or capture_path or "",
            verbose,
            deterministic,
        )
    else:
        click.echo(
            "Error: Specify --from/--to for capture comparison "
            "OR --baseline with --capture-id/--capture-path for baseline comparison",
            err=True,
        )
        sys.exit(1)

    # Output results
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    artifacts_created = []

    if output_format in ("json", "both"):
        json_path = output_path / "drift.json"
        with open(json_path, "w") as f:
            f.write(engine.to_json(report))
        artifacts_created.append(("Drift Report (JSON)", json_path))

    if output_format in ("markdown", "both"):
        md_path = output_path / "drift.md"
        with open(md_path, "w") as f:
            f.write(engine.to_markdown(report))
        artifacts_created.append(("Drift Report (Markdown)", md_path))

    # Print summary
    click.echo(f"\nDrift Detection Complete: {report.id}")
    click.echo(f"  Total Drifts: {report.total_drifts}")
    click.echo(f"  Breaking: {report.breaking_count}")
    click.echo(f"  Auth: {report.auth_count}")
    click.echo(f"  Risk: {report.risk_count}")
    click.echo(f"  Additive: {report.additive_count}")
    click.echo(f"  Schema: {report.schema_count}")
    click.echo(f"  Parameter: {report.parameter_count}")

    if report.has_breaking_changes:
        click.echo("\n⚠️  BREAKING CHANGES DETECTED")
    elif report.requires_review:
        click.echo("\n⚠️  Review recommended (risk changes detected)")

    click.echo(f"\nExit Code: {report.exit_code}")
    if artifacts_created:
        click.echo("\nArtifacts:")
        for name, path in artifacts_created:
            click.echo(f"  - {name}: {path}")

    # Exit with appropriate code for CI
    sys.exit(report.exit_code)


def _compare_captures(
    storage: Storage,
    engine: DriftEngine,
    from_capture: str,
    to_capture: str,
    verbose: bool,
    deterministic: bool,
) -> DriftReport:
    """Compare two captures."""

    # Load from capture
    from_session = storage.load_capture(from_capture)
    if not from_session:
        click.echo(f"Error: From capture not found: {from_capture}", err=True)
        sys.exit(1)

    # Load to capture
    to_session = storage.load_capture(to_capture)
    if not to_session:
        click.echo(f"Error: To capture not found: {to_capture}", err=True)
        sys.exit(1)

    if verbose:
        click.echo(f"From: {from_session.id} ({len(from_session.exchanges)} exchanges)")
        click.echo(f"To: {to_session.id} ({len(to_session.exchanges)} exchanges)")

    # Aggregate endpoints
    from_aggregator = EndpointAggregator(first_party_hosts=from_session.allowed_hosts)
    from_endpoints = from_aggregator.aggregate(from_session)

    to_aggregator = EndpointAggregator(first_party_hosts=to_session.allowed_hosts)
    to_endpoints = to_aggregator.aggregate(to_session)

    if verbose:
        click.echo(f"From endpoints: {len(from_endpoints)}")
        click.echo(f"To endpoints: {len(to_endpoints)}")
        click.echo("Running drift detection...")

    # Run comparison
    return engine.compare(
        from_endpoints,
        to_endpoints,
        from_capture_id=from_capture,
        to_capture_id=to_capture,
        deterministic=deterministic,
    )


def _compare_to_baseline(
    storage: Storage,
    engine: DriftEngine,
    baseline_path: str,
    capture_id: str,
    verbose: bool,
    deterministic: bool,
) -> DriftReport:
    """Compare capture against baseline."""

    # Load baseline
    baseline_file = Path(baseline_path)
    if not baseline_file.exists():
        click.echo(f"Error: Baseline file not found: {baseline_path}", err=True)
        sys.exit(1)

    with open(baseline_file) as f:
        baseline = json.load(f)
    resolve_schema_version(baseline, artifact="baseline", allow_legacy=True)

    if verbose:
        click.echo(f"Baseline: {baseline.get('capture_id', 'unknown')}")
        click.echo(f"  Endpoints: {baseline.get('endpoint_count', len(baseline.get('endpoints', [])))}")

    # Load capture
    session = storage.load_capture(capture_id)
    if not session:
        click.echo(f"Error: Capture not found: {capture_id}", err=True)
        sys.exit(1)

    if verbose:
        click.echo(f"Capture: {session.id} ({len(session.exchanges)} exchanges)")

    # Aggregate endpoints
    aggregator = EndpointAggregator(first_party_hosts=session.allowed_hosts)
    endpoints = aggregator.aggregate(session)

    if verbose:
        click.echo(f"Current endpoints: {len(endpoints)}")
        click.echo("Running drift detection...")

    # Run comparison
    return engine.compare_to_baseline(baseline, endpoints, deterministic=deterministic)
