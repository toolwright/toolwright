"""Validation, diagnostics, and proof-flow command registration."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from pathlib import Path

import click

from toolwright.cli.command_helpers import cli_root, cli_root_str, default_root_path


def register_validation_commands(
    *,
    cli: click.Group,
    run_with_lock: Callable[..., None],
) -> None:
    """Register validation and diagnostics commands."""

    @cli.command("diff")
    @click.option(
        "--toolpack",
        type=click.Path(),
        help="Path to toolpack.yaml (auto-resolved if not given)",
    )
    @click.option(
        "--baseline",
        type=click.Path(),
        help="Baseline toolpack.yaml or snapshot directory",
    )
    @click.option(
        "--output",
        "-o",
        type=click.Path(),
        help="Output directory for diff artifacts",
    )
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["json", "markdown", "github-md", "both"]),
        default="both",
        show_default=True,
        help="Diff output format",
    )
    @click.pass_context
    def diff(
        ctx: click.Context,
        toolpack: str | None,
        baseline: str | None,
        output: str | None,
        output_format: str,
    ) -> None:
        """Compare toolpack versions (what changed in your tools)."""
        from toolwright.cli.plan import run_plan
        from toolwright.utils.resolve import resolve_toolpack_path

        resolved = str(resolve_toolpack_path(explicit=toolpack, root=cli_root(ctx)))
        run_plan(
            toolpack_path=resolved,
            baseline=baseline,
            output_dir=output,
            output_format=output_format,
            root_path=cli_root_str(ctx),
            verbose=ctx.obj.get("verbose", False),
        )

    @cli.command()
    @click.option("--from", "from_capture", help="Source capture ID")
    @click.option("--to", "to_capture", help="Target capture ID")
    @click.option("--baseline", type=click.Path(exists=True), help="Baseline file path")
    @click.option("--capture-id", help="Capture ID to compare against baseline")
    @click.option("--capture-path", type=click.Path(), help="Capture path to compare against baseline")
    @click.option(
        "--capture",
        "-c",
        "capture_legacy",
        help="Deprecated alias for --capture-id/--capture-path",
    )
    @click.option("--shape-baselines", type=click.Path(exists=True), help="Shape baselines file for response drift")
    @click.option("--tool", help="Tool name for shape-based drift detection")
    @click.option("--response-file", type=click.Path(exists=True), help="JSON response body file for shape drift")
    @click.option(
        "--output",
        "-o",
        type=click.Path(),
        help="Output directory (defaults to <root>/reports)",
    )
    @click.option(
        "--format",
        "-f",
        "output_format",
        type=click.Choice(["json", "markdown", "both"]),
        default="both",
        help="Report format",
    )
    @click.option(
        "--deterministic/--volatile-metadata",
        default=True,
        show_default=True,
        help="Deterministic drift output by default; use --volatile-metadata for ephemeral IDs/timestamps",
    )
    @click.pass_context
    def drift(
        ctx: click.Context,
        from_capture: str | None,
        to_capture: str | None,
        baseline: str | None,
        capture_id: str | None,
        capture_path: str | None,
        capture_legacy: str | None,
        shape_baselines: str | None,
        tool: str | None,
        response_file: str | None,
        output: str | None,
        output_format: str,
        deterministic: bool,
    ) -> None:
        """Check live API for behavioral changes (what changed upstream).

        \b
        Examples:
          toolwright drift --from cap_old --to cap_new
          toolwright drift --baseline baseline.json --capture-id cap_new
          toolwright drift --shape-baselines shape_baselines.json
          toolwright drift --shape-baselines shape_baselines.json --tool get_products --response-file response.json
        """
        from toolwright.cli.drift import run_drift

        if capture_legacy:
            if capture_id or capture_path:
                click.echo(
                    "Error: --capture cannot be used with --capture-id or --capture-path",
                    err=True,
                )
                raise SystemExit(1)
            if Path(capture_legacy).exists():
                capture_path = capture_legacy
            else:
                capture_id = capture_legacy

        resolved_output = output or str(default_root_path(ctx, "reports"))

        run_drift(
            from_capture=from_capture,
            to_capture=to_capture,
            baseline=baseline,
            capture_id=capture_id,
            capture_path=capture_path,
            output_dir=resolved_output,
            output_format=output_format,
            verbose=ctx.obj.get("verbose", False),
            deterministic=deterministic,
            root_path=cli_root_str(ctx),
            shape_baselines=shape_baselines,
            tool=tool,
            response_file=response_file,
        )

    @cli.command(
        epilog="""\b
Examples:
  toolwright verify --toolpack toolpack.yaml
  toolwright verify --toolpack toolpack.yaml --mode baseline-check
  toolwright verify --toolpack toolpack.yaml --mode contracts --strict
  toolwright verify --toolpack toolpack.yaml --mode provenance
