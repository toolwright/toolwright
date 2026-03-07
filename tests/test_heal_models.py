"""Tests for heal system data models."""

from __future__ import annotations

import json

import pytest


class TestFieldType:
    def test_all_eight_values_exist(self):
        from toolwright.models.heal import FieldType

        expected = {"string", "integer", "number", "boolean", "array", "object", "null", "unknown"}
        assert {v.value for v in FieldType} == expected

    def test_string_representation(self):
        from toolwright.models.heal import FieldType

        assert str(FieldType.STRING) == "string"
        assert str(FieldType.INTEGER) == "integer"


class TestPresenceConfidence:
    def test_three_levels(self):
        from toolwright.models.heal import PresenceConfidence

        assert {v.value for v in PresenceConfidence} == {"low", "medium", "high"}


class TestHealDriftSeverity:
    def test_five_levels(self):
        from toolwright.models.heal import HealDriftSeverity

        expected = {"safe", "low", "medium", "high", "critical"}
        assert {v.value for v in HealDriftSeverity} == expected


class TestChangeType:
    def test_fifteen_values_exist(self):
        from toolwright.models.heal import ChangeType

        assert len(ChangeType) == 15

    def test_severity_mappings(self):
        from toolwright.models.heal import ChangeType, HealDriftSeverity

        safe_types = {
            ChangeType.FIELD_ADDED,
            ChangeType.OPTIONALITY_CHANGED,
            ChangeType.HEADER_CHANGED,
            ChangeType.RATE_LIMIT_CHANGED,
        }
        for ct in safe_types:
            assert ct.severity() == HealDriftSeverity.SAFE, f"{ct} should be SAFE"

        low_types = {
            ChangeType.FIELD_RENAMED,
            ChangeType.NULLABILITY_CHANGED,
            ChangeType.STATUS_CODE_CHANGED,
        }
        for ct in low_types:
            assert ct.severity() == HealDriftSeverity.LOW, f"{ct} should be LOW"

        medium_types = {
            ChangeType.FIELD_REMOVED,
            ChangeType.TYPE_CHANGED,
            ChangeType.VALUE_FORMAT_CHANGED,
            ChangeType.ENDPOINT_MOVED,
        }
        for ct in medium_types:
            assert ct.severity() == HealDriftSeverity.MEDIUM, f"{ct} should be MEDIUM"

        high_types = {
            ChangeType.STRUCTURE_CHANGED,
            ChangeType.NESTING_CHANGED,
            ChangeType.PAGINATION_CHANGED,
        }
        for ct in high_types:
            assert ct.severity() == HealDriftSeverity.HIGH, f"{ct} should be HIGH"

        assert ChangeType.AUTH_CHANGED.severity() == HealDriftSeverity.CRITICAL


class TestFieldTypeInfo:
    def test_construction(self):
        from toolwright.models.heal import FieldTypeInfo

        fti = FieldTypeInfo(types=["string", "null"], nullable=True)
        assert fti.types == ["string", "null"]
        assert fti.nullable is True

    def test_defaults(self):
        from toolwright.models.heal import FieldTypeInfo

        fti = FieldTypeInfo(types=["object"])
        assert fti.nullable is False


class TestFieldSchema:
    def test_construction(self):
        from toolwright.models.heal import FieldSchema

        fs = FieldSchema(
            name="id",
            path="data.customers[].id",
            field_type="string",
            nullable=False,
            optional=False,
            presence_rate=1.0,
            presence_confidence="medium",
            observed_types=["string"],
        )
        assert fs.path == "data.customers[].id"
        assert fs.presence_rate == 1.0

    def test_round_trip(self):
        from toolwright.models.heal import FieldSchema

        fs = FieldSchema(
            name="tax_id",
            path="data.customers[].tax_id",
            field_type="string",
            nullable=True,
            optional=True,
            presence_rate=0.75,
            presence_confidence="medium",
            observed_types=["string", "null"],
            example_values=["[REDACTED]"],
        )
        data = fs.model_dump()
        restored = FieldSchema.model_validate(data)
        assert restored == fs


