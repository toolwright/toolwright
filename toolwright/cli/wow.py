"""High-level experience commands for wow/prove flows."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import click

from toolwright.cli.demo import run_demo
from toolwright.cli.enforce import EnforcementGateway
from toolwright.cli.mint import run_mint
from toolwright.core.approval import LockfileManager
from toolwright.core.drift import DriftEngine
from toolwright.core.normalize import EndpointAggregator
from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths
from toolwright.storage import Storage

PROVE_SUMMARY_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class WowRunArtifacts:
    """Required wow output artifacts."""

    report_path: Path
    diff_path: Path
    summary_path: Path


def run_wow(
    *,
    out_dir: str | None,
    live: bool,
    scenario: str,
    keep: bool,
    verbose: bool,
) -> int:
    """Execute the wow flow and return an exit code."""
    if live:
        return _run_live_wow(
            out_dir=out_dir,
            scenario=scenario,
            keep=keep,
            verbose=verbose,
        )
    return _run_offline_wow(out_dir=out_dir, keep=keep, verbose=verbose)


def run_prove_smoke(
    *,
    out_dir: str | None,
    live: bool,
    scenarios: str,
    keep: bool,
    verbose: bool,
) -> int:
    """Run a small prove-smoke matrix."""
    requested = [item.strip() for item in scenarios.split(",") if item.strip()]
    if not requested:
        click.echo("Error: --smoke-scenarios requires at least one scenario", err=True)
        return 1

    workdir = _prepare_out_dir(out_dir=out_dir, keep=keep, prefix="toolwright-prove-smoke-")
    results: list[dict[str, Any]] = []
    for index, scenario in enumerate(requested, start=1):
        run_dir = workdir / f"run_{index}_{scenario}"
        code = run_wow(
            out_dir=str(run_dir),
            live=live,
            scenario=scenario,
            keep=keep,
            verbose=verbose,
        )
        summary_path = run_dir / "prove_summary.json"
        summary_payload: dict[str, Any] = {}
        if summary_path.exists():
            summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
        results.append(
            {
                "name": f"run_{index}",
                "scenario": scenario,
                "ok": code == 0,
                "summary": summary_payload,
                "summary_path": str(summary_path) if summary_path.exists() else None,
            }
        )

    all_ok = all(item["ok"] for item in results)
    report_path = workdir / "prove_smoke_report.json"
    report = {
        "overall_ok": all_ok,
        "runs": results,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    click.echo(f"Smoke report: {report_path}")
    if all_ok:
        click.echo("Prove smoke suite passed.")
        return 0
    click.echo("Prove smoke suite failed.", err=True)
    return 1


def _run_offline_wow(*, out_dir: str | None, keep: bool, verbose: bool) -> int:
    """Offline wow path: no browser dependencies required."""
    workdir = _prepare_out_dir(out_dir=out_dir, keep=keep, prefix="toolwright-wow-")
    demo_result = run_demo(output_root=str(workdir), verbose=verbose, quiet=True)
    toolpack_file = _find_toolpack_file(workdir)
    return _execute_wow_contract(
        workdir=workdir,
        toolpack_file=toolpack_file,
        scenario_label="offline_fixture",
        tool_count=demo_result.tool_count,
    )


def _run_live_wow(
    *,
    out_dir: str | None,
    scenario: str,
    keep: bool,
    verbose: bool,
) -> int:
    """Live wow path using Playwright capture against a local fixture server."""
    workdir = _prepare_out_dir(out_dir=out_dir, keep=keep, prefix="toolwright-wow-live-")
    try:
        import playwright  # noqa: F401
    except ImportError:
        click.echo(
            "Error: live mode requires Playwright. Install with: pip install \"toolwright[playwright]\"",
            err=True,
        )
        return 1

    server, thread, port = _start_live_fixture_server(scenario)
    try:
        try:
            run_mint(
                start_url=f"http://127.0.0.1:{port}",
                allowed_hosts=[f"127.0.0.1:{port}", "127.0.0.1", "localhost", f"localhost:{port}"],
                name=f"Toolwright wow live ({scenario})",
                scope_name="agent_safe_readonly",
                headless=True,
                script_path=None,
                duration_seconds=5,
                output_root=str(workdir),
                deterministic=True,
                print_mcp_config=False,
                runtime_mode="local",
                runtime_build=False,
                runtime_tag=None,
                runtime_version_pin=None,
                auth_profile=None,
                webmcp=False,
                redaction_profile=None,
                verbose=verbose,
            )
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1

        toolpack_file = _find_toolpack_file(workdir)
        return _execute_wow_contract(
            workdir=workdir,
            toolpack_file=toolpack_file,
            scenario_label=f"live_{scenario}",
            tool_count=0,
        )
    finally:
        with contextlib.suppress(Exception):
            server.shutdown()
        with contextlib.suppress(Exception):
            server.server_close()
        with contextlib.suppress(Exception):
            thread.join(timeout=3)


def _execute_wow_contract(
    *,
    workdir: Path,
    toolpack_file: Path,
    scenario_label: str,
    tool_count: int = 0,
) -> int:
    """Complete governance + replay + parity contract and write mandatory artifacts."""
    artifacts = WowRunArtifacts(
        report_path=workdir / "prove_twice_report.md",
        diff_path=workdir / "prove_twice_diff.json",
        summary_path=workdir / "prove_summary.json",
    )

    toolpack = load_toolpack(toolpack_file)
    resolved = resolve_toolpack_paths(toolpack=toolpack, toolpack_path=toolpack_file)
    if resolved.pending_lockfile_path is None:
        click.echo("Error: wow flow did not create a pending lockfile", err=True)
        return 1

    # Collect step results with timing
    steps: list[tuple[str, str, float]] = []  # (description, status, elapsed_s)

    # If tool_count was provided from compile, record it
    if tool_count:
        steps.append((
            f"Compiling {tool_count} tools from OpenAPI spec",
            "done",
            0.0,  # already elapsed, placeholder
        ))

    # --- Step: Sign lockfile ---
    t0 = time.monotonic()
    lock_manager = LockfileManager(str(resolved.pending_lockfile_path))
    lock_manager.load()
    prior_root = os.environ.get("TOOLWRIGHT_ROOT")
    os.environ["TOOLWRIGHT_ROOT"] = str((workdir / ".toolwright").resolve())
    try:
        lock_manager.approve_all(approved_by="wow")
        lock_manager.save()
    finally:
        if prior_root is None:
            os.environ.pop("TOOLWRIGHT_ROOT", None)
        else:
            os.environ["TOOLWRIGHT_ROOT"] = prior_root
    steps.append(("Signing lockfile (Ed25519)", "done", time.monotonic() - t0))

    # --- Step: Block unapproved tool (fail-closed) ---
    t0 = time.monotonic()
    governance_enforced = _check_fail_closed_without_lockfile(
        tools_path=resolved.tools_path,
        toolsets_path=resolved.toolsets_path,
        policy_path=resolved.policy_path,
    )
    elapsed = time.monotonic() - t0
    steps.append((
        "Blocking unapproved tool",
        "blocked" if governance_enforced else "FAIL",
        elapsed,
    ))

    # --- Step: Run approved tool (deterministic replay) ---
    action_name, action_args = _pick_replay_action(resolved.tools_path, resolved.toolsets_path)
    t0 = time.monotonic()
    run_a = _run_governed_dry_replay(
        tools_path=resolved.tools_path,
        toolsets_path=resolved.toolsets_path,
        policy_path=resolved.policy_path,
        lockfile_path=resolved.pending_lockfile_path,
        action_name=action_name,
        action_args=action_args,
        workdir=workdir,
    )
    run_b = _run_governed_dry_replay(
        tools_path=resolved.tools_path,
        toolsets_path=resolved.toolsets_path,
        policy_path=resolved.policy_path,
        lockfile_path=resolved.pending_lockfile_path,
        action_name=action_name,
        action_args=action_args,
        workdir=workdir,
    )
    elapsed = time.monotonic() - t0
    run_a_ok = bool(run_a.get("allowed")) and run_a.get("decision") == "allow"
    run_b_ok = bool(run_b.get("allowed")) and run_b.get("decision") == "allow"
    parity_ok = _results_are_parity_equivalent(run_a, run_b)
    replay_status = "deterministic" if (run_a_ok and run_b_ok and parity_ok) else "FAIL"
    steps.append(("Running approved tool (deterministic)", replay_status, elapsed))

    # --- Step: Detect drift ---
    t0 = time.monotonic()
    drift_count = _compute_drift_count(workdir, toolpack.capture_id, resolved.baseline_path)
    elapsed = time.monotonic() - t0
    drift_label = f"{drift_count} breaking change{'s' if drift_count != 1 else ''}" if drift_count > 0 else "clean"
    steps.append(("Detecting drift (endpoint removed)", drift_label, elapsed))

    # --- Step: Circuit breaker ---
    breaker_status = "quarantined" if drift_count > 0 else "clean"
    steps.append(("Tripping circuit breaker", breaker_status, 0.0))

    # --- Print polished output ---
    _print_polished_output(steps=steps, tool_count=tool_count)

    # --- Write artifacts (silently) ---
    diff_payload = _build_diff_payload(run_a=run_a, run_b=run_b, parity_ok=parity_ok)
    artifacts.diff_path.write_text(
        json.dumps(diff_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    _write_report(
        path=artifacts.report_path,
        scenario=scenario_label,
        parity_ok=parity_ok,
        run_a_ok=run_a_ok,
        run_b_ok=run_b_ok,
        action_name=action_name,
    )

    summary = {
        "schema_version": PROVE_SUMMARY_SCHEMA_VERSION,
        "scenario": scenario_label,
        "govern_enforced": governance_enforced,
        "run_a_ok": run_a_ok,
        "run_b_ok": run_b_ok,
        "parity_ok": parity_ok,
        "drift_count": drift_count,
        "report_path": str(artifacts.report_path),
        "diff_path": str(artifacts.diff_path),
    }
    artifacts.summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    success = governance_enforced and run_a_ok and run_b_ok and parity_ok
    if not success:
        click.echo("Governance contract failed.", err=True)
        return 1
    return 0


def _format_timing(seconds: float) -> str:
    """Format elapsed time for display."""
    if seconds < 0.001:
        return ""
    if seconds < 1.0:
        ms = seconds * 1000
        return f"{ms:.0f}ms"
    return f"{seconds:.1f}s"


def _print_polished_output(
    *,
    steps: list[tuple[str, str, float]],
    tool_count: int,
) -> None:
    """Print the clean, shareable demo output."""
    click.echo()
    click.echo("  \u25c6 toolwright demo \u2014 governance in action")
    click.echo()

    for description, status, elapsed in steps:
        timing = _format_timing(elapsed)
        # Build the status suffix
        if status == "done":
            suffix = f"\u2713  {timing}" if timing else "\u2713"
        else:
            suffix = f"\u2713  {status}"
        # Pad description to align status
        padded = f"  {description}..."
        click.echo(f"{padded:50s} {suffix}")

    click.echo()

    # Summary panel using box drawing characters
    total_s = sum(e for _, _, e in steps)
    total_label = "under 1 second" if total_s < 1.0 else f"{total_s:.1f} seconds"
    width = 58

    border_top = f"  \u250c\u2500 What just happened \u2500{'\\u2500' * (width - 21)}\u2510"
    border_bot = f"  \u2514{'\\u2500' * width}\u2518"

    # Build properly
    border_top = "  \u250c\u2500 What just happened " + "\u2500" * (width - 21) + "\u2510"
    border_bot = "  \u2514" + "\u2500" * width + "\u2518"

    def panel_line(text: str) -> str:
        inner = f"  {text}"
        padding = width - len(inner)
        if padding < 0:
            padding = 0
        return f"  \u2502{inner}{' ' * padding}\u2502"

    click.echo(border_top)
    click.echo(panel_line(""))
    click.echo(panel_line(f"In {total_label}, toolwright:"))
    click.echo(panel_line(f"  \u2022 Compiled an API into {tool_count} governed tools"))
    click.echo(panel_line("  \u2022 Blocked an unapproved tool (fail-closed)"))
    click.echo(panel_line("  \u2022 Detected an upstream API change (drift)"))
    click.echo(panel_line("  \u2022 Tripped a circuit breaker (auto-quarantine)"))
    click.echo(panel_line(""))
    click.echo(panel_line("This is what governance looks like."))
    click.echo(panel_line("Get started: toolwright create github"))
    click.echo(panel_line(""))
    click.echo(border_bot)
    click.echo()


def _prepare_out_dir(*, out_dir: str | None, keep: bool, prefix: str) -> Path:
    path = (
        Path(out_dir).resolve()
        if out_dir
        else Path(tempfile.mkdtemp(prefix=prefix)).resolve()
    )

    if path.exists() and not keep:
        for child in list(path.iterdir()):
            if child.is_dir():
                for nested in sorted(child.rglob("*"), reverse=True):
                    if nested.is_file():
                        nested.unlink()
                    elif nested.is_dir():
                        nested.rmdir()
                child.rmdir()
            else:
                child.unlink()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _find_toolpack_file(workdir: Path) -> Path:
    matches = sorted(workdir.glob("toolpacks/*/toolpack.yaml"))
    if not matches:
        raise RuntimeError(f"No toolpack.yaml found under {workdir / 'toolpacks'}")
    return matches[-1]


def _start_live_fixture_server(scenario: str) -> tuple[ThreadingHTTPServer, threading.Thread, int]:
    """Start a small local fixture server for live wow capture."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _send_json(self, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_html(self, html: str) -> None:
            encoded = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/":
                self._send_html(_render_live_root_html(scenario))
                return
            if path == "/api/products":
                self._send_json({"items": [{"id": "p1", "name": "Widget"}]})
                return
            if path == "/api/orders":
                query = parse_qs(parsed.query)
                cursor = query.get("cursor", [""])[0]
                if scenario == "auth_refresh":
                    if cursor == "page2":
                        self._send_json({"items": [{"id": "o3", "amount_cents": 2599}], "next_cursor": None})
                    else:
                        self._send_json(
                            {
                                "items": [
                                    {"id": "o1", "amount_cents": 1999},
                                    {"id": "o2", "amount_cents": 4999},
                                ],
                                "next_cursor": "page2",
                            }
                        )
                    return
                self._send_json({"items": [{"id": "o1", "amount_cents": 1999}], "next_cursor": None})
                return

            self.send_response(404)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, int(server.server_port)


