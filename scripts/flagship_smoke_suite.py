#!/usr/bin/env python3
"""Run repeatable flagship smoke scenarios for release readiness."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROVE_TWICE_SCRIPT = REPO_ROOT / "scripts" / "prove_twice_demo.py"


@dataclass
class ScenarioResult:
    name: str
    scenario: str
    ok: bool
    seconds: float
    details: str


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )


def _read_parity_ok(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("- parity_ok:"):
            return "`True`" in line
    return False


def _parse_scenarios(raw: str) -> list[str]:
    items = [item.strip() for item in raw.split(",")]
    scenarios = [item for item in items if item]
    if not scenarios:
        raise ValueError("at least one scenario must be provided")
    return scenarios


def _read_auth_refresh_ok(workdir: Path) -> tuple[bool, str]:
    checks_path = workdir / "auth_refresh_checks.json"
    if not checks_path.exists():
        return False, "missing auth_refresh_checks.json"
    payload = json.loads(checks_path.read_text(encoding="utf-8"))
    if not bool(payload.get("ok")):
        return False, f"auth refresh checks failed: {checks_path}"
    oauth_calls = int(payload.get("oauth_token_request_count", 0))
    orders_calls = int(payload.get("orders_request_count", 0))
    return True, f"auth_checks={checks_path} oauth_calls={oauth_calls} orders_calls={orders_calls}"


def _run_prove_twice_scenario(name: str, scenario: str, workdir: Path) -> ScenarioResult:
    started = time.perf_counter()
    proc = _run(
        [
            sys.executable,
            str(PROVE_TWICE_SCRIPT),
            "--scenario",
            scenario,
            "--workdir",
            str(workdir),
        ]
    )
    elapsed = time.perf_counter() - started

    if proc.returncode != 0:
        details = (proc.stderr or proc.stdout or "prove_twice failed").strip()
        return ScenarioResult(name=name, scenario=scenario, ok=False, seconds=elapsed, details=details)

    report = workdir / "prove_twice_report.md"
    diff_json = workdir / "prove_twice_diff.json"
    if not report.exists() or not diff_json.exists():
        return ScenarioResult(
            name=name,
            scenario=scenario,
            ok=False,
            seconds=elapsed,
            details="expected prove_twice report artifacts were not produced",
        )

    parity_ok = _read_parity_ok(report)
    diff_payload = json.loads(diff_json.read_text(encoding="utf-8"))
    run_a_ok = bool(diff_payload.get("run_a", {}).get("ok"))
    run_b_ok = bool(diff_payload.get("run_b", {}).get("ok"))

    if not (parity_ok and run_a_ok and run_b_ok):
        return ScenarioResult(
            name=name,
            scenario=scenario,
            ok=False,
            seconds=elapsed,
            details=(
                f"parity_ok={parity_ok}, "
                f"run_a_ok={run_a_ok}, run_b_ok={run_b_ok}"
            ),
        )

    extra = ""
    if scenario == "auth_refresh":
        auth_ok, auth_details = _read_auth_refresh_ok(workdir)
        if not auth_ok:
            return ScenarioResult(
                name=name,
                scenario=scenario,
                ok=False,
                seconds=elapsed,
                details=auth_details,
            )
        extra = f" {auth_details}"

    return ScenarioResult(
        name=name,
        scenario=scenario,
        ok=True,
        seconds=elapsed,
        details=f"report={report} diff={diff_json}{extra}",
    )


def _write_report(path: Path, results: list[ScenarioResult]) -> None:
    all_ok = all(item.ok for item in results)
    lines = [
        "# Flagship Smoke Suite",
        "",
        f"- overall_ok: `{all_ok}`",
        f"- scenarios: `{len(results)}`",
        "",
        "| Scenario | Status | Seconds | Details |",
        "| --- | --- | ---: | --- |",
    ]
    for item in results:
        status = "pass" if item.ok else "fail"
        lines.append(
            f"| {item.name} ({item.scenario}) | {status} | "
            f"{item.seconds:.2f} | {item.details} |"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run flagship smoke scenarios.")
    parser.add_argument(
        "--workdir",
        default="/tmp/flagship_smoke_suite",
        help="Directory for scenario outputs.",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep existing workdir contents (default clears workdir).",
    )
    parser.add_argument(
        "--scenarios",
        default="basic_products,auth_refresh",
        help="Comma-separated prove-twice scenarios to run.",
    )
    args = parser.parse_args(argv)

    workdir = Path(args.workdir).resolve()
    if workdir.exists() and not args.keep:
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    scenarios = _parse_scenarios(args.scenarios)
    results: list[ScenarioResult] = []
    for index, scenario in enumerate(scenarios, start=1):
        name = f"prove_twice_run_{index}"
        results.append(
            _run_prove_twice_scenario(name, scenario, workdir / f"{name}_{scenario}")
        )

    report_path = workdir / "flagship_smoke_report.md"
    _write_report(report_path, results)

    print(f"\nSmoke report: {report_path}")
    if all(item.ok for item in results):
        print("Flagship smoke suite passed.")
        return 0

    print("Flagship smoke suite failed.", file=sys.stderr)
    for item in results:
        if not item.ok:
            print(f"- {item.name}: {item.details}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
