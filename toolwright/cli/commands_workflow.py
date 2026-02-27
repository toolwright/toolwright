"""Workflow command group (Tide integration)."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from typing import Any, cast

import click


def _require_tide() -> None:
    """Ensure the tide package is importable."""
    try:
        import tide  # noqa: F401
    except ImportError:
        click.echo(
            "Error: tide is not installed. Install it with:\n"
            "  pip install tide\n"
            "or point PYTHONPATH at the tide source tree.",
            err=True,
        )
        sys.exit(1)


def _state_dir() -> Path:
    """Get or create the .tide state directory."""
    d = Path(".tide")
    d.mkdir(exist_ok=True)
    (d / "runs").mkdir(exist_ok=True)
    return d


def _load_run_json(run_dir: Path) -> dict[str, Any]:
    run_json = run_dir / "run.json"
    if not run_json.exists():
        click.echo(f"Error: run.json not found: {run_json}", err=True)
        sys.exit(1)
    return cast(dict[str, Any], json.loads(run_json.read_text(encoding="utf-8")))


def _build_diff_payload(run_a: dict[str, Any], run_b: dict[str, Any]) -> dict[str, Any]:
    steps_a = {str(s.get("step_id")): s for s in run_a.get("results", [])}
    steps_b = {str(s.get("step_id")): s for s in run_b.get("results", [])}
    all_ids = sorted(set(steps_a) | set(steps_b))

    step_diffs: list[dict[str, Any]] = []
    for sid in all_ids:
        a = steps_a.get(sid, {})
        b = steps_b.get(sid, {})
        step_diffs.append({
            "step_id": sid,
            "status_a": "pass" if a.get("ok") else ("missing" if not a else "fail"),
            "status_b": "pass" if b.get("ok") else ("missing" if not b else "fail"),
            "type_a": a.get("type"),
            "type_b": b.get("type"),
            "artifact_count_a": len(a.get("artifacts", [])),
            "artifact_count_b": len(b.get("artifacts", [])),
        })

    return {
        "run_a": {
            "run_id": run_a.get("run_id"),
            "workflow_name": run_a.get("workflow_name"),
            "ok": bool(run_a.get("ok")),
        },
        "run_b": {
            "run_id": run_b.get("run_id"),
            "workflow_name": run_b.get("workflow_name"),
            "ok": bool(run_b.get("ok")),
        },
        "workflow_changed": run_a.get("workflow_name") != run_b.get("workflow_name"),
        "overall_status_changed": bool(run_a.get("ok")) != bool(run_b.get("ok")),
        "step_diffs": step_diffs,
    }


def _render_diff_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Tide Run Diff",
        "",
        f"- Run A: `{payload['run_a']['run_id']}` (ok={payload['run_a']['ok']})",
        f"- Run B: `{payload['run_b']['run_id']}` (ok={payload['run_b']['ok']})",
        f"- Workflow changed: `{payload['workflow_changed']}`",
        f"- Overall status changed: `{payload['overall_status_changed']}`",
        "",
        "## Step Differences",
        "| Step | A | B | Type A | Type B | Artifacts A | Artifacts B |",
        "|---|---|---|---|---|---:|---:|",
    ]
    for step in payload["step_diffs"]:
        lines.append(
            "| {step_id} | {status_a} | {status_b} | {type_a} | {type_b} | {a} | {b} |".format(
                step_id=step["step_id"],
                status_a=step["status_a"],
                status_b=step["status_b"],
                type_a=step["type_a"] or "",
                type_b=step["type_b"] or "",
                a=step["artifact_count_a"],
                b=step["artifact_count_b"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def register_workflow_commands(*, cli: click.Group) -> None:
    """Register the workflow command group on the provided CLI group."""

    @cli.group()
    def workflow() -> None:
        """Verification-first workflow runner.

        Run multi-step verification workflows with shell, HTTP, browser,
        and MCP steps. Produces evidence bundles with digests.

        \b
        Examples:
          toolwright workflow init
          toolwright workflow run tide.yaml
          toolwright workflow report .tide/runs/<run_id>
          toolwright workflow doctor
        """

    @workflow.command("init")
    @click.argument("path", default="tide.yaml")
    def workflow_init(path: str) -> None:
        """Create a starter workflow YAML.

        \b
        Examples:
          toolwright workflow init
          toolwright workflow init my-workflow.yaml
        """
        target = Path(path)
        if target.exists():
            click.echo(f"Error: {target} already exists", err=True)
            sys.exit(1)

        starter = """\
version: 1
name: tide-starter
redaction_profile: default_safe
steps:
  - type: shell
    id: hello
    command: ["bash", "-lc", "echo hello from tide"]
    expect:
      exit_code: 0
