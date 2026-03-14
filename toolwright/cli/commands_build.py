"""Build-oriented top-level command registration."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import click

from toolwright.cli.command_helpers import cli_root_str, default_root_path


def register_build_commands(
    *,
    cli: click.Group,
    run_with_lock: Callable[..., None],
) -> None:
    """Register build and compilation commands."""

    @cli.command()
    @click.argument("subcommand", type=click.Choice(["import", "record"]))
    @click.argument("source", required=False)
    @click.option(
        "--allowed-hosts",
        "-a",
        multiple=True,
        help="API hosts to include (required, repeatable). Use the domain of your API, e.g. -a api.example.com",
    )
    @click.option("--name", "-n", help="Name for the capture session")
    @click.option(
        "--output",
        "-o",
        type=click.Path(),
        help="Capture output directory (defaults to <root>/captures)",
    )
    @click.option(
        "--input-format",
        type=click.Choice(["har", "otel", "openapi"]),
        default="har",
        show_default=True,
        help="Input format for import mode (auto-detected for OpenAPI specs)",
    )
    @click.option("--no-redact", is_flag=True, help="Disable redaction (not recommended)")
    @click.option(
        "--headless/--no-headless",
        default=False,
        show_default=True,
        help="Run Playwright browser headless in record mode",
    )
    @click.option(
        "--script",
        type=click.Path(exists=True),
        help="Python script with async run(page, context) for scripted capture",
    )
    @click.option(
        "--duration",
        type=int,
        default=30,
        show_default=True,
        help="Capture duration in seconds for non-interactive/headless mode",
    )
    @click.option(
        "--load-storage-state",
        type=click.Path(exists=True),
        help="Load browser storage state (cookies, localStorage) from a JSON file",
    )
    @click.option(
        "--save-storage-state",
        type=click.Path(),
        help="Save browser storage state to a JSON file after capture",
    )
    @click.pass_context
    def capture(
        ctx: click.Context,
        subcommand: str,
        source: str | None,
        allowed_hosts: tuple[str, ...],
        name: str | None,
        output: str | None,
        input_format: str,
        no_redact: bool,
        headless: bool,
        script: str | None,
        duration: int,
        load_storage_state: str | None,
        save_storage_state: str | None,
    ) -> None:
        """Import traffic from HAR/OTEL/OpenAPI files or capture with Playwright.

        For 'import': SOURCE is the path to a HAR, OTEL, or OpenAPI file.
        For 'record': SOURCE is the starting URL for browser capture.
        Record mode supports interactive, timed headless, and scripted automation.

        \b
        Examples:
          # Import a HAR file
          toolwright capture import traffic.har -a api.example.com
          # Import an OpenAPI spec
          toolwright capture import openapi.yaml -a api.example.com
          # Import OpenTelemetry traces
          toolwright capture import traces.json --input-format otel -a api.example.com
          # Record traffic interactively with Playwright
          toolwright capture record https://example.com -a api.example.com
        """
        if not allowed_hosts:
            click.echo(
                "Error: --allowed-hosts / -a is required.\n\n"
                "This tells toolwright which API hosts to capture. Use the domain of your API server.\n\n"
                "Examples:\n"
                "  toolwright capture import traffic.har -a api.example.com\n"
                "  toolwright capture record https://app.example.com -a api.example.com\n"
                "  toolwright capture import spec.yaml -a api.example.com -a auth.example.com\n\n"
                "Tip: check your HAR/spec file for the API hostname.",
                err=True,
            )
            raise SystemExit(2)

        resolved_output = output or str(default_root_path(ctx, "captures"))

        effective_format = input_format
        if subcommand == "import" and source and input_format == "har":
            effective_format = _detect_openapi_format(source, input_format)

        if effective_format == "openapi":
            from toolwright.cli.capture import run_capture_openapi

            run_with_lock(
                ctx,
                "capture",
                lambda: run_capture_openapi(
                    source=source or "",
                    allowed_hosts=list(allowed_hosts) if allowed_hosts else None,
                    name=name,
                    output=resolved_output,
                    verbose=ctx.obj.get("verbose", False),
                    root_path=cli_root_str(ctx),
                ),
            )
            return

        from toolwright.cli.capture import run_capture

        run_with_lock(
            ctx,
            "capture",
            lambda: run_capture(
                subcommand=subcommand,
                source=source,
                input_format=effective_format,
                allowed_hosts=list(allowed_hosts),
                name=name,
                output=resolved_output,
                redact=not no_redact,
                headless=headless,
                script_path=script,
                duration_seconds=duration,
                load_storage_state=load_storage_state,
                save_storage_state=save_storage_state,
                verbose=ctx.obj.get("verbose", False),
                root_path=cli_root_str(ctx),
            ),
        )

    @cli.command()
    @click.argument("start_url")
    @click.option(
        "--allowed-hosts",
        "-a",
        multiple=True,
        required=False,
        help="Hosts to include (required unless --recipe provides them, repeatable)",
    )
    @click.option("--name", "-n", help="Optional toolpack/session name")
    @click.option(
        "--scope",
        "-s",
        default="first_party_only",
        show_default=True,
        help="Scope to apply during compile",
    )
    @click.option(
        "--headless/--no-headless",
        default=False,
        show_default=True,
        help="Run browser headless during capture (default: interactive)",
    )
    @click.option(
        "--script",
        type=click.Path(exists=True),
        help="Python script with async run(page, context) for scripted capture",
    )
    @click.option(
        "--duration",
        type=int,
        default=120,
        show_default=True,
        help="Capture duration in seconds when no script is provided",
    )
    @click.option(
        "--output",
        "-o",
        type=click.Path(),
        help="Output root directory (defaults to --root)",
    )
    @click.option(
        "--deterministic/--volatile-metadata",
        default=True,
        show_default=True,
        help="Deterministic metadata by default; use --volatile-metadata for ephemeral IDs/timestamps",
    )
    @click.option(
        "--runtime",
        type=click.Choice(["local", "container"]),
        default="local",
        show_default=True,
        help="Runtime mode metadata/emission (container emits runtime files)",
    )
    @click.option(
        "--runtime-build",
        is_flag=True,
        help="Build container image after emitting runtime files (requires Docker)",
    )
    @click.option(
        "--runtime-tag",
        help="Container image tag to use when --runtime=container",
    )
    @click.option(
        "--runtime-version-pin",
        help="Exact requirement line for toolwright runtime when --runtime=container",
    )
    @click.option(
        "--print-mcp-config",
        is_flag=True,
        help="Print a ready-to-paste Claude Desktop MCP config snippet",
    )
    @click.option(
        "--auth-profile",
        default=None,
        help="Auth profile name to use for authenticated capture",
    )
    @click.option(
        "--webmcp",
        is_flag=True,
        default=False,
        help="Discover WebMCP tools (navigator.modelContext) on the target page",
    )
    @click.option(
        "--redaction-profile",
        type=click.Choice(["default_safe", "high_risk_pii"]),
        default=None,
        help="Redaction profile to apply during capture (default: built-in patterns)",
    )
    @click.option(
        "--extra-header", "-H",
        "extra_header_raw",
        multiple=True,
        help="Extra header to inject at serve time (repeatable, format: 'Name: value')",
    )
    @click.option(
        "--no-probe",
        is_flag=True,
        default=False,
        help="Skip pre-flight API probing (auth, GraphQL, OpenAPI detection)",
    )
    @click.option(
        "--recipe", "-r",
        default=None,
        help="Use a bundled API recipe (e.g., github, stripe). Sets hosts, headers, auth.",
    )
    @click.option(
        "--auto-approve/--no-auto-approve",
        default=False,
        help="Auto-approve low/medium risk tools via smart gate (default: off for mint).",
    )
    @click.option(
        "--rules/--no-rules",
        "apply_rules",
        default=True,
        help="Apply default behavioral rules (crud-safety) after minting.",
    )
    @click.pass_context
    def mint(
        ctx: click.Context,
        start_url: str,
        allowed_hosts: tuple[str, ...],
        name: str | None,
        scope: str,
        headless: bool,
        script: str | None,
        duration: int,
        output: str | None,
        deterministic: bool,
        runtime: str,
        runtime_build: bool,
        runtime_tag: str | None,
        runtime_version_pin: str | None,
        print_mcp_config: bool,
        auth_profile: str | None,
        webmcp: bool,
        redaction_profile: str | None,
        extra_header_raw: tuple[str, ...],
        no_probe: bool,
        recipe: str | None,
        auto_approve: bool,
        apply_rules: bool,
    ) -> None:
        """Capture traffic and compile a governed toolpack.

        \b
        Example:
          toolwright mint https://example.com -a api.example.com --print-mcp-config
          toolwright mint https://app.example.com -a api.example.com --auth-profile myapp
          toolwright mint https://app.example.com --webmcp -a api.example.com
          toolwright mint https://api.github.com --recipe github
        """
        from toolwright.cli.mint import run_mint
        from toolwright.utils.headers import parse_extra_headers

        if not allowed_hosts and not recipe:
            click.echo("Error: --allowed-hosts or --recipe is required", err=True)
            raise SystemExit(1)

        resolved_output = output or cli_root_str(ctx)
        extra_headers = parse_extra_headers(extra_header_raw) if extra_header_raw else None

        if recipe:
            from toolwright.recipes.loader import load_recipe

            recipe_data = load_recipe(recipe)

            if not allowed_hosts:
                allowed_hosts = tuple(h["pattern"] for h in recipe_data.get("hosts", []))

            recipe_headers = recipe_data.get("extra_headers", {})
            if recipe_headers:
                if extra_headers is None:
                    extra_headers = {}
                for key, value in recipe_headers.items():
                    extra_headers.setdefault(key, value)

            click.echo(f"Using recipe: {recipe_data['name']}", err=True)

        run_with_lock(
            ctx,
            "mint",
            lambda: run_mint(
                start_url=start_url,
                allowed_hosts=list(allowed_hosts),
                name=name,
                scope_name=scope,
                headless=headless,
                script_path=script,
                duration_seconds=duration,
                output_root=resolved_output,
                deterministic=deterministic,
                runtime_mode=runtime,
                runtime_build=runtime_build,
                runtime_tag=runtime_tag,
                runtime_version_pin=runtime_version_pin,
                print_mcp_config=print_mcp_config,
                auth_profile=auth_profile,
                webmcp=webmcp,
                redaction_profile=redaction_profile,
                verbose=ctx.obj.get("verbose", False),
                extra_headers=extra_headers,
                no_probe=no_probe,
                recipe=recipe,
                auto_approve=auto_approve,
                apply_rules=apply_rules,
            ),
        )

    @cli.command(hidden=True)
    @click.option("--capture", "-c", required=True, help="Capture session ID or path")
    @click.option(
        "--scope",
        "-s",
        default="first_party_only",
        help="Scope to apply (default: first_party_only)",
    )
    @click.option("--scope-file", type=click.Path(exists=True), help="Path to custom scope YAML")
    @click.option(
        "--format",
        "-f",
        "output_format",
        type=click.Choice(["manifest", "openapi", "all"]),
        default="all",
        help="Output format",
    )
    @click.option(
        "--output",
        "-o",
        type=click.Path(),
        help="Output directory (defaults to <root>/artifacts)",
    )
    @click.option(
        "--deterministic/--volatile-metadata",
        default=True,
        show_default=True,
        help="Deterministic artifacts by default; use --volatile-metadata for ephemeral IDs/timestamps",
    )
    @click.pass_context
    def compile(
        ctx: click.Context,
        capture: str,
        scope: str,
        scope_file: str | None,
        output_format: str,
        output: str | None,
        deterministic: bool,
    ) -> None:
        """Compile captured traffic into contracts, tools, and policies."""
        from toolwright.cli.compile import run_compile

        resolved_output = output or str(default_root_path(ctx, "artifacts"))

        run_with_lock(
            ctx,
            "compile",
            lambda: run_compile(
                capture_id=capture,
                scope_name=scope,
                scope_file=scope_file,
                output_format=output_format,
                output_dir=resolved_output,
                verbose=ctx.obj.get("verbose", False),
                deterministic=deterministic,
                root_path=cli_root_str(ctx),
            ),
        )


def _detect_openapi_format(source: str, default: str) -> str:
    """Detect if a source file is an OpenAPI spec."""
    import json as _json

    import yaml as _yaml

    source_path = Path(source)
    if not source_path.exists():
        return default
    try:
        text = source_path.read_text(encoding="utf-8")
        if source_path.suffix in {".yaml", ".yml"}:
            data = _yaml.safe_load(text)
        elif source_path.suffix == ".json":
            data = _json.loads(text)
        else:
            return default
        if isinstance(data, dict) and "openapi" in data:
            return "openapi"
    except Exception:
        pass
    return default
