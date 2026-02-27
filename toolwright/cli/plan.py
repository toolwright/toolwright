"""Plan command implementation."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from toolwright.core.plan.engine import (
    build_plan,
    render_plan_github_md,
    render_plan_json,
    render_plan_md,
)
from toolwright.core.toolpack import load_toolpack


def run_plan(
    *,
    toolpack_path: str,
    baseline: str | None,
    output_dir: str | None,
    output_format: str,
    root_path: str,
    verbose: bool,
) -> None:
    """Generate a deterministic plan report."""
    try:
        toolpack = load_toolpack(Path(toolpack_path))
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    output_root = Path(output_dir) if output_dir else Path(root_path) / "plans" / toolpack.toolpack_id
    output_root.mkdir(parents=True, exist_ok=True)

    try:
        report = build_plan(
            toolpack_path=Path(toolpack_path),
            baseline_path=Path(baseline) if baseline else None,
        )
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    artifacts_created: list[tuple[str, Path]] = []
    if output_format in ("json", "both"):
        json_path = output_root / "plan.json"
        json_path.write_text(render_plan_json(report), encoding="utf-8")
        artifacts_created.append(("plan.json", json_path))
    if output_format in ("markdown", "both"):
        md_path = output_root / "plan.md"
        md_path.write_text(render_plan_md(report), encoding="utf-8")
        artifacts_created.append(("plan.md", md_path))
    if output_format == "github-md":
        github_md_path = output_root / "diff.github.md"
        github_md_path.write_text(render_plan_github_md(report), encoding="utf-8")
        artifacts_created.append(("diff.github.md", github_md_path))

    if verbose:
        for name, path in artifacts_created:
            click.echo(f"Wrote {name}: {path}", err=True)