class TestInferredSchema:
    def test_construction(self):
        from toolwright.models.heal import FieldSchema, InferredSchema

        schema = InferredSchema(
            tool_id="list_customers",
            variant="list_customers:default",
            schema_hash="f8e7d6c5b4a39281",
            sample_count=23,
            first_seen=1709500000.0,
            last_seen=1709571234.0,
            response_type="object",
            fields={
                "(root)": FieldSchema(
                    name="(root)",
                    path="(root)",
                    field_type="object",
                    nullable=False,
                    optional=False,
                    presence_rate=1.0,
                    presence_confidence="medium",
                    observed_types=["object"],
                ),
            },
        )
        assert schema.tool_id == "list_customers"
        assert "(root)" in schema.fields

    def test_round_trip(self):
        from toolwright.models.heal import FieldSchema, InferredSchema

        schema = InferredSchema(
            tool_id="get_user",
            variant="get_user:default",
            schema_hash="abc123",
            sample_count=5,
            first_seen=1000.0,
            last_seen=2000.0,
            response_type="object",
            fields={
                "(root)": FieldSchema(
                    name="(root)",
                    path="(root)",
                    field_type="object",
                    nullable=False,
                    optional=False,
                    presence_rate=1.0,
                    presence_confidence="low",
                    observed_types=["object"],
                ),
            },
        )
        data = schema.model_dump()
        restored = InferredSchema.model_validate(data)
        assert restored == schema


class TestResponseSample:
    def test_construction(self):
        from toolwright.models.heal import FieldTypeInfo, ResponseSample

        sample = ResponseSample(
            tool_id="list_customers",
            variant="list_customers:default",
            timestamp=1709571234.567,
            status_code=200,
            latency_ms=142,
            schema_hash="a1b2c3d4e5f6g7h8",
            typed_shape={
                "(root)": FieldTypeInfo(types=["object"], nullable=False),
                "data": FieldTypeInfo(types=["object"], nullable=False),
            },
            presence_paths=["(root)", "data"],
            examples={"data.id": "cus_abc123"},
        )
        assert sample.tool_id == "list_customers"
        assert "(root)" in sample.typed_shape

    def test_root_always_present(self):
        """Every valid ResponseSample must have (root) in typed_shape."""
        from toolwright.models.heal import FieldTypeInfo, ResponseSample

        sample = ResponseSample(
            tool_id="test",
            variant="test:default",
            timestamp=1000.0,
            status_code=200,
            latency_ms=50,
            schema_hash="abc",
            typed_shape={
                "(root)": FieldTypeInfo(types=["object"], nullable=False),
            },
            presence_paths=["(root)"],
            examples={},
        )
        assert "(root)" in sample.typed_shape

    def test_round_trip(self):
        from toolwright.models.heal import FieldTypeInfo, ResponseSample

        sample = ResponseSample(
            tool_id="test",
            variant="test:default",
            timestamp=1000.5,
            status_code=200,
            latency_ms=99,
            schema_hash="xyz",
            typed_shape={
                "(root)": FieldTypeInfo(types=["array"], nullable=False),
                "[]": FieldTypeInfo(types=["object"], nullable=False),
                "[].id": FieldTypeInfo(types=["string"], nullable=False),
            },
            presence_paths=["(root)", "[]", "[].id"],
            examples={"[].id": "item_1"},
        )
        data = json.loads(sample.model_dump_json())
        restored = ResponseSample.model_validate(data)
        assert restored == sample


