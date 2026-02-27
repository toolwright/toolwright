"""Container runtime emitter for toolpacks."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from toolwright.utils.runtime import docker_available

DEFAULT_BASE_IMAGE = "python:3.11-slim"
DEFAULT_USER = "toolwright"
DEFAULT_UID = 10001


@dataclass(frozen=True)
class ContainerRuntimeFiles:
    """Emitted container runtime file paths."""

    dockerfile: Path
    entrypoint: Path
    run: Path
    requirements: Path


def emit_container_runtime(
    *,
    toolpack_dir: Path,
    image: str,
    base_image: str,
    requirements_line: str,
    env_allowlist: Iterable[str],
    healthcheck_cmd: list[str] | None,
    healthcheck_interval_s: int,
    healthcheck_timeout_s: int,
    healthcheck_retries: int,
    build: bool,
) -> ContainerRuntimeFiles:
    """Emit container runtime files into the toolpack directory."""
    toolpack_dir.mkdir(parents=True, exist_ok=True)
    dockerfile_path = toolpack_dir / "Dockerfile"
    entrypoint_path = toolpack_dir / "entrypoint.sh"
    run_path = toolpack_dir / "toolwright.run"
    requirements_path = toolpack_dir / "requirements.lock"

    _write_requirements(requirements_path, requirements_line)
    _write_entrypoint(entrypoint_path, env_allowlist)
    _write_run_wrapper(run_path, image, env_allowlist)
    _write_dockerfile(
        dockerfile_path,
        base_image=base_image,
        user=DEFAULT_USER,
        uid=DEFAULT_UID,
        healthcheck_cmd=healthcheck_cmd,
        healthcheck_interval_s=healthcheck_interval_s,
        healthcheck_timeout_s=healthcheck_timeout_s,
        healthcheck_retries=healthcheck_retries,
    )

    _make_executable(entrypoint_path)
    _make_executable(run_path)

    if build:
        _run_docker_build(toolpack_dir, image)

    return ContainerRuntimeFiles(
        dockerfile=dockerfile_path,
        entrypoint=entrypoint_path,
        run=run_path,
        requirements=requirements_path,
    )


def _write_requirements(path: Path, line: str) -> None:
    path.write_text(f"{line}\n", encoding="utf-8")


def _write_entrypoint(path: Path, env_allowlist: Iterable[str]) -> None:
    allowlist = " ".join(sorted(env_allowlist))
    script = f"""#!/bin/sh
set -e

_toolwright_env_allowlist="{allowlist}"

_append_arg() {{
  if [ -n "$2" ]; then
    TOOLWRIGHT_ARGS="$TOOLWRIGHT_ARGS $1 $2"
  fi
}}

TOOLWRIGHT_ARGS="mcp serve --toolpack ${{TOOLWRIGHT_TOOLPACK:-/toolpack/toolpack.yaml}}"
_append_arg "--toolset" "$TOOLWRIGHT_TOOLSET"
_append_arg "--lockfile" "$TOOLWRIGHT_LOCKFILE"
_append_arg "--base-url" "$TOOLWRIGHT_BASE_URL"
_append_arg "--auth" "$TOOLWRIGHT_AUTH_HEADER"
_append_arg "--audit-log" "$TOOLWRIGHT_AUDIT_LOG"
_append_arg "--confirm-store" "$TOOLWRIGHT_CONFIRM_STORE"

if [ "$TOOLWRIGHT_DRY_RUN" = "1" ] || [ "$TOOLWRIGHT_DRY_RUN" = "true" ]; then
  TOOLWRIGHT_ARGS="$TOOLWRIGHT_ARGS --dry-run"
fi

if [ -n "$TOOLWRIGHT_ALLOW_PRIVATE_CIDR" ]; then
  for cidr in $TOOLWRIGHT_ALLOW_PRIVATE_CIDR; do
    TOOLWRIGHT_ARGS="$TOOLWRIGHT_ARGS --allow-private-cidr $cidr"
  done
fi

if [ "$TOOLWRIGHT_ALLOW_REDIRECTS" = "1" ] || [ "$TOOLWRIGHT_ALLOW_REDIRECTS" = "true" ]; then
  TOOLWRIGHT_ARGS="$TOOLWRIGHT_ARGS --allow-redirects"
fi

exec toolwright $TOOLWRIGHT_ARGS
"""
    path.write_text(script, encoding="utf-8")


def _write_run_wrapper(path: Path, image: str, env_allowlist: Iterable[str]) -> None:
    allowlist = " ".join(sorted(env_allowlist))
    script = f"""#!/bin/sh
set -e

_toolwright_env_allowlist="{allowlist}"

DOCKER_ARGS=""
for var in $_toolwright_env_allowlist; do
  eval value="\\$$var"
  if [ -n "$value" ]; then
    DOCKER_ARGS="$DOCKER_ARGS -e $var"
  fi
done

exec docker run -i --rm $DOCKER_ARGS "{image}"
"""
    path.write_text(script, encoding="utf-8")


def _write_dockerfile(
    path: Path,
    *,
    base_image: str,
    user: str,
    uid: int,
    healthcheck_cmd: list[str] | None,
    healthcheck_interval_s: int,
    healthcheck_timeout_s: int,
    healthcheck_retries: int,
) -> None:
    lines = [
        f"FROM {base_image}",
        f"RUN useradd -m -u {uid} {user}",
        "WORKDIR /toolpack",
        "COPY requirements.lock /toolpack/requirements.lock",
        "RUN pip install --no-cache-dir -r requirements.lock",
        "COPY . /toolpack",
        f"RUN chown -R {user}:{user} /toolpack",
        f"USER {user}",
    ]

    if healthcheck_cmd:
        cmd = ", ".join(f"\"{part}\"" for part in healthcheck_cmd)
        lines.append(
            f"HEALTHCHECK --interval={healthcheck_interval_s}s "
            f"--timeout={healthcheck_timeout_s}s --retries={healthcheck_retries} "
            f"CMD [{cmd}]"
        )

    lines.append('ENTRYPOINT ["./entrypoint.sh"]')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | 0o111)


def _run_docker_build(toolpack_dir: Path, image: str) -> None:
    if not docker_available():
        raise RuntimeError("docker not available")
    subprocess.run(
        ["docker", "build", "-t", image, "."],
        cwd=str(toolpack_dir),
        check=True,
        capture_output=True,
        text=True,
    )