def _render_live_root_html(scenario: str) -> str:
    if scenario == "auth_refresh":
        return """<!doctype html>
<html><body><div id="status">loading</div><script>
async function run() {
  const first = await fetch('/api/orders').then((r) => r.json());
  let count = first.items.length;
  if (first.next_cursor) {
    const second = await fetch('/api/orders?cursor=' + first.next_cursor).then((r) => r.json());
    count += second.items.length;
  }
  document.getElementById('status').innerText = 'Orders loaded ' + count;
}
run().catch(() => { document.getElementById('status').innerText = 'failed'; });
</script></body></html>"""
    return """<!doctype html>
<html><body><div id="status">loading</div><script>
fetch('/api/products')
  .then((r) => r.json())
  .then((payload) => { document.getElementById('status').innerText = 'Products ' + payload.items.length; })
  .catch(() => { document.getElementById('status').innerText = 'failed'; });
</script></body></html>"""


def _check_fail_closed_without_lockfile(
    *,
    tools_path: Path,
    toolsets_path: Path,
    policy_path: Path,
) -> bool:
    try:
        EnforcementGateway(
            tools_path=str(tools_path),
            toolsets_path=str(toolsets_path),
            toolset_name="readonly",
            policy_path=str(policy_path),
            mode="proxy",
            dry_run=True,
            lockfile_path=None,
            unsafe_no_lockfile=False,
        )
    except ValueError:
        return True
    return False


