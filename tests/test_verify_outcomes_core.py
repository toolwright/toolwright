"""Tests for toolwright.core.verify.outcomes :: run_outcomes()."""

from __future__ import annotations

from toolwright.core.verify.outcomes import run_outcomes
from toolwright.models.verify import (
    Assertion,
    AssertionOp,
    VerificationContract,
    VerifyStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contract(
    contract_id: str = "vc_test",
    assertions: list[Assertion] | None = None,
) -> VerificationContract:
    """Build a VerificationContract with sensible defaults."""
    return VerificationContract(
        contract_id=contract_id,
        assertions=assertions or [],
    )


def _assertion(
    field_path: str = "status",
    op: AssertionOp = AssertionOp.EXISTS,
    value: object = None,
) -> Assertion:
    """Build a minimal Assertion."""
    return Assertion(field_path=field_path, op=op, value=value)


# ---------------------------------------------------------------------------
# empty / no-op cases
# ---------------------------------------------------------------------------

def test_empty_contracts_returns_unknown() -> None:
    """No contracts provided -> UNKNOWN."""
    result = run_outcomes(contracts=[], baseline_data={})

    assert result.status == VerifyStatus.UNKNOWN
    assert result.unknown_count == 1
    assert result.pass_count == 0
    assert result.fail_count == 0


def test_contract_with_no_assertions_returns_pass() -> None:
    """A contract that declares zero assertions counts as PASS."""
    result = run_outcomes(
        contracts=[_contract(assertions=[])],
        baseline_data={"anything": True},
    )

    assert result.status == VerifyStatus.PASS
    assert result.pass_count == 1


# ---------------------------------------------------------------------------
# EXISTS operator
# ---------------------------------------------------------------------------

def test_exists_field_present_returns_pass() -> None:
    """EXISTS on a field that is in the data -> PASS."""
    result = run_outcomes(
        contracts=[_contract(assertions=[_assertion(field_path="name", op=AssertionOp.EXISTS)])],
        baseline_data={"name": "alice"},
    )

    assert result.status == VerifyStatus.PASS
    assert result.pass_count == 1


def test_exists_field_missing_returns_fail() -> None:
    """EXISTS on a field that is NOT in the data -> FAIL."""
    result = run_outcomes(
        contracts=[_contract(assertions=[_assertion(field_path="missing_field", op=AssertionOp.EXISTS)])],
        baseline_data={"other": 1},
    )

    assert result.status == VerifyStatus.FAIL
    assert result.fail_count == 1


# ---------------------------------------------------------------------------
# EQUALS operator
# ---------------------------------------------------------------------------

def test_equals_matching_value_returns_pass() -> None:
    """EQUALS with matching value -> PASS."""
    result = run_outcomes(
        contracts=[_contract(assertions=[
            _assertion(field_path="status", op=AssertionOp.EQUALS, value=200),
        ])],
        baseline_data={"status": 200},
    )

    assert result.status == VerifyStatus.PASS


def test_equals_mismatched_value_returns_fail() -> None:
    """EQUALS with wrong value -> FAIL."""
    result = run_outcomes(
        contracts=[_contract(assertions=[
            _assertion(field_path="status", op=AssertionOp.EQUALS, value=200),
        ])],
        baseline_data={"status": 500},
    )

    assert result.status == VerifyStatus.FAIL


# ---------------------------------------------------------------------------
# CONTAINS operator
# ---------------------------------------------------------------------------

def test_contains_string_match_returns_pass() -> None:
    """CONTAINS on a string that includes the substring -> PASS."""
    result = run_outcomes(
        contracts=[_contract(assertions=[
            _assertion(field_path="message", op=AssertionOp.CONTAINS, value="ok"),
        ])],
        baseline_data={"message": "everything is ok here"},
    )

    assert result.status == VerifyStatus.PASS


def test_contains_list_match_returns_pass() -> None:
    """CONTAINS on a list that includes the element -> PASS."""
    result = run_outcomes(
        contracts=[_contract(assertions=[
            _assertion(field_path="tags", op=AssertionOp.CONTAINS, value="admin"),
        ])],
        baseline_data={"tags": ["user", "admin", "staff"]},
    )

    assert result.status == VerifyStatus.PASS


def test_contains_no_match_returns_fail() -> None:
    """CONTAINS when substring is absent -> FAIL."""
    result = run_outcomes(
        contracts=[_contract(assertions=[
            _assertion(field_path="message", op=AssertionOp.CONTAINS, value="error"),
        ])],
        baseline_data={"message": "all good"},
    )

    assert result.status == VerifyStatus.FAIL


# ---------------------------------------------------------------------------
# MATCHES_REGEX operator
# ---------------------------------------------------------------------------

def test_matches_regex_returns_pass() -> None:
    """MATCHES_REGEX with a matching pattern -> PASS."""
    result = run_outcomes(
        contracts=[_contract(assertions=[
            _assertion(field_path="email", op=AssertionOp.MATCHES_REGEX, value=r"^[^@]+@[^@]+\.\w+$"),
        ])],
        baseline_data={"email": "user@example.com"},
    )

    assert result.status == VerifyStatus.PASS


def test_matches_regex_no_match_returns_fail() -> None:
    """MATCHES_REGEX with no match -> FAIL."""
    result = run_outcomes(
        contracts=[_contract(assertions=[
            _assertion(field_path="code", op=AssertionOp.MATCHES_REGEX, value=r"^\d{4}$"),
        ])],
        baseline_data={"code": "abc"},
    )

    assert result.status == VerifyStatus.FAIL


def test_matches_regex_invalid_regex_returns_fail() -> None:
    """MATCHES_REGEX with invalid regex -> FAIL (not a crash)."""
    result = run_outcomes(
        contracts=[_contract(assertions=[
            _assertion(field_path="val", op=AssertionOp.MATCHES_REGEX, value=r"[invalid("),
        ])],
        baseline_data={"val": "something"},
    )

    assert result.status == VerifyStatus.FAIL


# ---------------------------------------------------------------------------
# Numeric comparison operators (GT, GTE, LT, LTE)
# ---------------------------------------------------------------------------

def test_gt_returns_pass_when_greater() -> None:
    """GT: actual > expected -> PASS."""
    result = run_outcomes(
        contracts=[_contract(assertions=[
            _assertion(field_path="count", op=AssertionOp.GT, value=5),
        ])],
        baseline_data={"count": 10},
    )

    assert result.status == VerifyStatus.PASS


def test_gt_returns_fail_when_equal() -> None:
    """GT: actual == expected -> FAIL."""
    result = run_outcomes(
        contracts=[_contract(assertions=[
            _assertion(field_path="count", op=AssertionOp.GT, value=10),
        ])],
        baseline_data={"count": 10},
    )

    assert result.status == VerifyStatus.FAIL


def test_lte_returns_pass_when_equal() -> None:
    """LTE: actual == expected -> PASS."""
    result = run_outcomes(
        contracts=[_contract(assertions=[
            _assertion(field_path="count", op=AssertionOp.LTE, value=10),
        ])],
        baseline_data={"count": 10},
    )

    assert result.status == VerifyStatus.PASS


# ---------------------------------------------------------------------------
# Nested field path resolution
# ---------------------------------------------------------------------------

def test_dotted_field_path_resolves_nested_dict() -> None:
    """Dot notation resolves into nested dicts -> PASS."""
    result = run_outcomes(
        contracts=[_contract(assertions=[
            _assertion(field_path="data.user.name", op=AssertionOp.EQUALS, value="alice"),
        ])],
        baseline_data={"data": {"user": {"name": "alice"}}},
    )

    assert result.status == VerifyStatus.PASS


def test_dotted_field_path_resolves_array_index() -> None:
    """Dot notation with numeric index resolves into lists -> PASS."""
    result = run_outcomes(
        contracts=[_contract(assertions=[
            _assertion(field_path="items.0.id", op=AssertionOp.EQUALS, value=42),
        ])],
        baseline_data={"items": [{"id": 42}, {"id": 99}]},
    )

    assert result.status == VerifyStatus.PASS


def test_missing_nested_field_returns_unknown() -> None:
    """Non-EXISTS op on a missing nested path -> UNKNOWN (field not found)."""
    result = run_outcomes(
        contracts=[_contract(assertions=[
            _assertion(field_path="a.b.c", op=AssertionOp.EQUALS, value="x"),
        ])],
        baseline_data={"a": {"b": {}}},
    )

    assert result.status == VerifyStatus.UNKNOWN
    cr = result.contract_results[0]
    assert cr.unknown_count >= 1


# ---------------------------------------------------------------------------
# Multiple contracts / mixed results
# ---------------------------------------------------------------------------

def test_multiple_contracts_all_pass() -> None:
    """Two passing contracts -> overall PASS."""
    result = run_outcomes(
        contracts=[
            _contract(contract_id="c1", assertions=[
                _assertion(field_path="a", op=AssertionOp.EXISTS),
            ]),
            _contract(contract_id="c2", assertions=[
                _assertion(field_path="b", op=AssertionOp.EQUALS, value=1),
            ]),
        ],
        baseline_data={"a": True, "b": 1},
    )

    assert result.status == VerifyStatus.PASS
    assert result.pass_count == 2
    assert result.fail_count == 0


def test_mixed_pass_and_fail_returns_overall_fail() -> None:
    """One passing + one failing contract -> overall FAIL."""
    result = run_outcomes(
        contracts=[
            _contract(contract_id="c_ok", assertions=[
                _assertion(field_path="x", op=AssertionOp.EXISTS),
            ]),
            _contract(contract_id="c_bad", assertions=[
                _assertion(field_path="y", op=AssertionOp.EQUALS, value=99),
            ]),
        ],
        baseline_data={"x": 1, "y": 0},
    )

    assert result.status == VerifyStatus.FAIL
    assert result.pass_count == 1
    assert result.fail_count == 1


def test_assertion_results_populated_in_contract() -> None:
    """Assertion results are accessible inside the ContractResult."""
    result = run_outcomes(
        contracts=[_contract(assertions=[
            _assertion(field_path="status", op=AssertionOp.EQUALS, value=200),
        ])],
        baseline_data={"status": 200},
    )

    cr = result.contract_results[0]
    assert len(cr.assertion_results) == 1
    ar = cr.assertion_results[0]
    assert ar.status == VerifyStatus.PASS
    assert ar.actual_value == 200
    assert ar.message != ""