"""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(starter, encoding="utf-8")
        click.echo(f"Wrote {target}")
        click.echo(f"Next: toolwright workflow run {target}")

    @workflow.command("run")
    @click.argument("workflow_file", type=click.Path(exists=True))
    def workflow_run(workflow_file: str) -> None:
        """Execute a workflow and emit a verification bundle.

        \b
        Examples:
          toolwright workflow run tide.yaml
          toolwright workflow run workflows/ci.yaml
        """
        _require_tide()
        from tide.core.runner import run_workflow as _run_workflow
        from tide.errors import DependencyError, RunFailed, TideError, UserInputError

        try:
            run_dir = _run_workflow(Path(workflow_file), _state_dir())
            click.echo(str(run_dir))
        except RunFailed as e:
            click.echo(str(e.run_dir))
            click.echo(f"Error: {e}", err=True)
            sys.exit(2)
        except DependencyError as e:
            click.echo(str(e), err=True)
            sys.exit(3)
        except UserInputError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(4)
        except TideError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(5)

    @workflow.command("replay")
    @click.argument("run_dir", type=click.Path(exists=True))
    def workflow_replay(run_dir: str) -> None:
        """Replay a previous run using its resolved workflow.

        \b
        Examples:
          toolwright workflow replay .tide/runs/20250101T120000z_abc1234567
        """
        _require_tide()
        from tide.core.runner import run_workflow as _run_workflow
        from tide.errors import DependencyError, RunFailed, TideError, UserInputError

        run_path = Path(run_dir)
        resolved = run_path / "resolved_workflow.yaml"
        if not resolved.exists():
            click.echo("Error: resolved_workflow.yaml not found in run directory", err=True)
            sys.exit(1)

        try:
            new_run_dir = _run_workflow(resolved, _state_dir())
            click.echo(str(new_run_dir))
        except RunFailed as e:
            click.echo(str(e.run_dir))
            click.echo(f"Error: {e}", err=True)
            sys.exit(2)
        except DependencyError as e:
            click.echo(str(e), err=True)
            sys.exit(3)
        except UserInputError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(4)
        except TideError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(5)

    @workflow.command("diff")
    @click.argument("run_a", type=click.Path(exists=True))
    @click.argument("run_b", type=click.Path(exists=True))
    @click.option(
        "--format", "output_format",
        type=click.Choice(["github-md", "json"]),
        default="github-md",
        show_default=True,
        help="Output format",
    )
    def workflow_diff(run_a: str, run_b: str, output_format: str) -> None:
        """Compare two workflow runs.

        \b
        Examples:
          toolwright workflow diff .tide/runs/run_a .tide/runs/run_b
          toolwright workflow diff run_a run_b --format json
        """
        payload = _build_diff_payload(
            _load_run_json(Path(run_a)),
            _load_run_json(Path(run_b)),
        )
        if output_format == "json":
            click.echo(json.dumps(payload, indent=2))
        else:
            click.echo(_render_diff_markdown(payload))

    @workflow.command("report")
    @click.argument("run_dir", type=click.Path(exists=True))
    @click.option(
        "--format", "output_format",
        type=click.Choice(["github-md", "json"]),
        default="github-md",
        show_default=True,
        help="Report format",
    )
    def workflow_report(run_dir: str, output_format: str) -> None:
        """Generate a report for a completed run.

        \b
        Examples:
          toolwright workflow report .tide/runs/<run_id>
          toolwright workflow report .tide/runs/<run_id> --format json
        """
        _require_tide()
        from tide.reporters.github_md import report_github_md
        from tide.reporters.json_report import report_json

        run_path = Path(run_dir)
        if output_format == "github-md":
            content = report_github_md(run_path)
            ext = ".md"
        else:
            content = report_json(run_path)
            ext = ".json"

        out = run_path / f"report{ext}"
        out.write_text(content, encoding="utf-8")
        click.echo(str(out))

    @workflow.command("pack")
    @click.argument("run_dir", type=click.Path(exists=True))
    @click.option("--out", type=click.Path(), default=None, help="Output zip path")
    def workflow_pack(run_dir: str, out: str | None) -> None:
        """Pack a run directory into a portable zip.

        \b
        Examples:
          toolwright workflow pack .tide/runs/<run_id>
          toolwright workflow pack .tide/runs/<run_id> --out bundle.zip
        """
        run_path = Path(run_dir)
        output = Path(out) if out else (run_path.parent / f"{run_path.name}.zip")
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for p in sorted(run_path.rglob("*")):
                if p.is_file():
                    archive.write(p, arcname=p.relative_to(run_path))
        click.echo(str(output))

    @workflow.command("export")
    @click.argument("target")
    @click.argument("run_dir", type=click.Path(exists=True))
    @click.option("--out", type=click.Path(), default="traffic.har", help="Output file path")
    def workflow_export(target: str, run_dir: str, out: str) -> None:
        """Export artifacts for other tools (e.g. HAR for toolwright capture).

        \b
        Examples:
          toolwright workflow export toolwright .tide/runs/<run_id>
          toolwright workflow export toolwright .tide/runs/<run_id> --out my.har
        """
        if target != "toolwright":
            click.echo("Error: only export target 'toolwright' is supported", err=True)
            sys.exit(1)

        out_path = Path(out)
        if out_path.suffix.lower() != ".har":
            click.echo("Error: --out must end with .har for toolwright import", err=True)
            sys.exit(1)

        _require_tide()
        from tide.core.redaction import extract_first_har_from_zip

        artifacts = Path(run_dir) / "artifacts"
        har_zips = sorted(
            [p for p in artifacts.glob("*.har.zip") if not str(p).endswith(".har.raw.zip")]
        )
        if not har_zips:
            click.echo(
                "Error: no redacted HAR zip found. Use a browser step with HAR enabled.",
                err=True,
            )
            sys.exit(1)

        extract_first_har_from_zip(har_zips[0], out_path)
        click.echo(str(out_path))

    @workflow.command("doctor")
    def workflow_doctor() -> None:
        """Check optional workflow dependencies.

        \b
        Examples:
          toolwright workflow doctor
        """
        click.echo("Workflow dependencies:")
        try:
            import playwright  # noqa: F401
            click.echo("  Playwright: installed")
        except ImportError:
            click.echo("  Playwright: not installed (pip install toolwright[playwright])")
        try:
            import mcp  # noqa: F401
            click.echo("  MCP SDK: installed")
        except ImportError:
            click.echo("  MCP SDK: not installed (pip install toolwright[mcp])")
        try:
            import tide  # noqa: F401
            click.echo("  Tide: installed")
        except ImportError:
            click.echo("  Tide: not installed (pip install tide)")
