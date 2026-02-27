"""Unit tests for the flagship smoke suite script."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_script_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "flagship_smoke_suite.py"
    assert script_path.exists(), f"missing script under repo root: {script_path}"
    spec = importlib.util.spec_from_file_location("flagship_smoke_suite_script", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_scenarios_splits_and_trims() -> None:
    mod = _load_script_module()
    scenarios = mod._parse_scenarios(" basic_products , auth_refresh ")
    assert scenarios == ["basic_products", "auth_refresh"]


def test_parse_scenarios_rejects_empty() -> None:
    mod = _load_script_module()
    with pytest.raises(ValueError, match="at least one scenario"):
        mod._parse_scenarios(" , ")


def test_read_auth_refresh_ok_handles_missing_file(tmp_path: Path) -> None:
    mod = _load_script_module()
    ok, details = mod._read_auth_refresh_ok(tmp_path)
    assert ok is False
    assert "missing auth_refresh_checks.json" in details


def test_read_auth_refresh_ok_accepts_valid_payload(tmp_path: Path) -> None:
    mod = _load_script_module()
    checks_path = tmp_path / "auth_refresh_checks.json"
    checks_path.write_text(
        json.dumps(
            {
                "ok": True,
                "oauth_token_request_count": 2,
                "orders_request_count": 2,
            }
        ),
        encoding="utf-8",
    )
    ok, details = mod._read_auth_refresh_ok(tmp_path)
    assert ok is True
    assert "oauth_calls=2" in details
    assert "orders_calls=2" in details
