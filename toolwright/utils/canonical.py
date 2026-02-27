"""Canonical serialization helpers for deterministic governance artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, cast


def canonicalize(value: Any) -> Any:
    """Return a recursively canonicalized value with deterministic ordering."""
    if isinstance(value, Mapping):
        return {str(k): canonicalize(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, list):
        return [canonicalize(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Serialize a value into canonical JSON."""
    return json.dumps(canonicalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_digest(value: Any) -> str:
    """Compute sha256 digest from canonical serialization."""
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _canonicalize_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        canonicalize(action)
        for action in sorted(
            actions,
            key=lambda action: (
                str(action.get("tool_id", "")),
                str(action.get("host", "")),
                str(action.get("method", "")).upper(),
                str(action.get("path", "")),
                str(action.get("signature_id", "")),
                str(action.get("name", "")),
            ),
        )
    ]


def canonicalize_tools_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize tools manifest for stable digesting."""
    normalized = dict(payload)
    normalized["actions"] = _canonicalize_actions(list(payload.get("actions", [])))
    return cast(dict[str, Any], canonicalize(normalized))


def canonicalize_toolsets(payload: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize toolsets artifact for stable digesting."""
    normalized = dict(payload)
    toolsets: dict[str, Any] = payload.get("toolsets", {})
    normalized["toolsets"] = {
        name: {
            **{k: v for k, v in data.items() if k != "actions"},
            "actions": sorted(str(action) for action in data.get("actions", [])),
        }
        for name, data in sorted(toolsets.items(), key=lambda item: item[0])
    }
    return cast(dict[str, Any], canonicalize(normalized))


def canonicalize_policy(payload: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize policy artifact for stable digesting."""
    normalized = dict(payload)
    rules = list(payload.get("rules", []))
    normalized["rules"] = [
        canonicalize(rule)
        for rule in sorted(
            rules,
            key=lambda rule: (
                str(rule.get("id", "")),
                str(rule.get("type", "")),
                int(rule.get("priority", 0)),
            ),
        )
    ]
    overrides = list(payload.get("state_changing_overrides", []))
    normalized["state_changing_overrides"] = [
        canonicalize(override)
        for override in sorted(
            overrides,
            key=lambda override: (
                str(override.get("tool_id", "")),
                str(override.get("method", "")).upper(),
                str(override.get("host", "")),
                str(override.get("path", "")),
            ),
        )
    ]
    return cast(dict[str, Any], canonicalize(normalized))


def canonical_request_digest(
    *,
    tool_id: str,
    method: str,
    path: str,
    host: str,
    params: dict[str, Any],
) -> str:
    """Compute deterministic digest for a decision request."""
    payload = {
        "tool_id": tool_id,
        "method": method.upper(),
        "path": path,
        "host": host.lower(),
        "params": canonicalize(params),
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()