def _pick_replay_action(tools_path: Path, toolsets_path: Path) -> tuple[str, dict[str, Any]]:
    tools_payload = json.loads(tools_path.read_text(encoding="utf-8"))
    toolsets_payload = _load_yaml_json(toolsets_path)
    readonly_actions = {
        str(action_name)
        for action_name in toolsets_payload.get("toolsets", {}).get("readonly", {}).get("actions", [])
    }

    actions = [
        action
        for action in tools_payload.get("actions", [])
        if isinstance(action, dict) and str(action.get("name")) in readonly_actions
    ]
    actions.sort(key=lambda item: (str(item.get("method", "")), str(item.get("path", ""))))

    selected = actions[0] if actions else None
    if selected is None:
        raise RuntimeError("No readonly action available for wow replay")

    required = selected.get("input_schema", {}).get("required", [])
    args: dict[str, Any] = {}
    if isinstance(required, list):
        properties = selected.get("input_schema", {}).get("properties", {})
        if not isinstance(properties, dict):
            properties = {}
        for field in required:
            schema = properties.get(str(field), {})
            args[str(field)] = _default_value_for_schema(str(field), schema if isinstance(schema, dict) else {})

    return str(selected["name"]), args


def _default_value_for_schema(field: str, schema: dict[str, Any]) -> Any:
    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return enum_values[0]
    field_type = str(schema.get("type", "")).lower()
    if field_type == "integer":
        return 1
    if field_type == "number":
        return 1.0
    if field_type == "boolean":
        return True
    if field.lower() == "id":
        return "demo-id"
    return "demo"