""",
    )
    @click.option(
        "--toolpack",
        type=click.Path(),
        help="Path to toolpack.yaml (auto-resolved if not given)",
    )
    @click.option(
        "--mode",
        type=click.Choice(["contracts", "baseline-check", "replay", "outcomes", "provenance", "all"]),
        default="all",
        show_default=True,
        help="Verification mode",
    )
    @click.option("--lockfile", type=click.Path(), help="Optional lockfile override (pending allowed)")
    @click.option("--playbook", type=click.Path(exists=True), help="Path to deterministic playbook")
    @click.option("--ui-assertions", type=click.Path(exists=True), help="Path to UI assertion list")
    @click.option(
        "--output",
        "-o",
        type=click.Path(),
        help="Output directory for verification reports (defaults to <root>/reports)",
    )
    @click.option("--strict/--no-strict", default=True, show_default=True, help="Strict gating mode")
    @click.option("--top-k", default=5, show_default=True, type=int, help="Top candidate APIs per assertion")
    @click.option(
        "--min-confidence",
        default=0.70,
        show_default=True,
        type=float,
        help="Minimum confidence threshold for provenance pass",
    )
    @click.option(
        "--unknown-budget",
        default=0.20,
        show_default=True,
        type=float,
        help="Maximum ratio of unknown provenance assertions before gating",
    )
    @click.pass_context
    def verify(
        ctx: click.Context,
        toolpack: str | None,
        mode: str,
        lockfile: str | None,
        playbook: str | None,
        ui_assertions: str | None,
        output: str | None,
        strict: bool,
        top_k: int,
        min_confidence: float,
        unknown_budget: float,
    ) -> None:
        """Run verification contracts (replay, outcomes, provenance)."""
        from toolwright.cli.verify import run_verify
        from toolwright.utils.resolve import resolve_toolpack_path

        resolved_toolpack = str(resolve_toolpack_path(explicit=toolpack, root=cli_root(ctx)))
        resolved_output = output or str(default_root_path(ctx, "reports"))
        run_verify(
            toolpack_path=resolved_toolpack,
            mode=mode,
            lockfile_path=lockfile,
            playbook_path=playbook,
            ui_assertions_path=ui_assertions,
            output_dir=resolved_output,
            strict=strict,
            top_k=top_k,
            min_confidence=min_confidence,
            unknown_budget=unknown_budget,
            verbose=ctx.obj.get("verbose", False),
        )

    @cli.command(hidden=True)
    @click.option(
        "--toolpack",
        required=False,
        type=click.Path(),
        help="Path to toolpack.yaml (auto-detected if omitted).",
    )
    @click.option(
        "--runtime",
        type=click.Choice(["auto", "local", "container"]),
        default="auto",
        show_default=True,
        help="Runtime to validate",
    )
    @click.pass_context
    def doctor(ctx: click.Context, toolpack: str | None, runtime: str) -> None:
        """Validate toolpack readiness for execution."""
        from click.core import ParameterSource

        from toolwright.cli.doctor import run_doctor

        # Auto-discover toolpack if not specified
        if toolpack is None:
            from toolwright.ui.discovery import find_toolpacks

            root = Path(ctx.obj.get("root", ".toolwright"))
            candidates = find_toolpacks(root)
            if not candidates:
                raise click.ClickException(
                    "No toolpacks found. Run 'toolwright create' first."
                )
            toolpack = str(candidates[0])

        runtime_source = ctx.get_parameter_source("runtime")
        require_local_mcp = (
            runtime == "local" and runtime_source == ParameterSource.COMMANDLINE
        )

        run_doctor(
            toolpack_path=toolpack,
            runtime=runtime,
            verbose=ctx.obj.get("verbose", False),
            require_local_mcp=require_local_mcp,
        )

    @cli.command(hidden=True)
    @click.option(
        "--toolpack",
        type=click.Path(),
        help="Path to toolpack.yaml (resolves tools/policy paths)",
    )
    @click.option("--tools", type=click.Path(), help="Path to tools.json")
    @click.option("--policy", type=click.Path(exists=True), help="Path to policy.yaml")
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["text", "json"]),
        default="text",
        show_default=True,
        help="Lint output format",
    )
    @click.pass_context
    def lint(
        ctx: click.Context,
        toolpack: str | None,
        tools: str | None,
        policy: str | None,
        output_format: str,
    ) -> None:
        """Lint capability artifacts for strict governance hygiene."""
        from toolwright.cli.lint import run_lint

        run_lint(
            toolpack_path=toolpack,
            tools_path=tools,
            policy_path=policy,
            output_format=output_format,
            verbose=ctx.obj.get("verbose", False),
        )

    @cli.command()
    @click.option(
        "--tools",
        required=False,
        type=click.Path(exists=True),
        help="Path to tools.json manifest.",
    )
    @click.option(
        "--toolpack",
        type=click.Path(),
        help="Path to toolpack.yaml (auto-resolves tools.json path)",
    )
    def health(tools: str | None, toolpack: str | None) -> None:
        """Probe endpoint health for all tools in a manifest.

        Sends non-mutating probes (HEAD/OPTIONS) to each endpoint and
        reports status, response time, and failure classification.

        Exits 0 if all healthy, 1 if any unhealthy.

        \b
        Examples:
          toolwright health --tools output/tools.json
          toolwright health --tools my-api/tools.json
          toolwright health --toolpack toolpack.yaml
        """
        if not tools and not toolpack:
            raise click.UsageError("Provide --tools or --toolpack.")

        if toolpack and not tools:
            from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

            tp = load_toolpack(Path(toolpack))
            resolved = resolve_toolpack_paths(toolpack=tp, toolpack_path=toolpack)
            tools = str(resolved.tools_path)

        manifest = json.loads(Path(tools).read_text())  # type: ignore[arg-type]
        actions = manifest.get("actions", [])

        if not actions:
            click.echo("No actions found in manifest.")
            return

        from toolwright.core.health.checker import HealthChecker

        checker = HealthChecker()
        results = asyncio.run(checker.check_all(actions))

        any_unhealthy = False
        for result in results:
            status = "healthy" if result.healthy else "UNHEALTHY"
            if not result.healthy:
                any_unhealthy = True
            failure_class = (
                f"  [{result.failure_class.value}]"
                if result.failure_class
                else ""
            )
            status_code = (
                f"  {result.status_code}"
                if result.status_code is not None
                else ""
            )
            click.echo(
                f"  {result.tool_id:<30} {status:<12}{status_code}"
                f"{failure_class}  {result.response_time_ms:.0f}ms"
            )

        click.echo()
        if any_unhealthy:
            click.echo("Some tools are unhealthy.")
            raise SystemExit(1)

        click.echo("All tools healthy.")

    @cli.command()
    @click.option(
        "--out",
        type=click.Path(file_okay=False),
        help="Output directory for demo artifacts (defaults to a temporary directory)",
    )
    @click.option(
        "--live",
        is_flag=True,
        help="Run live/browser orchestration (requires extra dependencies)",
    )
    @click.option(
        "--scenario",
        type=click.Choice(["basic_products", "auth_refresh"]),
        default="basic_products",
        show_default=True,
        help="Live scenario to execute when --live is enabled",
    )
    @click.option(
        "--keep",
        is_flag=True,
        help="Keep existing output directory contents",
    )
    @click.option(
        "--smoke",
        is_flag=True,
        help="Run smoke test matrix across multiple scenarios",
    )
    @click.option(
        "--smoke-scenarios",
        default="offline_fixture",
        show_default=True,
        help="Comma-separated scenarios for --smoke mode",
    )
    @click.option(
        "--generate-only",
        is_flag=True,
        help="Generate a fixture toolpack without running the prove flow",
    )
    @click.option(
        "--offline",
        is_flag=True,
        help="Compile-only mode (no server). Same as --generate-only.",
    )
    @click.pass_context
    def demo(
        ctx: click.Context,
        out: str | None,
        live: bool,
        scenario: str,
        keep: bool,
        smoke: bool,
        smoke_scenarios: str,
        generate_only: bool,
        offline: bool,
    ) -> None:
        """One-command proof of governance enforcement.

        Proves that governance is enforced, replays are deterministic, and parity
        passes. Runs offline by default (no credentials or browser needed).

        \b
        Examples:
          toolwright demo                          # Offline proof flow
          toolwright demo --offline                # Compile-only (no server)
          toolwright demo --live                   # Live browser proof
          toolwright demo --smoke                  # Smoke test matrix
          toolwright demo --generate-only          # Generate fixture toolpack only
        """
        if generate_only or offline:
            from toolwright.cli.demo import run_demo

            run_with_lock(
                ctx,
                "demo",
                lambda: run_demo(
                    output_root=out or cli_root_str(ctx),
                    verbose=ctx.obj.get("verbose", False),
                ),
            )
            return

        if smoke:
            from toolwright.cli.wow import run_prove_smoke

            exit_code = run_prove_smoke(
                out_dir=out,
                live=live,
                scenarios=smoke_scenarios,
                keep=keep,
                verbose=ctx.obj.get("verbose", False),
            )
            if exit_code != 0:
                sys.exit(exit_code)
            return

        from toolwright.cli.wow import run_wow

        exit_code = run_wow(
            out_dir=out,
            live=live,
            scenario=scenario,
            keep=keep,
            verbose=ctx.obj.get("verbose", False),
        )
        if exit_code != 0:
            sys.exit(exit_code)
