"""Tests for circuit breaker state recovery from corrupt files."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from toolwright.core.kill.breaker import CircuitBreakerRegistry


def test_corrupt_state_logs_error(tmp_path: Path, caplog) -> None:
    """Corrupt state file logs an error and starts with empty state."""
    state_path = tmp_path / "breakers.json"
    state_path.write_text("NOT JSON AT ALL")

    with caplog.at_level(logging.ERROR):
        reg = CircuitBreakerRegistry(state_path=state_path)

    assert "Corrupt circuit breaker state" in caplog.text
    # Should start with empty state
    assert reg.quarantine_report() == []


def test_save_creates_backup(tmp_path: Path) -> None:
    """Every save creates a .bak copy of the state file."""
    state_path = tmp_path / "breakers.json"
    reg = CircuitBreakerRegistry(state_path=state_path)
    reg.kill_tool("test_tool", reason="testing")

    bak_path = state_path.with_suffix(".json.bak")
    assert bak_path.exists(), f"Expected backup file {bak_path} to exist"
    bak_data = json.loads(bak_path.read_text())
    assert "test_tool" in bak_data
