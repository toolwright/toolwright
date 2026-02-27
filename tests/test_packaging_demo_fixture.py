"""Packaging tests for demo fixture inclusion and wheel smoke run."""

from __future__ import annotations

import importlib.util
import os
import site
import subprocess
import sys
import tarfile
from pathlib import Path
from zipfile import ZipFile

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _venv_bin(venv_dir: Path, name: str) -> Path:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    return venv_dir / scripts_dir / name


def _build_dist(tmp_path: Path) -> tuple[Path, Path]:
    if importlib.util.find_spec("build") is None:
        pytest.skip("packaging tests require `toolwright[packaging-test]` (missing `build`)")
    if importlib.util.find_spec("hatchling") is None:
        pytest.skip("packaging tests require `toolwright[packaging-test]` (missing `hatchling`)")

    repo_root = _repo_root()
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--sdist",
            "--no-isolation",
            "--outdir",
            str(dist_dir),
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )

    wheel = next(dist_dir.glob("toolwright-*.whl"))
    sdist = next(dist_dir.glob("toolwright-*.tar.gz"))
    return wheel, sdist


def _dependency_env() -> dict[str, str]:
    dep_paths: list[str] = [p for p in site.getsitepackages() if Path(p).exists()]
    user_site = site.getusersitepackages()
    if user_site and Path(user_site).exists():
        dep_paths.append(user_site)

    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(dep_paths + ([existing] if existing else []))
    return env


def test_demo_fixture_in_wheel_and_sdist(tmp_path: Path) -> None:
    wheel, sdist = _build_dist(tmp_path)

    with ZipFile(wheel) as zf:
        assert any(name.endswith("toolwright/assets/demo/sample.har") for name in zf.namelist())

    with tarfile.open(sdist, "r:gz") as tf:
        assert any(name.endswith("toolwright/assets/demo/sample.har") for name in tf.getnames())


def test_demo_smoke_runs_from_installed_wheel(tmp_path: Path) -> None:
    wheel, _sdist = _build_dist(tmp_path)

    venv_dir = tmp_path / "wheel-venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)

    pip_bin = _venv_bin(venv_dir, "pip")
    toolwright_bin = _venv_bin(venv_dir, "toolwright")
    cask_bin = _venv_bin(venv_dir, "toolwright")

    subprocess.run([str(pip_bin), "install", "--no-deps", str(wheel)], check=True)
    env = _dependency_env()

    output_root = tmp_path / "smoke-demo-output"
    help_toolwright = subprocess.run(
        [str(toolwright_bin), "--help"],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Usage:" in help_toolwright.stdout

    help_cask = subprocess.run(
        [str(cask_bin), "--help"],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Usage:" in help_cask.stdout

    result = subprocess.run(
        [str(cask_bin), "demo", "--out", str(output_root)],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stderr == ""
    assert "Demo complete" in result.stdout
    assert (output_root / "captures").exists()
    assert (output_root / "artifacts").exists()
    assert (output_root / "toolpacks").exists()
