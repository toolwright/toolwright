"""Artifact and schema migration command implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import yaml


def run_migrate(*, toolpack_path: str, apply_changes: bool, verbose: bool) -> None:
    """Migrate legacy toolpack artifacts to current contract layout."""
    path = Path(toolpack_path)
    if not path.exists():
        raise click.ClickException(f"Toolpack not found: {toolpack_path}")

    payload_raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload_raw, dict):
        raise click.ClickException("toolpack payload must be a mapping")

    payload: dict[str, Any] = dict(payload_raw)
    changes: list[str] = []

    if not payload.get("version"):
        payload["version"] = "1.0.0"
        changes.append("set toolpack version=1.0.0")
    if not payload.get("schema_version"):
        payload["schema_version"] = "1.0"
        changes.append("set toolpack schema_version=1.0")

    paths = payload.get("paths")
    if not isinstance(paths, dict):
        raise click.ClickException("toolpack paths must be a mapping")

    contracts_rel = paths.get("contracts")
    contracts_path = path.parent / "artifact" / "contracts.yaml"

    if not isinstance(contracts_rel, str) or not contracts_rel.strip():
        paths["contracts"] = "artifact/contracts.yaml"
        changes.append("set paths.contracts=artifact/contracts.yaml")

    if not contracts_path.exists():
        legacy_contract_path = None
        legacy_rel = paths.get("contract_yaml")
        if isinstance(legacy_rel, str) and legacy_rel.strip():
            candidate = path.parent / legacy_rel
            if candidate.exists():
                legacy_contract_path = candidate

        contracts_payload = _contracts_payload_from_legacy(legacy_contract_path)
        changes.append("create artifact/contracts.yaml")
        if apply_changes:
            contracts_path.parent.mkdir(parents=True, exist_ok=True)
            contracts_path.write_text(
                yaml.safe_dump(contracts_payload, sort_keys=False),
                encoding="utf-8",
            )

    if not changes:
        click.echo("No migrations required.")
        return

    if not apply_changes:
        click.echo("Dry run: proposed migrations")
        for change in changes:
            click.echo(f"  - {change}")
        return

    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    click.echo("Migration complete")
    for change in changes:
        click.echo(f"  - {change}")
    if verbose:
        click.echo(f"Migrated toolpack: {path}")


def _contracts_payload_from_legacy(legacy_contract_path: Path | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "kind": "contracts",
        "contracts": [],
    }
    if legacy_contract_path and legacy_contract_path.exists():
        payload["legacy_contract_path"] = str(legacy_contract_path.name)
    return payload
