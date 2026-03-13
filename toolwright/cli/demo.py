"""Demo command implementation (fixture capture -> compile -> toolpack)."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import click

from toolwright.cli.approve import sync_lockfile
from toolwright.cli.compile import compile_capture_session
from toolwright.core.capture.har_parser import HARParser
from toolwright.core.capture.redactor import Redactor
from toolwright.core.toolpack import (
    Toolpack,
    ToolpackOrigin,
    ToolpackPaths,
    ToolpackRuntime,
    write_toolpack,
)
from toolwright.storage import Storage


@dataclass(frozen=True)
class DemoResult:
    """Data produced by the demo compilation step."""

    tool_count: int
    root: Path
    toolpack_file: Path


def run_demo(*, output_root: str | None, verbose: bool, quiet: bool = False) -> DemoResult:
    """Generate a deterministic offline demo toolpack from bundled fixture data.

    When *quiet* is True, suppresses all stdout output (used by the wow flow
    which prints its own polished output).
    """
    root = _resolve_output_root(output_root)

    fixture = resources.files("toolwright.assets.demo").joinpath("sample.har")
    parser = HARParser(allowed_hosts=["api.example.com"])
    with resources.as_file(fixture) as fixture_path:
        session = parser.parse_file(fixture_path, name="Toolwright Demo")
    if not session.exchanges:
        click.echo("Error: Demo fixture produced no exchanges", err=True)
        sys.exit(1)

    session = Redactor().redact_session(session)

    storage = Storage(base_path=root)
    storage.save_capture(session)

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
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if not compile_result.tools_path or not compile_result.toolsets_path:
        click.echo("Error: compile did not produce required tools/toolsets artifacts", err=True)
        sys.exit(1)
    if not compile_result.policy_path or not compile_result.baseline_path:
        click.echo("Error: compile did not produce required policy/baseline artifacts", err=True)
        sys.exit(1)

    toolpack_id = _generate_toolpack_id(session.id, compile_result.artifact_id)
    toolpack_dir = root / "toolpacks" / toolpack_id
    artifact_dir = toolpack_dir / "artifact"
    lockfile_dir = toolpack_dir / "lockfile"
    lockfile_dir.mkdir(parents=True, exist_ok=True)

    shutil.copytree(compile_result.output_path, artifact_dir, dirs_exist_ok=True)

    copied_tools = artifact_dir / "tools.json"
    copied_toolsets = artifact_dir / "toolsets.yaml"
    copied_policy = artifact_dir / "policy.yaml"
    copied_baseline = artifact_dir / "baseline.json"

    pending_lockfile = lockfile_dir / "toolwright.lock.pending.yaml"
    sync_lockfile(
        tools_path=str(copied_tools),
        policy_path=str(copied_policy),
        toolsets_path=str(copied_toolsets),
        lockfile_path=str(pending_lockfile),
        capture_id=session.id,
        scope="agent_safe_readonly",
        deterministic=True,
    )

    toolpack = Toolpack(
        toolpack_id=toolpack_id,
        created_at=session.created_at,
        capture_id=session.id,
        artifact_id=compile_result.artifact_id,
        scope="agent_safe_readonly",
        allowed_hosts=sorted(set(session.allowed_hosts)),
        origin=ToolpackOrigin(
            start_url="https://demo.toolwright.local",
            name="Toolwright Demo",
        ),
        paths=ToolpackPaths(
            tools=str(copied_tools.relative_to(toolpack_dir)),
            toolsets=str(copied_toolsets.relative_to(toolpack_dir)),
            policy=str(copied_policy.relative_to(toolpack_dir)),
            baseline=str(copied_baseline.relative_to(toolpack_dir)),
            contracts="artifact/contracts.yaml",
            contract_yaml="artifact/contract.yaml",
            contract_json="artifact/contract.json",
            lockfiles={"pending": str(pending_lockfile.relative_to(toolpack_dir))},
        ),
        runtime=ToolpackRuntime(mode="local", container=None),
    )

    toolpack_file = toolpack_dir / "toolpack.yaml"
    write_toolpack(toolpack, toolpack_file)

    tools_data = json.loads(copied_tools.read_text())
    actions = sorted(
        tools_data.get("actions", []),
        key=lambda a: (a.get("method", ""), a.get("path", "")),
    )

    tool_count = len(actions)
    result = DemoResult(tool_count=tool_count, root=root, toolpack_file=toolpack_file)

    if not quiet:
        _print_standalone_output(tool_count=tool_count, actions=actions)

    return result


def _print_standalone_output(*, tool_count: int, actions: list[dict]) -> None:  # type: ignore[type-arg]
    """Print output for --offline / --generate-only mode (no wow flow)."""
    click.echo()
    click.echo(f"  Compiled {tool_count} tools from bundled API fixture.")
    click.echo()
    for action in actions:
        m = action.get("method", "?")
        p = action.get("path", "?")
        n = action.get("name", "?")
        click.echo(f"    {m:6s} {p:30s}  {n}")
    click.echo()
    click.echo("  Get started with a real API:")
    click.echo("    toolwright create github")
    click.echo()


def _resolve_output_root(output_root: str | None) -> Path:
    if output_root:
        path = Path(output_root)
        path.mkdir(parents=True, exist_ok=True)
        return path

    return Path(tempfile.mkdtemp(prefix="toolwright-demo-"))


def _generate_toolpack_id(capture_id: str, artifact_id: str) -> str:
    canonical = f"demo:{capture_id}:{artifact_id}"
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:12]
    return f"tp_{digest}"
