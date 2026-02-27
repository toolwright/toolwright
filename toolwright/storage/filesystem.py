"""Filesystem storage for captures, artifacts, and reports."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from toolwright.models.capture import CaptureSession


class Storage:
    """Local filesystem storage for Toolwright data."""

    def __init__(self, base_path: Path | str = ".toolwright") -> None:
        """Initialize storage with base path.

        Args:
            base_path: Base directory for all storage
        """
        self.base_path = Path(base_path)
        self._ensure_structure()

    def _ensure_structure(self) -> None:
        """Ensure directory structure exists."""
        (self.base_path / "captures").mkdir(parents=True, exist_ok=True)
        (self.base_path / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.base_path / "toolpacks").mkdir(parents=True, exist_ok=True)
        (self.base_path / "baselines").mkdir(parents=True, exist_ok=True)
        (self.base_path / "reports").mkdir(parents=True, exist_ok=True)
        (self.base_path / "evidence").mkdir(parents=True, exist_ok=True)
        (self.base_path / "scopes").mkdir(parents=True, exist_ok=True)
        (self.base_path / "state").mkdir(parents=True, exist_ok=True)

    def save_capture(self, session: CaptureSession) -> Path:
        """Save a capture session to disk.

        Args:
            session: CaptureSession to save

        Returns:
            Path to the saved capture directory
        """
        capture_dir = self.base_path / "captures" / session.id
        capture_dir.mkdir(parents=True, exist_ok=True)

        # Save session metadata
        session_file = capture_dir / "session.json"
        session_data = session.model_dump(mode="json", exclude={"exchanges"})
        self._write_json(session_file, session_data)

        # Save exchanges
        exchanges_file = capture_dir / "exchanges.json"
        exchanges_data = [e.model_dump(mode="json") for e in session.exchanges]
        self._write_json(exchanges_file, exchanges_data)

        return capture_dir

    def load_capture(self, capture_id: str) -> CaptureSession | None:
        """Load a capture session from disk.

        Args:
            capture_id: ID of the capture to load

        Returns:
            CaptureSession if found, None otherwise
        """
        capture_dir = self.base_path / "captures" / capture_id

        if not capture_dir.exists():
            # Try as a direct path
            capture_dir = Path(capture_id)
            if not capture_dir.exists():
                return None

        session_file = capture_dir / "session.json"
        exchanges_file = capture_dir / "exchanges.json"

        if not session_file.exists():
            return None

        session_data = self._read_json(session_file)
        if not session_data:
            return None

        exchanges_data = self._read_json(exchanges_file) or []

        return CaptureSession(
            **session_data,
            exchanges=exchanges_data,
        )

    def list_captures(self) -> list[dict[str, Any]]:
        """List all captures with metadata.

        Returns:
            List of capture metadata dicts
        """
        captures_dir = self.base_path / "captures"
        captures = []

        for capture_dir in captures_dir.iterdir():
            if capture_dir.is_dir():
                session_file = capture_dir / "session.json"
                if session_file.exists():
                    data = self._read_json(session_file)
                    if data:
                        captures.append(data)

        # Sort by created_at descending
        captures.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return captures

    def save_artifact(
        self,
        artifact_id: str,
        artifact_type: str,
        data: dict[str, Any],
        format: str = "json",
    ) -> Path:
        """Save an artifact to disk.

        Args:
            artifact_id: ID for the artifact set
            artifact_type: Type of artifact (contract, tools, policy, baseline)
            data: Data to save
            format: Output format (json or yaml)

        Returns:
            Path to the saved artifact
        """
        artifact_dir = self.base_path / "artifacts" / artifact_id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        if format == "yaml":
            import yaml

            artifact_file = artifact_dir / f"{artifact_type}.yaml"
            with open(artifact_file, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        else:
            artifact_file = artifact_dir / f"{artifact_type}.json"
            self._write_json(artifact_file, data)

        return artifact_file

    def save_report(
        self,
        report_id: str,
        report_type: str,
        data: dict[str, Any],
        format: str = "json",
    ) -> Path:
        """Save a report to disk.

        Args:
            report_id: ID for the report
            report_type: Type of report (drift, etc.)
            data: Data to save
            format: Output format (json, markdown)

        Returns:
            Path to the saved report
        """
        reports_dir = self.base_path / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        if format == "markdown":
            report_file = reports_dir / f"{report_type}_{report_id}.md"
            with open(report_file, "w", encoding="utf-8") as f:
                f.write(self._format_as_markdown(data))
        else:
            report_file = reports_dir / f"{report_type}_{report_id}.json"
            self._write_json(report_file, data)

        return report_file

    def append_audit_log(self, event: dict[str, Any]) -> None:
        """Append an event to the audit log.

        Args:
            event: Audit event to log
        """
        audit_file = self.base_path / "audit.log.jsonl"

        # Add timestamp if not present
        if "timestamp" not in event:
            event["timestamp"] = datetime.utcnow().isoformat() + "Z"

        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def _write_json(self, path: Path, data: Any) -> None:
        """Write JSON data to file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def _read_json(self, path: Path) -> Any:
        """Read JSON data from file."""
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return None

    def _format_as_markdown(self, data: dict[str, Any]) -> str:
        """Format a report as markdown."""
        lines = ["# Report\n"]

        for key, value in data.items():
            if isinstance(value, dict):
                lines.append(f"\n## {key}\n")
                lines.append("```json")
                lines.append(json.dumps(value, indent=2))
                lines.append("```\n")
            elif isinstance(value, list):
                lines.append(f"\n## {key}\n")
                for item in value:
                    if isinstance(item, dict):
                        lines.append(f"- {json.dumps(item)}")
                    else:
                        lines.append(f"- {item}")
                lines.append("")
            else:
                lines.append(f"**{key}:** {value}\n")

        return "\n".join(lines)
