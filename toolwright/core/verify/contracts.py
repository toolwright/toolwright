"""Contract loading, schema validation, and version checking."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from toolwright.models.verify import (
    Assertion,
    AssertionOp,
    ContractResult,
    FlakePolicy,
    VerificationContract,
    VerifyStatus,
)


def load_contracts(contract_path: Path) -> list[VerificationContract]:
    """Load verification contracts from a YAML or JSON file.

    Returns a list of VerificationContract objects.
    Raises ValueError if the file format is invalid.
    """
    if not contract_path.exists():
        raise FileNotFoundError(f"Contract file not found: {contract_path}")

    raw = contract_path.read_text(encoding="utf-8")
    if contract_path.suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(raw) or {}
    else:
        payload = json.loads(raw)

    if not isinstance(payload, dict):
        raise ValueError("Contract file must be a mapping")

    _validate_contract_schema(payload)

    raw_contracts = payload.get("contracts", [])
    if not isinstance(raw_contracts, list):
        raise ValueError("'contracts' must be a list")

    results: list[VerificationContract] = []
    for idx, entry in enumerate(raw_contracts):
        if not isinstance(entry, dict):
            raise ValueError(f"Contract at index {idx} must be a mapping")
        results.append(_parse_contract(entry, idx))

    return results


def _validate_contract_schema(payload: dict[str, Any]) -> None:
    """Validate top-level contract file schema."""
    if "schema_version" not in payload and "version" not in payload:
        raise ValueError("Contract file must include 'schema_version' or 'version'")


def _parse_contract(entry: dict[str, Any], idx: int) -> VerificationContract:
    """Parse a single contract entry into a VerificationContract."""
    contract_id = str(entry.get("contract_id", f"vc_inline_{idx}"))
    targets = entry.get("targets", [])
    if not isinstance(targets, list):
        targets = [str(targets)]

    raw_assertions = entry.get("assertions", [])
    assertions: list[Assertion] = []
    for aidx, raw_a in enumerate(raw_assertions):
        if not isinstance(raw_a, dict):
            raise ValueError(
                f"Assertion at index {aidx} in contract {contract_id} must be a mapping"
            )
        assertions.append(_parse_assertion(raw_a))

    risk_tier = str(entry.get("risk_tier", "low"))
    flake_raw = entry.get("flake_policy", {})
    flake_policy = FlakePolicy()
    if isinstance(flake_raw, dict):
        try:
            flake_policy = FlakePolicy.model_validate(flake_raw)
        except ValidationError:
            flake_policy = FlakePolicy()

    return VerificationContract(
        contract_id=contract_id,
        toolpack_digest=str(entry.get("toolpack_digest", "")),
        targets=targets,
        assertions=assertions,
        risk_tier=risk_tier,
        flake_policy=flake_policy,
        evidence_policy_ref=entry.get("evidence_policy_ref"),
    )


def _parse_assertion(raw: dict[str, Any]) -> Assertion:
    """Parse a raw assertion dict into an Assertion model."""
    atype = raw.get("type", "field_match")
    if atype not in ("api_state", "schema_check", "field_match"):
        atype = "field_match"

    op_str = raw.get("op", "exists")
    try:
        op = AssertionOp(op_str)
    except ValueError:
        op = AssertionOp.EXISTS

    return Assertion(
        type=atype,
        endpoint_ref=raw.get("endpoint_ref"),
        field_path=str(raw.get("field_path", "")),
        op=op,
        value=raw.get("value"),
        description=str(raw.get("description", "")),
    )


def validate_contract_file(contract_path: Path) -> ContractResult:
    """Validate a contract file exists and has valid schema.

    Returns a ContractResult with pass/fail status.
    """
    if not contract_path.exists():
        return ContractResult(
            contract_id="file_check",
            status=VerifyStatus.FAIL,
            fail_count=1,
        )

    try:
        raw = contract_path.read_text(encoding="utf-8")
        if contract_path.suffix in {".yaml", ".yml"}:
            payload = yaml.safe_load(raw) or {}
        else:
            payload = json.loads(raw)
    except Exception:
        return ContractResult(
            contract_id="file_check",
            status=VerifyStatus.FAIL,
            fail_count=1,
        )

    if not isinstance(payload, dict):
        return ContractResult(
            contract_id="file_check",
            status=VerifyStatus.FAIL,
            fail_count=1,
        )

    has_schema = bool(payload.get("schema_version"))
    has_version = bool(payload.get("version"))
    has_contracts = isinstance(payload.get("contracts"), list)

    if has_schema and has_version and has_contracts:
        return ContractResult(
            contract_id="file_check",
            status=VerifyStatus.PASS,
            pass_count=1,
        )
    elif has_schema or has_version:
        return ContractResult(
            contract_id="file_check",
            status=VerifyStatus.UNKNOWN,
            unknown_count=1,
        )
    else:
        return ContractResult(
            contract_id="file_check",
            status=VerifyStatus.FAIL,
            fail_count=1,
        )