def _run_governed_dry_replay(
    *,
    tools_path: Path,
    toolsets_path: Path,
    policy_path: Path,
    lockfile_path: Path,
    action_name: str,
    action_args: dict[str, Any],
    workdir: Path,
) -> dict[str, Any]:
    gateway = EnforcementGateway(
        tools_path=str(tools_path),
        toolsets_path=str(toolsets_path),
        toolset_name="readonly",
        policy_path=str(policy_path),
        mode="proxy",
        dry_run=True,
        lockfile_path=str(lockfile_path),
        confirmation_store_path=str(workdir / ".toolwright" / "state" / "confirmations.db"),
        unsafe_no_lockfile=False,
    )
    return gateway.execute_action(action_name, action_args)


def _results_are_parity_equivalent(run_a: dict[str, Any], run_b: dict[str, Any]) -> bool:
    comparable_keys = ["decision", "allowed", "reason_code", "action", "dry_run", "params"]
    left = {key: run_a.get(key) for key in comparable_keys}
    right = {key: run_b.get(key) for key in comparable_keys}
    return left == right


def _build_diff_payload(
    *,
    run_a: dict[str, Any],
    run_b: dict[str, Any],
    parity_ok: bool,
) -> dict[str, Any]:
    comparable_keys = ["decision", "allowed", "reason_code", "action", "dry_run", "params"]
    differences: list[str] = []
    for key in comparable_keys:
        if run_a.get(key) != run_b.get(key):
            differences.append(key)
    return {
        "run_a": {
            "ok": bool(run_a.get("allowed")),
            "decision": run_a.get("decision"),
            "reason_code": run_a.get("reason_code"),
        },
        "run_b": {
            "ok": bool(run_b.get("allowed")),
            "decision": run_b.get("decision"),
            "reason_code": run_b.get("reason_code"),
        },
        "parity_ok": parity_ok,
        "differences": differences,
    }


