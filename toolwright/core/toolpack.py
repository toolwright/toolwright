"""Toolpack models and path resolution helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from toolwright.core.runtime.container import DEFAULT_BASE_IMAGE
from toolwright.utils.schema_version import CURRENT_SCHEMA_VERSION, resolve_schema_version


def _default_env_allowlist() -> list[str]:
    return [
        "TOOLWRIGHT_TOOLPACK",
        "TOOLWRIGHT_TOOLSET",
        "TOOLWRIGHT_LOCKFILE",
        "TOOLWRIGHT_BASE_URL",
        "TOOLWRIGHT_AUTH_HEADER",
        "TOOLWRIGHT_AUDIT_LOG",
        "TOOLWRIGHT_DRY_RUN",
        "TOOLWRIGHT_CONFIRM_STORE",
        "TOOLWRIGHT_ALLOW_PRIVATE_CIDR",
        "TOOLWRIGHT_ALLOW_REDIRECTS",
    ]


class ToolpackRuntimeHealthcheck(BaseModel):
    """Container healthcheck configuration."""

    cmd: list[str] = Field(
        default_factory=lambda: [
            "toolwright",
            "doctor",
            "--runtime",
            "local",
            "--toolpack",
            "/toolpack/toolpack.yaml",
        ]
    )
    interval_s: int = 10
    timeout_s: int = 5
    retries: int = 3


class ToolpackContainerRuntime(BaseModel):
    """Container runtime configuration."""

    image: str
    base_image: str = DEFAULT_BASE_IMAGE
    dockerfile: str = "Dockerfile"
    entrypoint: str = "entrypoint.sh"
    run: str = "toolwright.run"
    requirements: str = "requirements.lock"
    env_allowlist: list[str] = Field(default_factory=_default_env_allowlist)
    healthcheck: ToolpackRuntimeHealthcheck = Field(
        default_factory=ToolpackRuntimeHealthcheck
    )


class ToolpackRuntime(BaseModel):
    """Runtime metadata for executing a toolpack."""

    mode: str = "local"
    container: ToolpackContainerRuntime | None = None


class ToolpackOrigin(BaseModel):
    """Origin metadata for a minted toolpack."""

    start_url: str
    name: str | None = None


class ToolpackPaths(BaseModel):
    """Relative artifact and lockfile paths inside a toolpack directory."""

    tools: str
    toolsets: str
    policy: str
    baseline: str
    contracts: str | None = None
    contract_yaml: str | None = None
    contract_json: str | None = None
    evidence_summary: str | None = None
    evidence_summary_sha256: str | None = None
    lockfiles: dict[str, str] = Field(default_factory=dict)


class Toolpack(BaseModel):
    """Toolpack metadata payload."""

    version: str = "1.0.0"
    schema_version: str = CURRENT_SCHEMA_VERSION
    toolpack_id: str
    created_at: datetime
    capture_id: str
    artifact_id: str
    scope: str
    allowed_hosts: list[str] = Field(default_factory=list)
    display_name: str | None = None
    origin: ToolpackOrigin
    paths: ToolpackPaths
    runtime: ToolpackRuntime | None = None


@dataclass(frozen=True)
class ResolvedToolpackPaths:
    """Resolved absolute paths for a toolpack and its managed artifacts."""

    toolpack_file: Path
    tools_path: Path
    toolsets_path: Path
    policy_path: Path
    baseline_path: Path
    contracts_path: Path | None
    contract_yaml_path: Path | None
    contract_json_path: Path | None
    evidence_summary_path: Path | None
    evidence_summary_sha256_path: Path | None
    pending_lockfile_path: Path | None
    approved_lockfile_path: Path | None


def load_toolpack(toolpack_path: str | Path) -> Toolpack:
    """Load and validate a toolpack YAML file."""
    resolved = Path(toolpack_path)
    with open(resolved) as f:
        payload = yaml.safe_load(f) or {}
    resolve_schema_version(payload, artifact="toolpack", allow_legacy=False)
    return Toolpack(**payload)


def write_toolpack(toolpack: Toolpack, toolpack_path: str | Path) -> None:
    """Write a toolpack YAML payload."""
    resolved = Path(toolpack_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = toolpack.model_dump(mode="json")
    with open(resolved, "w") as f:
        yaml.safe_dump(payload, f, sort_keys=False)


def resolve_toolpack_paths(
    *,
    toolpack: Toolpack,
    toolpack_path: str | Path,
) -> ResolvedToolpackPaths:
    """Resolve toolpack relative paths to absolute filesystem paths."""
    toolpack_file = Path(toolpack_path).resolve()
    root = toolpack_file.parent

    def _resolve(value: str | None) -> Path | None:
        if not value:
            return None
        return (root / value).resolve()

    pending_lockfile = _resolve(toolpack.paths.lockfiles.get("pending"))
    approved_lockfile = _resolve(toolpack.paths.lockfiles.get("approved"))

    return ResolvedToolpackPaths(
        toolpack_file=toolpack_file,
        tools_path=(root / toolpack.paths.tools).resolve(),
        toolsets_path=(root / toolpack.paths.toolsets).resolve(),
        policy_path=(root / toolpack.paths.policy).resolve(),
        baseline_path=(root / toolpack.paths.baseline).resolve(),
        contracts_path=_resolve(toolpack.paths.contracts),
        contract_yaml_path=_resolve(toolpack.paths.contract_yaml),
        contract_json_path=_resolve(toolpack.paths.contract_json),
        evidence_summary_path=_resolve(toolpack.paths.evidence_summary),
        evidence_summary_sha256_path=_resolve(toolpack.paths.evidence_summary_sha256),
        pending_lockfile_path=pending_lockfile,
        approved_lockfile_path=approved_lockfile,
    )
