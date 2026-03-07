"""Create command: instant toolpack from OpenAPI specs or bundled recipes."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import click
import httpx

from toolwright.cli.approve import sync_lockfile
from toolwright.cli.compile import compile_capture_session
from toolwright.cli.mint import (
    AutoApproveResult,
    DefaultRulesResult,
    apply_default_rules,
    auto_approve_lockfile,
    build_mcp_integration_output,
    format_example_tool,
)
from toolwright.core.capture.openapi_parser import OpenAPIParser
from toolwright.core.toolpack import (
    Toolpack,
    ToolpackOrigin,
    ToolpackPaths,
    ToolpackRuntime,
    write_toolpack,
)
from toolwright.utils.schema_version import resolve_generated_at


def _fetch_or_cache_spec(
    spec_url: str,
    api_name: str | None,
    root: Path,
) -> Path:
    """Fetch an OpenAPI spec from URL, with offline cache fallback.

    On success, caches to .toolwright/specs/{api_name}.json.
    On failure, checks cache. Raises click.ClickException if both fail.
    """
    cache_dir = root / "specs"
    cache_file = cache_dir / f"{api_name or 'spec'}.json" if api_name else None

    # Try network fetch
    try:
        resp = httpx.get(spec_url, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
        content = resp.text

        # Cache on success
        if cache_file:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(content)

        # Write to temp file for parser
        tmp = tempfile.NamedTemporaryFile(
            suffix=".json" if spec_url.endswith(".json") else ".yaml",
            delete=False,
            mode="w",
        )
        tmp.write(content)
        tmp.close()
        return Path(tmp.name)

    except (httpx.HTTPError, OSError) as exc:
        # Offline fallback: check cache
        if cache_file and cache_file.exists():
            click.echo(f"  Network unavailable, using cached spec: {cache_file}", err=True)
            return cache_file

        raise click.ClickException(
            f"Failed to fetch OpenAPI spec from {spec_url}: {exc}\n"
            f"  Hint: use --spec with a local file path, or ensure network access."
        ) from exc


def _resolve_spec_path(
    api_name: str | None,
    spec: str | None,
    recipe_data: dict[str, Any] | None,
    root: Path,
) -> Path:
    """Resolve the spec path from recipe, --spec flag, or fetch."""
    if spec:
        # Direct spec path or URL
        spec_path = Path(spec)
        if spec_path.exists():
            return spec_path
        # Treat as URL
        return _fetch_or_cache_spec(spec, api_name, root)

    if recipe_data and recipe_data.get("openapi_spec_url"):
        return _fetch_or_cache_spec(recipe_data["openapi_spec_url"], api_name, root)

    raise click.ClickException(
        "No OpenAPI spec available. Use --spec <path-or-url> or choose a recipe with an OpenAPI spec URL."
    )


def run_create(
    *,
    api_name: str | None,
    spec: str | None,
    name: str | None,
    auto_approve: bool,
    apply_rules: bool,
    output_root: str,
    verbose: bool,
) -> None:
    """Create a toolpack from an OpenAPI spec or bundled recipe."""
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)

    recipe_data: dict[str, Any] | None = None

    # Resolve recipe if api_name provided
    if api_name:
        from toolwright.recipes.loader import list_recipes, load_recipe

        try:
            recipe_data = load_recipe(api_name)
            click.echo(f"Using recipe: {recipe_data['name']}")
        except (FileNotFoundError, ValueError) as exc:
            available = list_recipes()
            names = [r["name"] for r in available]
            raise click.ClickException(
                f"Unknown API: '{api_name}'\n"
                f"  Available recipes: {', '.join(names) if names else 'none'}\n"
                f"  Or use: toolwright create --spec <path-or-url>"
            ) from exc

    # Need either api_name or spec
    if not api_name and not spec:
        raise click.ClickException(
            "Provide an API name or --spec.\n"
            "  Example: toolwright create github\n"
            "  Example: toolwright create --spec ./openapi.json"
        )

    # Resolve spec
    click.echo("  Fetching OpenAPI spec...")
    spec_path = _resolve_spec_path(api_name, spec, recipe_data, root)

    # Parse spec
    click.echo("  Parsing spec...")
    allowed_hosts: list[str] = []
    if recipe_data:
        allowed_hosts = [h["pattern"] for h in recipe_data.get("hosts", [])]

    parser = OpenAPIParser(allowed_hosts=allowed_hosts)
    session = parser.parse_file(spec_path, name=name or api_name)

    if not session.exchanges:
        raise click.ClickException(
            "No endpoints found in the OpenAPI spec. Check the spec file."
        )

    click.echo(f"  Found {len(session.exchanges)} endpoints")

    # Compile
    click.echo("  Compiling artifacts...")
    try:
        compile_result = compile_capture_session(
            session=session,
            scope_name="first_party_only",
            scope_file=None,
            output_format="all",
            output_dir=root / "artifacts",
            deterministic=True,
            verbose=verbose,
        )
    except ValueError as e:
        raise click.ClickException(f"Compilation failed: {e}") from e

    if not compile_result.tools_path or not compile_result.toolsets_path:
        raise click.ClickException("Compile did not produce required tools/toolsets artifacts")
    if not compile_result.policy_path or not compile_result.baseline_path:
        raise click.ClickException("Compile did not produce required policy/baseline artifacts")

    # Package toolpack
    click.echo("  Packaging toolpack...")
    from toolwright.utils.resolve import generate_toolpack_slug

    effective_hosts = sorted(set(session.allowed_hosts or allowed_hosts))
    toolpack_id = generate_toolpack_slug(allowed_hosts=effective_hosts, root=root)
    if name:
        # Use name as slug base
        import re
        slug = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")
        toolpack_id = slug or toolpack_id

    toolpack_dir = root / "toolpacks" / toolpack_id
    artifact_dir = toolpack_dir / "artifact"
    lockfile_dir = toolpack_dir / "lockfile"
    toolpack_dir.mkdir(parents=True, exist_ok=True)
    lockfile_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(compile_result.output_path, artifact_dir, dirs_exist_ok=True)

    copied_tools = artifact_dir / "tools.json"
    copied_toolsets = artifact_dir / "toolsets.yaml"
    copied_policy = artifact_dir / "policy.yaml"
    copied_baseline = artifact_dir / "baseline.json"
    copied_groups = artifact_dir / "groups.json"
    copied_contracts = artifact_dir / "contracts.yaml"
    copied_contract_yaml = artifact_dir / "contract.yaml"
    copied_contract_json = artifact_dir / "contract.json"

    # Sync lockfile
    pending_lockfile = lockfile_dir / "toolwright.lock.pending.yaml"
    sync_result = sync_lockfile(
        tools_path=str(copied_tools),
        policy_path=str(copied_policy),
        toolsets_path=str(copied_toolsets),
        lockfile_path=str(pending_lockfile),
        capture_id=session.id,
        scope="first_party_only",
        deterministic=True,
    )

    # Auto-approve via smart gate
    gate_result: AutoApproveResult | None = None
    if auto_approve:
        gate_result = auto_approve_lockfile(pending_lockfile)

    lockfiles: dict[str, str] = {
        "pending": str(pending_lockfile.relative_to(toolpack_dir)),
    }

    # Write toolpack.yaml
    toolpack = Toolpack(
        toolpack_id=toolpack_id,
        created_at=resolve_generated_at(deterministic=True),
        capture_id=session.id,
        artifact_id=compile_result.artifact_id,
        scope="first_party_only",
        allowed_hosts=effective_hosts,
        display_name=name or api_name,
        origin=ToolpackOrigin(
            start_url=f"openapi:{spec or (recipe_data or {}).get('openapi_spec_url', 'local')}",
            name=name or api_name,
        ),
        paths=ToolpackPaths(
            tools=str(copied_tools.relative_to(toolpack_dir)),
            toolsets=str(copied_toolsets.relative_to(toolpack_dir)),
            policy=str(copied_policy.relative_to(toolpack_dir)),
            baseline=str(copied_baseline.relative_to(toolpack_dir)),
            contracts=(
                str(copied_contracts.relative_to(toolpack_dir))
                if copied_contracts.exists()
                else None
            ),
            contract_yaml=(
                str(copied_contract_yaml.relative_to(toolpack_dir))
                if copied_contract_yaml.exists()
                else None
            ),
            contract_json=(
                str(copied_contract_json.relative_to(toolpack_dir))
                if copied_contract_json.exists()
                else None
            ),
            groups=(
                str(copied_groups.relative_to(toolpack_dir))
                if copied_groups.exists()
                else None
            ),
            lockfiles=lockfiles,
        ),
        runtime=ToolpackRuntime(mode="local", container=None),
        auth_requirements=None,
        extra_headers=None,
    )

    toolpack_file = toolpack_dir / "toolpack.yaml"
    write_toolpack(toolpack, toolpack_file)

    # Apply behavioral rules
    rules_result: DefaultRulesResult | None = None
    if apply_rules:
        # Use recipe templates if available, otherwise default crud-safety
        if recipe_data and recipe_data.get("rule_templates"):
            from toolwright.rules.loader import apply_template as _apply_tmpl

            rules_path = toolpack_dir / "rules.json"
            total_rules = 0
            for tmpl_name in recipe_data["rule_templates"]:
                try:
                    created = _apply_tmpl(tmpl_name, rules_path=rules_path)
                    total_rules += len(created)
                except ValueError:
                    pass
            rules_result = DefaultRulesResult(
                rule_count=total_rules,
                template_name=", ".join(recipe_data["rule_templates"]),
            )
        else:
            rules_path = toolpack_dir / "rules.json"
            rules_result = apply_default_rules(rules_path=rules_path)

    # -----------------------------------------------------------------------
    # Output: 4 sections
    # -----------------------------------------------------------------------

    click.echo(f"\nCreate complete: {toolpack_id}")

    # Section 1: Tools Created (inline gate status)
    tools_data = json.loads(copied_tools.read_text())
    actions = tools_data.get("actions", [])
    click.echo(f"\n  Tools: {len(actions)} endpoints compiled")

    if gate_result and gate_result.approved_count > 0:
        click.echo(f"  Auto-approved: {gate_result.approved_count} (low/medium risk)")
        if gate_result.pending_count > 0:
            click.echo(f"  Pending review: {gate_result.pending_count} (high/critical risk)")
    else:
        click.echo(f"  Pending approvals: {sync_result.pending_count}")

    if rules_result and rules_result.rule_count > 0:
        click.echo(f"  Rules: {rules_result.template_name} ({rules_result.rule_count} rules)")

    # Example tool
    if actions:
        example = next((a for a in actions if a.get("method") == "GET"), actions[0])
        click.echo(format_example_tool(example))

    # Section 2: Auth Required
    if recipe_data and recipe_data.get("hosts"):
        from toolwright.cli.commands_auth import _host_to_env_var

        click.echo(click.style("\n  Auth:", fg="cyan"))
        for host_info in recipe_data["hosts"]:
            pattern = host_info["pattern"]
            env_var = _host_to_env_var(pattern)
            click.echo(f'    export {env_var}="Bearer <your-token>"')

    # Section 3: Connect to MCP client
    click.echo(build_mcp_integration_output(toolpack_path=toolpack_file))

    # Section 4: Next Steps
    click.echo("  Next steps:")
    if recipe_data and recipe_data.get("hosts"):
        click.echo("    1. Set your auth token (see above)")
    click.echo("    2. Run: toolwright config --toolpack " + str(toolpack_file))
    click.echo("    3. Paste config into Claude Desktop and restart")
    click.echo("    4. Ask Claude about your API!")


def register_create_commands(*, cli: click.Group, run_with_lock: Any) -> None:
    """Register the create command on the CLI group."""

    @cli.command("create")
    @click.argument("api_name", required=False)
    @click.option("--spec", help="URL or path to OpenAPI spec")
    @click.option(
        "--auto-approve/--no-auto-approve",
        default=True,
        help="Auto-approve low/medium risk tools (default: on for create).",
    )
    @click.option(
        "--rules/--no-rules",
        "apply_rules",
        default=True,
        help="Apply default behavioral rules (crud-safety).",
    )
    @click.option("--name", "-n", help="Override toolpack name")
    @click.pass_context
    def create(
        ctx: click.Context,
        api_name: str | None,
        spec: str | None,
        auto_approve: bool,
        apply_rules: bool,
        name: str | None,
    ) -> None:
        """Create governed MCP tools from an OpenAPI spec or recipe.

        \b
        Examples:
          toolwright create github                    # from bundled recipe
          toolwright create --spec ./openapi.json     # from local spec
          toolwright create --spec https://...        # from URL
        """
        resolved_output = str(ctx.obj.get("root", ""))
        if not resolved_output:
            from toolwright.utils.state import resolve_root

            resolved_output = str(resolve_root())

        run_with_lock(
            ctx,
            "create",
            lambda: run_create(
                api_name=api_name,
                spec=spec,
                name=name,
                auto_approve=auto_approve,
                apply_rules=apply_rules,
                output_root=resolved_output,
                verbose=ctx.obj.get("verbose", False),
            ),
        )