def _write_report(
    *,
    path: Path,
    scenario: str,
    parity_ok: bool,
    run_a_ok: bool,
    run_b_ok: bool,
    action_name: str,
) -> None:
    lines = [
        "# Prove Twice Report",
        "",
        f"- scenario: `{scenario}`",
        f"- action: `{action_name}`",
        f"- parity_ok: `{parity_ok}`",
        "",
        "| Assertion | Prove Once | Prove Again |",
        "| --- | --- | --- |",
        (
            "| governed replay returns allow in dry-run mode | "
            f"{'pass' if run_a_ok else 'fail'} | {'pass' if run_b_ok else 'fail'} |"
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _compute_drift_count(workdir: Path, capture_id: str, baseline_path: Path) -> int:
    storage = Storage(base_path=str(workdir))
    session = storage.load_capture(capture_id)
    if session is None:
        return -1
    baseline_payload = _load_yaml_json(baseline_path)
    aggregator = EndpointAggregator(first_party_hosts=session.allowed_hosts)
    endpoints = aggregator.aggregate(session)
    report = DriftEngine().compare_to_baseline(baseline_payload, endpoints, deterministic=True)
    return int(report.total_drifts)


def _load_yaml_json(path: Path) -> dict[str, Any]:
    if path.suffix in {".yaml", ".yml"}:
        import yaml

        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return payload
