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
    shape_baselines: str | None = None,
    tool: str | None = None,
    response_file: str | None = None,
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
        shape_baselines: Path to shape_baselines.json for shape-based drift
        tool: Tool name for shape-based drift detection
        response_file: Path to JSON response body for shape-based drift
    """
    # Shape-based drift detection mode
    if shape_baselines:
        run_shape_drift(
            shape_baselines_path=shape_baselines,
            tool=tool,
            response_file=response_file,
            verbose=verbose,
        )
        return

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


def run_shape_drift(
    shape_baselines_path: str,
    tool: str | None,
    response_file: str | None,
    verbose: bool,
) -> None:
    """Run shape-based drift detection for a single tool.

    Args:
        shape_baselines_path: Path to shape_baselines.json.
        tool: Tool name to check. If None, lists available tools.
        response_file: Path to JSON response body to compare.
        verbose: Enable verbose output.
    """
    from toolwright.core.drift.baselines import detect_drift_for_tool
    from toolwright.core.drift.shape_diff import DriftSeverity
    from toolwright.models.baseline import BaselineIndex

    baselines_file = Path(shape_baselines_path)
    if not baselines_file.exists():
        click.echo(f"Error: Shape baselines file not found: {shape_baselines_path}", err=True)
        sys.exit(1)

    index = BaselineIndex.load(baselines_file)

    if not index.baselines:
        click.echo("No shape baselines found in file.", err=True)
        sys.exit(1)

    # List mode: show available tools
    if not tool:
        from toolwright.utils.text import pluralize

        click.echo(f"\nShape baselines ({pluralize(len(index.baselines), 'tool')}):\n")
        for name, bl in sorted(index.baselines.items()):
            fields = len(bl.shape.fields)
            samples = bl.shape.sample_count
            click.echo(f"  {name:<40} {fields} fields, {samples} samples")
        click.echo("\nCheck a tool: toolwright drift --shape-baselines ... --tool <name> --response-file <file>")
        return

    if not response_file:
        click.echo("Error: --response-file is required with --tool for shape drift detection", err=True)
        sys.exit(1)

    response_path = Path(response_file)
    if not response_path.exists():
        click.echo(f"Error: Response file not found: {response_file}", err=True)
        sys.exit(1)

    with open(response_path) as f:
        body = json.load(f)

    if verbose:
        click.echo(f"Tool: {tool}")
        click.echo(f"Baselines: {shape_baselines_path}")
        click.echo(f"Response: {response_file}")

    result = detect_drift_for_tool(tool, body, index)

    if result.error:
        click.echo(f"Error: {result.error}", err=True)
        sys.exit(1)

    # Print results
    click.echo(f"\nShape Drift: {tool}")
    click.echo(f"  Changes: {len(result.changes)}")
    click.echo(f"  Severity: {result.severity.value if result.severity else 'none'}")

    if result.changes:
        click.echo("\nChanges:")
        for change in result.changes:
            severity_label = change.severity.value.upper()
            click.echo(f"  [{severity_label}] {change.change_type.value}: {change.description}")

    if result.severity == DriftSeverity.MANUAL:
        click.echo("\nMANUAL REVIEW REQUIRED")
        sys.exit(2)
    elif result.severity == DriftSeverity.APPROVAL_REQUIRED:
        click.echo("\nAPPROVAL REQUIRED")
        sys.exit(1)
    else:
        if not result.changes:
            click.echo("\nNo drift detected.")
        sys.exit(0)


@click.command("status")
@click.option(
    "--events-path",
    type=click.Path(),
    default=".toolwright/state/drift_events.jsonl",
    show_default=True,
    help="Path to drift events JSONL file.",
)
@click.option(
    "--limit", "-n",
    type=int,
    default=20,
    show_default=True,
    help="Number of recent events to show.",
)
def drift_status(events_path: str, limit: int) -> None:
    """Show recent shape drift events.

    Reads the drift_events.jsonl log produced by the shape probe loop
    and displays recent drift detections with severity and tool info.

    \b
    Examples:
      toolwright drift status
      toolwright drift status --events-path /path/to/drift_events.jsonl
      toolwright drift status -n 50
    """
    events_file = Path(events_path)

    if not events_file.exists():
        click.echo("No drift events found. The shape probe loop has not logged any events yet.")
        return

    lines = events_file.read_text().strip().split("\n")
    if not lines or lines == [""]:
        click.echo("No drift events found. The shape probe loop has not logged any events yet.")
        return

    events = [json.loads(line) for line in lines[-limit:]]

    click.echo(f"\nRecent Drift Events ({len(events)} of {len(lines)} total):\n")
    for event in events:
        severity = event.get("severity", "unknown").upper()
        tool = event.get("tool_name", "unknown")
        timestamp = event.get("timestamp", "")[:19]
        changes = event.get("changes", [])
        change_count = len(changes)

        click.echo(f"  [{severity}] {tool} — {change_count} change(s) at {timestamp}")
        for change in changes[:3]:  # Show first 3 changes
            click.echo(f"    {change.get('change_type', '')}: {change.get('description', '')}")
        if change_count > 3:
            click.echo(f"    ... and {change_count - 3} more")
