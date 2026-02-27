"""Bundle command implementation."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from typing import Any

import click

from toolwright.core.plan.engine import build_plan, render_plan_json, render_plan_md
from toolwright.core.toolpack import load_toolpack
from toolwright.utils.config import build_mcp_config_payload, render_config_payload

FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o644
EXEC_MODE = 0o755


def run_bundle(
    *,
    toolpack_path: str,
    output_path: str,
    verbose: bool,
) -> None:
    """Create a deterministic bundle for sharing."""
    try:
        toolpack = load_toolpack(Path(toolpack_path))
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    try:
        report = build_plan(toolpack_path=Path(toolpack_path), baseline_path=None)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    plan_json = render_plan_json(report)
    plan_md = render_plan_md(report)
    config_payload = build_mcp_config_payload(
        toolpack_path=Path("toolpack.yaml"),
        server_name=toolpack.toolpack_id,
        portable=True,
    )
    config_json = render_config_payload(config_payload, "json")
    run_md = _render_run_md(toolpack.toolpack_id)

    toolpack_root = Path(toolpack_path).resolve().parent
    bundle_path = Path(output_path)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)

    files = _collect_toolpack_files(toolpack_root)
    manifest = _bundle_manifest(files)

    with zipfile.ZipFile(
        bundle_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as zf:
        for rel_path in sorted(files):
            abs_path = toolpack_root / rel_path
            mode = EXEC_MODE if rel_path in {"entrypoint.sh", "toolwright.run"} else FILE_MODE
            _write_zip_file(zf, rel_path, abs_path.read_bytes(), mode)

        _write_zip_file(zf, "plan.json", plan_json.encode("utf-8"), FILE_MODE)
        _write_zip_file(zf, "plan.md", plan_md.encode("utf-8"), FILE_MODE)
        _write_zip_file(zf, "client-config.json", config_json.encode("utf-8"), FILE_MODE)
        _write_zip_file(zf, "RUN.md", run_md.encode("utf-8"), FILE_MODE)
        _write_zip_file(
            zf,
            "BUNDLE_MANIFEST.json",
            _json_dump(manifest).encode("utf-8"),
            FILE_MODE,
        )

    if verbose:
        click.echo(f"Bundle created: {bundle_path}")


def _collect_toolpack_files(root: Path) -> list[str]:
    """Collect portable bundle files, excluding sensitive runtime state."""
    allowed_roots = {
        "artifact",
        "lockfile",
        "toolpack.yaml",
        "Dockerfile",
        "entrypoint.sh",
        "toolwright.run",
        "requirements.lock",
    }
    sensitive_tokens = {
        "storage_state",
        "confirmations.db",
        "approval_signing.key",
        "auth",
        ".toolwright",
        "state",
    }
    files: list[str] = []
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(root)
        rel_text = rel.as_posix()
        if any(token in rel_text for token in sensitive_tokens):
            continue
        head = rel.parts[0] if rel.parts else rel_text
        if head not in allowed_roots:
            continue
        if head == "lockfile" and rel.name not in {
            "toolwright.lock.yaml",
            "toolwright.lock.pending.yaml",
            "toolwright.lock.approved.yaml",
        }:
            continue
        files.append(rel_text)
    return files


def _write_zip_file(zf: zipfile.ZipFile, arcname: str, data: bytes, mode: int) -> None:
    info = zipfile.ZipInfo(arcname, date_time=FIXED_TIMESTAMP)
    info.external_attr = (mode & 0xFFFF) << 16
    zf.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _render_run_md(_toolpack_id: str) -> str:
    return (
        "# Toolwright Bundle\n\n"
        "Run this toolpack:\n\n"
        "  toolwright run --toolpack ./toolpack.yaml\n"
    )


def _bundle_manifest(files: list[str]) -> dict[str, Any]:
    return {
        "format": "toolwright.bundle.v1",
        "portable": True,
        "exports": sorted(files),
        "excludes": [
            "raw capture traffic",
            "full request/response headers",
            "auth storage state",
            "confirmation databases",
            "local signing keys",
        ],
    }


def _json_dump(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True)
