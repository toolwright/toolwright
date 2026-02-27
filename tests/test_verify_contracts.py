"""Tests for contract loading and schema validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from toolwright.core.verify.contracts import load_contracts, validate_contract_file
from toolwright.models.verify import AssertionOp, VerifyStatus

# --- load_contracts ---

def test_load_contracts_from_json(tmp_path: Path) -> None:
    path = tmp_path / "contracts.json"
    path.write_text(json.dumps({
        "version": "1.0",
        "schema_version": "1.0",
        "contracts": [
            {
                "contract_id": "vc_1",
                "targets": ["get_users"],
                "assertions": [
                    {"field_path": "status", "op": "equals", "value": 200},
                ],
            }
        ],
    }))
    contracts = load_contracts(path)
    assert len(contracts) == 1
    assert contracts[0].contract_id == "vc_1"
    assert contracts[0].targets == ["get_users"]
    assert len(contracts[0].assertions) == 1
    assert contracts[0].assertions[0].op == AssertionOp.EQUALS


def test_load_contracts_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "contracts.yaml"
    path.write_text(yaml.dump({
        "version": "1.0",
        "schema_version": "1.0",
        "contracts": [
            {
                "contract_id": "vc_2",
                "targets": ["create_user"],
                "risk_tier": "high",
                "assertions": [
                    {"field_path": "users", "op": "exists"},
                ],
            }
        ],
    }))
    contracts = load_contracts(path)
    assert len(contracts) == 1
    assert contracts[0].risk_tier == "high"


def test_load_contracts_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_contracts(tmp_path / "nope.json")


def test_load_contracts_missing_version(tmp_path: Path) -> None:
    path = tmp_path / "contracts.json"
    path.write_text(json.dumps({"contracts": []}))
    with pytest.raises(ValueError, match="schema_version.*version"):
        load_contracts(path)


def test_load_contracts_invalid_format(tmp_path: Path) -> None:
    path = tmp_path / "contracts.json"
    path.write_text(json.dumps([1, 2, 3]))
    with pytest.raises(ValueError, match="mapping"):
        load_contracts(path)


def test_load_contracts_empty_list(tmp_path: Path) -> None:
    path = tmp_path / "contracts.json"
    path.write_text(json.dumps({
        "version": "1.0",
        "schema_version": "1.0",
        "contracts": [],
    }))
    contracts = load_contracts(path)
    assert contracts == []


def test_load_contracts_multiple(tmp_path: Path) -> None:
    path = tmp_path / "contracts.json"
    path.write_text(json.dumps({
        "version": "1.0",
        "schema_version": "1.0",
        "contracts": [
            {"contract_id": "vc_a", "assertions": [{"field_path": "a"}]},
            {"contract_id": "vc_b", "assertions": [{"field_path": "b"}]},
        ],
    }))
    contracts = load_contracts(path)
    assert len(contracts) == 2


def test_load_contracts_unknown_op_defaults_to_exists(tmp_path: Path) -> None:
    path = tmp_path / "contracts.json"
    path.write_text(json.dumps({
        "version": "1.0",
        "schema_version": "1.0",
        "contracts": [
            {
                "contract_id": "vc_x",
                "assertions": [{"field_path": "x", "op": "bogus_op"}],
            }
        ],
    }))
    contracts = load_contracts(path)
    assert contracts[0].assertions[0].op == AssertionOp.EXISTS


# --- validate_contract_file ---

def test_validate_valid_file(tmp_path: Path) -> None:
    path = tmp_path / "contracts.yaml"
    path.write_text(yaml.dump({
        "version": "1.0",
        "schema_version": "1.0",
        "contracts": [],
    }))
    result = validate_contract_file(path)
    assert result.status == VerifyStatus.PASS


def test_validate_missing_file(tmp_path: Path) -> None:
    result = validate_contract_file(tmp_path / "nope.yaml")
    assert result.status == VerifyStatus.FAIL


def test_validate_file_no_contracts_key(tmp_path: Path) -> None:
    path = tmp_path / "contracts.json"
    path.write_text(json.dumps({"version": "1.0", "schema_version": "1.0"}))
    result = validate_contract_file(path)
    assert result.status == VerifyStatus.UNKNOWN


def test_validate_file_no_version(tmp_path: Path) -> None:
    path = tmp_path / "contracts.json"
    path.write_text(json.dumps({"contracts": []}))
    result = validate_contract_file(path)
    assert result.status == VerifyStatus.FAIL
