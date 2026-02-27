"""Outcomes verification — check tool post-conditions against contracts."""

from __future__ import annotations

import re
from typing import Any

from toolwright.models.verify import (
    Assertion,
    AssertionOp,
    AssertionResult,
    ContractResult,
    OutcomesResult,
    VerificationContract,
    VerifyStatus,
)


def run_outcomes(
    *,
    contracts: list[VerificationContract],
    baseline_data: dict[str, Any],
) -> OutcomesResult:
    """Run outcomes verification: evaluate contract assertions against baseline data.

    For each contract, evaluate each assertion against the provided baseline data.
    """
    if not contracts:
        return OutcomesResult(
            status=VerifyStatus.UNKNOWN,
            unknown_count=1,
        )

    contract_results: list[ContractResult] = []
    for contract in contracts:
        result = _evaluate_contract(contract, baseline_data)
        contract_results.append(result)

    pass_count = sum(1 for r in contract_results if r.status == VerifyStatus.PASS)
    fail_count = sum(1 for r in contract_results if r.status == VerifyStatus.FAIL)
    unknown_count = sum(1 for r in contract_results if r.status == VerifyStatus.UNKNOWN)

    if fail_count > 0:
        overall = VerifyStatus.FAIL
    elif unknown_count > 0:
        overall = VerifyStatus.UNKNOWN
    elif pass_count > 0:
        overall = VerifyStatus.PASS
    else:
        overall = VerifyStatus.UNKNOWN

    return OutcomesResult(
        status=overall,
        contract_results=contract_results,
        pass_count=pass_count,
        fail_count=fail_count,
        unknown_count=unknown_count,
    )


def _evaluate_contract(
    contract: VerificationContract,
    baseline_data: dict[str, Any],
) -> ContractResult:
    """Evaluate all assertions in a contract."""
    if not contract.assertions:
        return ContractResult(
            contract_id=contract.contract_id,
            status=VerifyStatus.PASS,
            pass_count=1,
        )

    results: list[AssertionResult] = []
    for assertion in contract.assertions:
        result = _evaluate_assertion(assertion, baseline_data)
        results.append(result)

    pass_count = sum(1 for r in results if r.status == VerifyStatus.PASS)
    fail_count = sum(1 for r in results if r.status == VerifyStatus.FAIL)
    unknown_count = sum(1 for r in results if r.status == VerifyStatus.UNKNOWN)

    if fail_count > 0:
        status = VerifyStatus.FAIL
    elif unknown_count > 0:
        status = VerifyStatus.UNKNOWN
    else:
        status = VerifyStatus.PASS

    return ContractResult(
        contract_id=contract.contract_id,
        status=status,
        assertion_results=results,
        pass_count=pass_count,
        fail_count=fail_count,
        unknown_count=unknown_count,
    )


def _evaluate_assertion(
    assertion: Assertion,
    data: dict[str, Any],
) -> AssertionResult:
    """Evaluate a single assertion against data."""
    actual = _resolve_field_path(assertion.field_path, data)

    if actual is _MISSING:
        if assertion.op == AssertionOp.EXISTS:
            return AssertionResult(
                assertion=assertion,
                status=VerifyStatus.FAIL,
                actual_value=None,
                message=f"Field '{assertion.field_path}' does not exist",
            )
        return AssertionResult(
            assertion=assertion,
            status=VerifyStatus.UNKNOWN,
            actual_value=None,
            message=f"Field '{assertion.field_path}' not found in data",
        )

    matched = _check_op(assertion.op, actual, assertion.value)
    status = VerifyStatus.PASS if matched else VerifyStatus.FAIL
    msg = (
        f"Field '{assertion.field_path}' {assertion.op} check passed"
        if matched
        else f"Field '{assertion.field_path}' {assertion.op} check failed: actual={actual!r}, expected={assertion.value!r}"
    )

    return AssertionResult(
        assertion=assertion,
        status=status,
        actual_value=actual,
        message=msg,
    )


class _MissingSentinel:
    """Sentinel for missing field path resolution."""

    def __repr__(self) -> str:
        return "<MISSING>"


_MISSING = _MissingSentinel()


def _resolve_field_path(path: str, data: Any) -> Any:
    """Resolve a dot-notation field path against data.

    Supports: "foo.bar.baz", "items.0.name" (array index).
    """
    if not path:
        return data

    parts = path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict):
            if part in current:
                current = current[part]
            else:
                return _MISSING
        elif isinstance(current, list | tuple):
            try:
                idx = int(part)
                current = current[idx]
            except (ValueError, IndexError):
                return _MISSING
        else:
            return _MISSING
    return current


def _check_op(op: AssertionOp, actual: Any, expected: Any) -> bool:
    """Check if actual value satisfies the operation against expected."""
    if op == AssertionOp.EXISTS:
        return actual is not _MISSING

    if op == AssertionOp.EQUALS:
        return bool(actual == expected)

    if op == AssertionOp.CONTAINS:
        if isinstance(actual, str) and isinstance(expected, str):
            return expected in actual
        if isinstance(actual, list | tuple):
            return expected in actual
        return False

    if op == AssertionOp.MATCHES_REGEX:
        if not isinstance(actual, str) or not isinstance(expected, str):
            return False
        try:
            return bool(re.search(expected, actual))
        except re.error:
            return False

    if op in (AssertionOp.GT, AssertionOp.GTE, AssertionOp.LT, AssertionOp.LTE):
        try:
            a = float(actual)
            e = float(expected)
        except (TypeError, ValueError):
            return False
        if op == AssertionOp.GT:
            return a > e
        if op == AssertionOp.GTE:
            return a >= e
        if op == AssertionOp.LT:
            return a < e
        if op == AssertionOp.LTE:
            return a <= e

    return False
