"""Create draft toolpacks from discovered CaptureSession."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml

from toolwright.models.capture import CaptureSession, HTTPMethod


class DraftToolpackCreator:
    """Creates draft toolpacks from discovered CaptureSession."""

    def __init__(self, drafts_root: Path) -> None:
        self._drafts_root = drafts_root

    def create(self, session: CaptureSession, label: str = "") -> str:
        """Create a draft toolpack from a CaptureSession. Returns draft ID."""
        draft_id = self._generate_draft_id()
        draft_dir = self._drafts_root / draft_id
        draft_dir.mkdir(parents=True, exist_ok=True)

        host = session.allowed_hosts[0] if session.allowed_hosts else "unknown"
        created_at = datetime.now(UTC).isoformat()

        actions = self._build_actions(session)

        # Write tools.json
        tools_data = {"schema_version": "1.0", "actions": actions}
        (draft_dir / "tools.json").write_text(json.dumps(tools_data, indent=2))

        # Write toolpack.yaml
        toolpack_data = {
            "draft": True,
            "draft_id": draft_id,
            "label": label,
            "host": host,
            "created_at": created_at,
            "paths": {"tools": "tools.json"},
        }
        (draft_dir / "toolpack.yaml").write_text(yaml.dump(toolpack_data, default_flow_style=False))

        # Write manifest.json
        manifest = {
            "draft_id": draft_id,
            "label": label,
            "host": host,
            "created_at": created_at,
            "session_id": session.id,
            "action_count": len(actions),
        }
        (draft_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

        return draft_id

    def list_drafts(self) -> list[dict]:
        """List all draft toolpacks with metadata."""
        if not self._drafts_root.is_dir():
            return []

        drafts = []
        for entry in self._drafts_root.iterdir():
            if not entry.is_dir():
                continue
            manifest_path = entry / "manifest.json"
            if not manifest_path.is_file():
                continue
            manifest = json.loads(manifest_path.read_text())
            drafts.append(manifest)

        drafts.sort(key=lambda d: d.get("created_at", ""), reverse=True)
        return drafts

    def get_draft_path(self, draft_id: str) -> Path | None:
        """Get the path to a draft toolpack directory."""
        candidate = self._drafts_root / draft_id
        if candidate.is_dir():
            return candidate
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_draft_id() -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        random_part = uuid.uuid4().hex[:8]
        return f"draft_{timestamp}_{random_part}"

    @staticmethod
    def _build_actions(session: CaptureSession) -> list[dict]:
        seen: set[tuple[str, str]] = set()
        actions: list[dict] = []

        for ex in session.exchanges:
            key = (ex.method.value, ex.path)
            if key in seen:
                continue
            seen.add(key)

            # Generate name from method + last path segment
            segment = ex.path.rstrip("/").rsplit("/", 1)[-1] or "root"
            name = f"{ex.method.value.lower()}_{segment}"

            risk_tier = _risk_tier_for_method(ex.method)

            actions.append({
                "name": name,
                "method": ex.method.value,
                "path": ex.path,
                "host": ex.host,
                "risk_tier": risk_tier,
            })

        return actions


def _risk_tier_for_method(method: HTTPMethod) -> str:
    if method == HTTPMethod.GET:
        return "low"
    if method == HTTPMethod.DELETE:
        return "high"
    return "medium"
