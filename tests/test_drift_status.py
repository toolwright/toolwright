"""Tests for drift status subcommand — shows recent drift events."""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner


def _write_events(events_path: Path, events: list[dict]) -> None:
    """Write events to a JSONL file."""
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with open(events_path, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


class TestDriftStatusCommand:
    def test_shows_recent_events(self, tmp_path):
        """drift status shows recent drift events from JSONL log."""
        from toolwright.cli.drift import drift_status

        events_path = tmp_path / "drift_events.jsonl"
        _write_events(events_path, [
            {
                "timestamp": "2026-03-01T12:00:00Z",
                "tool_name": "list_products",
                "severity": "safe",
                "changes": [
                    {
                        "change_type": "field_added",
                        "severity": "safe",
                        "path": ".data[].new_field",
                        "description": "New field: .data[].new_field",
                    }
                ],
            },
            {
                "timestamp": "2026-03-01T12:05:00Z",
                "tool_name": "get_order",
                "severity": "manual",
                "changes": [
                    {
                        "change_type": "type_changed_breaking",
                        "severity": "manual",
                        "path": ".id",
                        "description": "Type changed: integer -> string",
                    }
                ],
            },
        ])

        runner = CliRunner()
        result = runner.invoke(drift_status, ["--events-path", str(events_path)])

        assert result.exit_code == 0
        assert "list_products" in result.output
        assert "get_order" in result.output
        assert "safe" in result.output.lower()
        assert "manual" in result.output.lower()

    def test_empty_events_file(self, tmp_path):
        """drift status with no events -> clean message."""
        from toolwright.cli.drift import drift_status

        events_path = tmp_path / "drift_events.jsonl"

        runner = CliRunner()
        result = runner.invoke(drift_status, ["--events-path", str(events_path)])

        assert result.exit_code == 0
        assert "no drift" in result.output.lower() or "no events" in result.output.lower()
