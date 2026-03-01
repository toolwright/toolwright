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
    groups: str | None = None
    lockfiles: dict[str, str] = Field(default_factory=dict)


class ToolpackAuthRequirement(BaseModel):
    """Auth requirement detected during capture."""

    host: str
    scheme: str  # "bearer", "api_key", "cookie", "none"
    location: str  # "header", "query", "cookie"
    header_name: str | None = None  # "Authorization", "X-API-Key", etc.
    env_var_name: str  # pre-computed: "TOOLWRIGHT_AUTH_API_STRIPE_COM"


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
    auth_requirements: list[ToolpackAuthRequirement] | None = None
    extra_headers: dict[str, str] | None = None


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
    groups_path: Path | None
    pending_lockfile_path: Path | None
    approved_lockfile_path: Path | None


def load_toolpack(toolpack_path: str | Path) -> Toolpack:
    """Load and validate a toolpack YAML file."""
    from pydantic import ValidationError

    resolved = Path(toolpack_path)
    with open(resolved) as f:
        payload = yaml.safe_load(f) or {}
    resolve_schema_version(payload, artifact="toolpack", allow_legacy=False)
    try:
        return Toolpack(**payload)
    except ValidationError as e:
        missing = [err["loc"][-1] for err in e.errors() if err["type"] == "missing"]
        if missing:
            msg = f"Invalid toolpack {resolved}: missing required fields: {', '.join(str(f) for f in missing)}"
        else:
            msg = f"Invalid toolpack {resolved}: {len(e.errors())} validation error(s)"
        raise ValueError(msg) from e


def write_toolpack(toolpack: Toolpack, toolpack_path: str | Path) -> None:
    """Write a toolpack YAML payload."""
    resolved = Path(toolpack_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = toolpack.model_dump(mode="json")
    with open(resolved, "w") as f:
        yaml.safe_dump(payload, f, sort_keys=False)


def build_auth_requirements(
    *,
    hosts: list[str],
    auth_type: str,
) -> list[ToolpackAuthRequirement]:
    """Build ToolpackAuthRequirement list from detected auth type and hosts.

    Pre-computes env_var_name so all consumers (auth check, mint output,
    troubleshooting docs) show the exact same string.
    """
    import re

    scheme_to_header: dict[str, str | None] = {
        "bearer": "Authorization",
        "api_key": "X-API-Key",
        "cookie": None,
        "none": None,
        "unknown": None,
        "redirect": None,
    }

    scheme_to_location: dict[str, str] = {
        "bearer": "header",
        "api_key": "header",
        "cookie": "cookie",
        "none": "header",
        "unknown": "header",
        "redirect": "header",
    }

    reqs: list[ToolpackAuthRequirement] = []
    for host in hosts:
        normalized = re.sub(r"[^A-Za-z0-9]", "_", host).upper()
        env_var = f"TOOLWRIGHT_AUTH_{normalized}"
        reqs.append(
            ToolpackAuthRequirement(
                host=host,
                scheme=auth_type,
                location=scheme_to_location.get(auth_type, "header"),
                header_name=scheme_to_header.get(auth_type),
                env_var_name=env_var,
            )
        )
    return reqs


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
        groups_path=_resolve(toolpack.paths.groups),
        pending_lockfile_path=pending_lockfile,
        approved_lockfile_path=approved_lockfile,
    )
