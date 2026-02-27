"""Init command — auto-detect project context and generate starter config."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml

from toolwright.core.init.detector import (
    detect_project,
    generate_config,
    generate_gitignore_entries,
)


def run_init(
    *,
    directory: str,
    verbose: bool,
) -> None:
    """Initialize Toolwright in a project directory."""
    project_dir = Path(directory).resolve()
    if not project_dir.exists():
        click.echo(f"Error: Directory not found: {project_dir}", err=True)
        sys.exit(1)

    detection = detect_project(project_dir)

    if verbose:
        click.echo("Project detection:")
        click.echo(f"  Type: {detection.project_type}")
        click.echo(f"  Language: {detection.language}")
        click.echo(f"  Package manager: {detection.package_manager}")
        if detection.frameworks:
            click.echo(f"  Frameworks: {', '.join(detection.frameworks)}")
        if detection.api_specs:
            click.echo(f"  API specs: {', '.join(detection.api_specs)}")

    if detection.has_existing_toolwright:
        click.echo(".toolwright/ already exists — will not overwrite existing config.")
        if verbose:
            for suggestion in detection.suggestions:
                click.echo(f"  Suggestion: {suggestion}")
        return

    # Create .toolwright/ directory structure
    toolwright_dir = project_dir / ".toolwright"
    toolwright_dir.mkdir(parents=True, exist_ok=True)
    (toolwright_dir / "captures").mkdir(exist_ok=True)
    (toolwright_dir / "artifacts").mkdir(exist_ok=True)
    (toolwright_dir / "reports").mkdir(exist_ok=True)

    # Write config.yaml
    config = generate_config(detection)
    config_path = toolwright_dir / "config.yaml"
    config_path.write_text(yaml.dump(config, sort_keys=False), encoding="utf-8")

    # Append to .gitignore if it exists
    gitignore_path = project_dir / ".gitignore"
    gitignore_entries = generate_gitignore_entries()
    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8")
        if "# Toolwright" not in existing:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write("\n" + "\n".join(gitignore_entries) + "\n")
    else:
        gitignore_path.write_text("\n".join(gitignore_entries) + "\n", encoding="utf-8")

    click.echo(f"✓ Initialized Toolwright in {toolwright_dir}")
    click.echo(f"  Config: {config_path}")

    # Print next steps — show all entry paths so users know their options.
    click.echo()
    click.echo("What's next (pick the path that fits):")
    if detection.api_specs:
        spec = detection.api_specs[0]
        click.echo(f"  A. toolwright capture import {spec} --input-format openapi -a <api-host>")
        click.echo("     You have an OpenAPI spec — import it directly.")
    else:
        click.echo("  A. toolwright mint <start-url> -a <api-host>")
        click.echo("     Point toolwright at your app and capture live traffic (requires Playwright).")
        click.echo("  B. toolwright capture import <file.har> -a <api-host>")
        click.echo("     Import a HAR file from your browser's DevTools.")
        click.echo("  C. toolwright capture import <spec> --input-format openapi -a <api-host>")
        click.echo("     Import an OpenAPI spec (URL or local file).")
    click.echo()
    click.echo("  Then: toolwright gate allow --all   (approve tools)")
    click.echo("        toolwright serve --toolpack <path>   (start MCP server)")
    click.echo("        toolwright config --toolpack <path>   (generate MCP client config)")


def run_mcp_config(
    *,
    toolpack_path: str,
    client: str,
) -> None:
    """Generate MCP client configuration for a toolpack."""
    tp_path = Path(toolpack_path)
    if not tp_path.exists():
        click.echo(f"Error: Toolpack not found: {tp_path}", err=True)
        sys.exit(1)

    config = _build_mcp_client_config(tp_path, client)
    click.echo(json.dumps(config, indent=2))


def _build_mcp_client_config(toolpack_path: Path, client: str) -> dict[str, object]:
    """Build MCP client config for different clients."""
    tp_dir = toolpack_path.parent if toolpack_path.is_file() else toolpack_path
    tp_file = str(toolpack_path.resolve())

    # Try to find tools and policy paths
    tools_path = _find_artifact(tp_dir, "tools.json")
    policy_path = _find_artifact(tp_dir, "policy.yaml")

    base_args = [
        "toolwright", "run",
        "--toolpack", tp_file,
    ]
    if tools_path:
        base_args.extend(["--tools", str(tools_path)])
    if policy_path:
        base_args.extend(["--policy", str(policy_path)])

    if client in {"claude", "cursor"}:
        return {
            "mcpServers": {
                "toolwright": {
                    "command": base_args[0],
                    "args": base_args[1:],
                }
            }
        }
    else:
        # Generic stdio config
        return {
            "server": {
                "name": "toolwright",
                "transport": "stdio",
                "command": base_args,
            }
        }


def _find_artifact(tp_dir: Path, filename: str) -> Path | None:
    """Find an artifact file within the toolpack directory."""
    # Check direct and under artifact/
    for candidate in [tp_dir / filename, tp_dir / "artifact" / filename]:
        if candidate.exists():
            return candidate.resolve()
    return None
