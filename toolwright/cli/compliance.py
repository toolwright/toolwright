"""CLI implementation for compliance reporting."""

from __future__ import annotations

import json
from pathlib import Path

import click


def run_compliance_report(
    tools_path: str | None = None,
    output_path: str | None = None,
) -> None:
    """Generate a structured compliance report."""
    from toolwright.core.compliance.report import ComplianceReporter

    manifest = None
    if tools_path:
        with open(tools_path) as f:
            manifest = json.load(f)

    reporter = ComplianceReporter()
    report_data = reporter.generate(tools_manifest=manifest)

    output = json.dumps(report_data, indent=2)
    if output_path:
        Path(output_path).write_text(output)
        click.echo(f"Compliance report written to {output_path}")
    else:
        click.echo(output)