class TestDriftChange:
    def test_construction(self):
        from toolwright.models.heal import ChangeType, DriftChange, HealDriftSeverity

        dc = DriftChange(
            change_type=ChangeType.FIELD_RENAMED,
            severity=HealDriftSeverity.LOW,
            field_path="data.customers[].customer_name",
            description="Field renamed: customer_name -> customerName",
            old_value="customer_name (string)",
            new_value="customerName (string)",
            needs_code_repair=True,
            repair_hint="Update all references in response handling.",
        )
        assert dc.needs_code_repair is True
        assert dc.repair_hint is not None

    def test_optional_fields(self):
        from toolwright.models.heal import ChangeType, DriftChange, HealDriftSeverity

        dc = DriftChange(
            change_type=ChangeType.FIELD_ADDED,
            severity=HealDriftSeverity.SAFE,
            field_path="data.new_field",
            description="New field appeared",
        )
        assert dc.old_value is None
        assert dc.new_value is None
        assert dc.needs_code_repair is False
        assert dc.repair_hint is None


class TestDriftDiagnosis:
    def _make_diagnosis(self):
        from toolwright.models.heal import (
            ChangeType,
            DriftChange,
            DriftDiagnosis,
            HealDriftSeverity,
        )

        return DriftDiagnosis(
            tool_id="list_customers",
            variant="list_customers:default",
            tool_source_path="server/tools/customers.py",
            timestamp=1709571300.0,
            overall_severity=HealDriftSeverity.LOW,
            needs_code_repair=True,
            source_available=True,
            baseline_schema_hash="f8e7d6c5b4a39281",
            current_schema_hash="1a2b3c4d5e6f7890",
            changes=[
                DriftChange(
                    change_type=ChangeType.FIELD_RENAMED,
                    severity=HealDriftSeverity.LOW,
                    field_path="data.customers[].customer_name",
                    description="Field renamed: customer_name -> customerName",
                    old_value="customer_name (string)",
                    new_value="customerName (string)",
                    needs_code_repair=True,
                    repair_hint="Update all references in response handling.",
                ),
            ],
            baseline_sample={"data.customers[].customer_name": "Acme Corp"},
            current_sample={
                "data.customers[].customerName": "Acme Corp",
                "data.customers[].tax_id": None,
            },
        )

    def test_format_for_agent(self):
        diag = self._make_diagnosis()
        text = diag.format_for_agent()
        assert "list_customers" in text
        assert "FIELD_RENAMED" in text or "field_renamed" in text
        assert "customer_name" in text

    def test_format_compact(self):
        diag = self._make_diagnosis()
        compact = diag.format_compact()
        assert isinstance(compact, str)
        assert len(compact) > 0

    def test_to_json_from_json_round_trip(self):
        diag = self._make_diagnosis()
        json_str = diag.to_json()
        restored = type(diag).from_json(json_str)
        assert restored.tool_id == diag.tool_id
        assert restored.overall_severity == diag.overall_severity
        assert len(restored.changes) == len(diag.changes)
        assert restored.changes[0].change_type == diag.changes[0].change_type


class TestValidationResult:
    def test_construction(self):
        from toolwright.models.heal import ValidationCheck, ValidationResult

        result = ValidationResult(
            passed=True,
            checks=[
                ValidationCheck(name="health_probe", passed=True, detail="HTTP 200 (142ms)"),
                ValidationCheck(name="schema_match", passed=True, detail="23 fields, 0 missing"),
            ],
        )
        assert result.passed is True
        assert len(result.checks) == 2

    def test_with_error(self):
        from toolwright.models.heal import ValidationResult

        result = ValidationResult(passed=False, checks=[], error="Connection refused")
        assert result.passed is False
        assert result.error == "Connection refused"


class TestConfidenceScore:
    def test_construction(self):
        from toolwright.models.heal import ConfidenceScore

        score = ConfidenceScore(value=0.85, factors={"validation": 0.40, "complexity": 0.25})
        assert score.value == 0.85
        assert "validation" in score.factors


class TestRepairCostEntry:
    def test_construction(self):
        from toolwright.models.heal import RepairCostEntry

        entry = RepairCostEntry(
            tool_id="list_customers",
            mode="autonomous",
            tokens_used=1500,
            cost_usd=0.0045,
            timestamp=1709571300.0,
        )
        assert entry.mode == "autonomous"
        assert entry.cost_usd == 0.0045
