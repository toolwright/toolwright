"""Scope management command implementations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import yaml


def run_scopes_merge(
    *,
    suggested_path: str,
    authoritative_path: str,
    output_path: str | None,
    apply: bool,
    verbose: bool,
) -> None:
    """Merge generated scope suggestions into a proposal without silent overwrite."""
    suggested = _load_yaml(Path(suggested_path))
    authoritative_file = Path(authoritative_path)
    authoritative = _load_yaml(authoritative_file) if authoritative_file.exists() else {"version": 1, "scopes": {}}

    suggested_scopes = _extract_suggested_scopes(suggested)
    authoritative_scopes = authoritative.get("scopes", {})

    merged: dict[str, Any] = {
        "version": authoritative.get("version", suggested.get("version", 1)),
        "scopes": dict(authoritative_scopes),
    }

    added: list[str] = []
    existing: list[str] = []
    for scope_name in sorted(suggested_scopes):
        if scope_name in merged["scopes"]:
            existing.append(scope_name)
            continue
        merged["scopes"][scope_name] = suggested_scopes[scope_name]
        added.append(scope_name)

    proposal_path = Path(output_path) if output_path else authoritative_file.with_name("scopes.merge.proposed.yaml")
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(yaml.safe_dump(merged, sort_keys=False), encoding="utf-8")

    click.echo(f"Scopes merge proposal: {proposal_path}")
    click.echo(f"  Added scopes: {len(added)}")
    click.echo(f"  Existing preserved: {len(existing)}")
    if verbose and added:
        click.echo(f"  Added: {', '.join(added)}")
    if apply:
        authoritative_file.parent.mkdir(parents=True, exist_ok=True)
        authoritative_file.write_text(proposal_path.read_text(encoding="utf-8"), encoding="utf-8")
        click.echo(f"Applied merged scopes to: {authoritative_file}")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise click.ClickException(f"Scope file not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise click.ClickException(f"Expected YAML mapping at: {path}")
    return payload


def _extract_suggested_scopes(suggested_payload: dict[str, Any]) -> dict[str, Any]:
    """Return normalized scope suggestions from either scopes-map or draft-list format."""
    scopes = suggested_payload.get("scopes")
    if isinstance(scopes, dict):
        return scopes

    drafts = suggested_payload.get("drafts")
    if not isinstance(drafts, list):
        return {}

    risk_rank = {"safe": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    normalized: dict[str, dict[str, Any]] = {}

    for draft in drafts:
        if not isinstance(draft, dict):
            continue
        scope_name = str(draft.get("scope_name", "")).strip()
        if not scope_name:
            continue

        risk_tier = str(draft.get("risk_tier", "low")).strip().lower()
        if risk_tier not in risk_rank:
            risk_tier = "low"

        confidence_raw = draft.get("confidence", 0.0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0

        signals_raw = draft.get("signals", [])
        signals: list[str] = []
        if isinstance(signals_raw, list):
            signals = [str(signal) for signal in signals_raw if signal is not None]

        entry = normalized.get(scope_name)
        if entry is None:
            normalized[scope_name] = {
                "intent": scope_name,
                "risk_tier": risk_tier,
                "confidence": round(confidence, 3),
                "review_required": bool(draft.get("review_required", False)),
                "signals": signals,
                "endpoint_ids": [str(draft.get("endpoint_id", ""))] if draft.get("endpoint_id") else [],
            }
            continue

        if risk_rank[risk_tier] > risk_rank[str(entry.get("risk_tier", "low"))]:
            entry["risk_tier"] = risk_tier
        entry["confidence"] = round(min(float(entry.get("confidence", 1.0)), confidence), 3)
        entry["review_required"] = bool(entry.get("review_required", False)) or bool(
            draft.get("review_required", False)
        )
        existing_signals = list(entry.get("signals", []))
        entry["signals"] = sorted(set(existing_signals + signals))
        endpoint_ids = list(entry.get("endpoint_ids", []))
        endpoint_id = draft.get("endpoint_id")
        if endpoint_id:
            endpoint_ids.append(str(endpoint_id))
            entry["endpoint_ids"] = sorted(set(endpoint_ids))

    return normalized
