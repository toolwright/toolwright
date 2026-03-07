"""Keep the hero demo screenplay aligned with the bundled demo fixture."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import yaml

from toolwright.cli.enforce import EnforcementGateway


def _latest_toolpack(output_root: Path) -> Path:
    toolpacks = sorted(
        output_root.glob("toolpacks/*/toolpack.yaml"),
        key=lambda path: path.stat().st_mtime,
    )
    assert toolpacks, "Expected toolwright demo to create a toolpack fixture"
    return toolpacks[-1]


def _resolve_artifact_paths(toolpack_path: Path) -> tuple[Path, Path, Path]:
    payload = yaml.safe_load(toolpack_path.read_text())
    toolpack_dir = toolpack_path.parent
    paths = payload["paths"]
    return (
        toolpack_dir / paths["tools"],
        toolpack_dir / paths["toolsets"],
        toolpack_dir / paths["policy"],
    )


def _gateway(lockfile: Path, tools: Path, toolsets: Path, policy: Path, store: Path) -> EnforcementGateway:
    return EnforcementGateway(
        tools_path=str(tools),
        toolsets_path=str(toolsets),
        policy_path=str(policy),
        lockfile_path=str(lockfile),
        mode="proxy",
        dry_run=True,
        confirmation_store_path=str(store),
    )


def _run_toolwright(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "toolwright", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def test_hero_screenplay_matches_demo_fixture_governance_flow(tmp_path: Path) -> None:
    output_root = tmp_path / "demo"
    lockfile = tmp_path / "hero.lock.yaml"
    confirmation_store = tmp_path / ".toolwright" / "confirmations.db"
    confirmation_store.parent.mkdir(parents=True, exist_ok=True)

    screenplay_text = Path("demos/screenplays/hero.yaml").read_text()
    assert "delete_user" in screenplay_text
    assert "denied_not_approved" in screenplay_text

    demo_result = _run_toolwright(tmp_path, "demo", "--generate-only", "--out", str(output_root))
    assert demo_result.returncode == 0, demo_result.stdout + demo_result.stderr

    toolpack_path = _latest_toolpack(output_root)
    tools, toolsets, policy = _resolve_artifact_paths(toolpack_path)

    sync_result = _run_toolwright(
        tmp_path,
        "gate",
        "sync",
        "--tools",
        str(tools),
        "--policy",
        str(policy),
        "--toolsets",
        str(toolsets),
        "--lockfile",
        str(lockfile),
    )
    assert sync_result.returncode in {0, 1}, sync_result.stdout + sync_result.stderr
    assert lockfile.exists()

    blocked = _gateway(lockfile, tools, toolsets, policy, confirmation_store).execute_action(
        "delete_user",
        {"id": "usr_1"},
    )
    assert blocked["decision"] == "deny"
    assert blocked["reason_code"] == "denied_not_approved"

    allow_result = _run_toolwright(
        tmp_path,
        "gate",
        "allow",
        "--all",
        "--lockfile",
        str(lockfile),
        "--by",
        "ci@toolwright",
        "-y",
    )
    assert allow_result.returncode == 0, allow_result.stdout + allow_result.stderr

    confirm_needed = _gateway(lockfile, tools, toolsets, policy, confirmation_store).execute_action(
        "delete_user",
        {"id": "usr_1"},
    )
    assert confirm_needed["decision"] == "confirm"
    token = confirm_needed["confirmation_token_id"]
    assert token

    grant_result = _run_toolwright(
        tmp_path,
        "confirm",
        "grant",
        token,
        "--store",
        str(confirmation_store),
    )
    assert grant_result.returncode == 0, grant_result.stdout + grant_result.stderr

    allowed = _gateway(lockfile, tools, toolsets, policy, confirmation_store).execute_action(
        "delete_user",
        {"id": "usr_1"},
        token,
    )
    assert allowed["decision"] == "allow"
    assert allowed["allowed"] is True
