"""Repair command — diagnose issues and propose fixes."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click


def run_repair(
    *,
    toolpack_path: str,
    context_paths: list[str],
    output_dir: str | None,
    auto_discover: bool,
    verbose: bool,
    root_path: str,
) -> None:
    """Diagnose toolpack issues and propose remediation patches."""
    from toolwright.core.repair.engine import RepairEngine
    from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

    tp_path = Path(toolpack_path)
    if not tp_path.exists():
        click.echo(f"Error: Toolpack not found: {tp_path}", err=True)
        sys.exit(2)

    try:
        toolpack = load_toolpack(tp_path)
        resolved = resolve_toolpack_paths(toolpack=toolpack, toolpack_path=tp_path)
    except Exception as exc:
        click.echo(f"Error loading toolpack: {exc}", err=True)
        sys.exit(2)

    engine = RepairEngine(
        toolpack=toolpack,
        toolpack_path=tp_path.resolve(),
        resolved=resolved,
    )

    parsed_paths = [Path(p) for p in context_paths]
    report = engine.run(
        context_paths=parsed_paths,
        auto_discover=auto_discover,
    )

    # Resolve output directory
    out = _resolve_output_dir(output_dir, root_path)
    out.mkdir(parents=True, exist_ok=True)

    # Write artifacts
    _write_repair_json(out, report)
    _write_repair_md(out, report)
    _write_commands_sh(out, report)
    _write_diagnosis_json(out, report)

    # Print summary to stdout
    _print_summary(report, out, verbose)

    sys.exit(report.exit_code)


def _resolve_output_dir(output_dir: str | None, root_path: str) -> Path:
    """Resolve output directory, defaulting to <root>/repairs/<timestamp>_repair/."""
    if output_dir:
        return Path(output_dir)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%SZ")
    return Path(root_path) / "repairs" / f"{timestamp}_repair"


def _write_repair_json(out: Path, report: Any) -> None:
    """Write repair.json — full structured report."""
    data = report.model_dump(mode="json")
    (out / "repair.json").write_text(
        json.dumps(data, indent=2, sort_keys=False),
        encoding="utf-8",
    )


def _write_diagnosis_json(out: Path, report: Any) -> None:
    """Write diagnosis.json — just the diagnosis section."""
    data = report.diagnosis.model_dump(mode="json")
    (out / "diagnosis.json").write_text(
        json.dumps(data, indent=2, sort_keys=False),
        encoding="utf-8",
    )


def _write_repair_md(out: Path, report: Any) -> None:
    """Write repair.md — human-readable markdown report."""
    lines: list[str] = []
    lines.append(f"# Repair Report — {report.toolpack_id}")
    lines.append("")
    lines.append(f"**Generated:** {report.generated_at}")
    lines.append(f"**Toolpack:** `{report.toolpack_path}`")
    lines.append(f"**Schema version:** {report.repair_schema_version}")
    lines.append("")

    # Summary
    diag = report.diagnosis
    plan = report.patch_plan
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Issues found:** {diag.total_issues}")
    lines.append(f"- **Patches proposed:** {plan.total_patches}")
    lines.append(f"  - Safe: {plan.safe_count}")
    lines.append(f"  - Approval required: {plan.approval_required_count}")
    lines.append(f"  - Manual: {plan.manual_count}")
    lines.append("")

    # Exit code
    if report.exit_code == 0:
        lines.append("> System is healthy. No action needed.")
    else:
        lines.append("> Issues detected. Review patches below.")
    lines.append("")

    # Diagnosis details
    if diag.items:
        lines.append("## Diagnosis")
        lines.append("")
        lines.append("| Severity | Source | Title |")
        lines.append("|----------|--------|-------|")
        for item in diag.items:
            lines.append(f"| {item.severity.value} | {item.source.value} | {item.title} |")
        lines.append("")

    # Patch plan
    if plan.patches:
        lines.append("## Patch Plan")
        lines.append("")
        for patch in plan.patches:
            lines.append(f"### {patch.title}")
            lines.append("")
            lines.append(f"- **Kind:** {patch.kind.value}")
            lines.append(f"- **Action:** {patch.action.value}")
            lines.append(f"- **Description:** {patch.description}")
            lines.append(f"- **Reason:** {patch.reason}")
            if patch.risk_note:
                lines.append(f"- **Risk:** {patch.risk_note}")
            lines.append("")
            lines.append("```sh")
            lines.append(patch.cli_command)
            lines.append("```")
            lines.append("")

    # Context files used
    if diag.context_files_used:
        lines.append("## Context Files Used")
        lines.append("")
        for f in diag.context_files_used:
            lines.append(f"- `{f}`")
        lines.append("")

    # Verify snapshot
    if report.verify_before:
        lines.append("## Pre-Repair Verification")
        lines.append("")
        lines.append(f"- **Status:** {report.verify_before.verify_status}")
        lines.append("")

    # Redaction
    if report.redaction_summary.redacted_field_count > 0:
        lines.append("## Redaction")
        lines.append("")
        lines.append(f"- **Fields redacted:** {report.redaction_summary.redacted_field_count}")
        lines.append(f"- **Keys:** {', '.join(report.redaction_summary.redacted_keys)}")
        lines.append("")

    (out / "repair.md").write_text("\n".join(lines), encoding="utf-8")


def _write_commands_sh(out: Path, report: Any) -> None:
    """Write patch.commands.sh — copy-pasteable commands."""
    lines = [
        "#!/usr/bin/env bash",
        f"# Repair commands for {report.toolpack_id}",
        f"# Generated: {report.generated_at}",
        "",
    ]
    if report.patch_plan.commands_sh:
        lines.append(report.patch_plan.commands_sh)
    else:
        lines.append("# No commands to run — system is healthy.")
    lines.append("")
    (out / "patch.commands.sh").write_text("\n".join(lines), encoding="utf-8")


def _print_summary(report: Any, out: Path, verbose: bool) -> None:
    """Print repair summary to stdout."""
    diag = report.diagnosis
    plan = report.patch_plan

    if report.exit_code == 0:
        click.echo("Repair: system is healthy, no issues found.")
        return

    click.echo(f"Repair: {diag.total_issues} issues found, {plan.total_patches} patches proposed.")
    click.echo(f"  Safe: {plan.safe_count}  Approval required: {plan.approval_required_count}  Manual: {plan.manual_count}")
    click.echo()
    click.echo(f"  Output: {out}")
    click.echo(f"  Report: {out / 'repair.json'}")
    click.echo(f"  Commands: {out / 'patch.commands.sh'}")

    if verbose:
        click.echo()
        for item in diag.items:
            click.echo(f"  [{item.severity.value:8s}] {item.title}")

        click.echo()
        for patch in plan.patches:
            click.echo(f"  [{patch.kind.value:20s}] {patch.title}")
            click.echo(f"    {patch.cli_command}")
