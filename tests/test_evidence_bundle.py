"""Tests for evidence bundle creation, storage, and loading."""

from __future__ import annotations

import json
from pathlib import Path

from toolwright.core.verify.evidence import (
    create_evidence_bundle,
    create_evidence_entry,
    load_evidence_bundle,
    save_evidence_bundle,
)


def test_create_evidence_entry_computes_digest() -> None:
    entry = create_evidence_entry(
        event_type="verify_result",
        source="verify_engine",
        data={"status": "pass", "tool_id": "get_users"},
    )
    assert entry.event_type == "verify_result"
    assert entry.source == "verify_engine"
    assert entry.digest  # non-empty
    assert len(entry.digest) == 64  # SHA-256 hex


def test_create_evidence_entry_deterministic_digest() -> None:
    data = {"a": 1, "b": 2}
    e1 = create_evidence_entry(event_type="test", source="test", data=data)
    e2 = create_evidence_entry(event_type="test", source="test", data=data)
    assert e1.digest == e2.digest


def test_create_evidence_entry_different_data_different_digest() -> None:
    e1 = create_evidence_entry(event_type="test", source="test", data={"a": 1})
    e2 = create_evidence_entry(event_type="test", source="test", data={"a": 2})
    assert e1.digest != e2.digest


def test_create_evidence_bundle_computes_bundle_digest() -> None:
    entries = [
        create_evidence_entry(event_type="a", source="s", data={"x": 1}),
        create_evidence_entry(event_type="b", source="s", data={"y": 2}),
    ]
    bundle = create_evidence_bundle(
        toolpack_id="tp_test",
        context="verify",
        entries=entries,
    )
    assert bundle.bundle_digest
    assert bundle.toolpack_id == "tp_test"
    assert bundle.context == "verify"
    assert len(bundle.entries) == 2


def test_bundle_digest_changes_with_entries() -> None:
    e1 = create_evidence_entry(event_type="a", source="s", data={"x": 1})
    e2 = create_evidence_entry(event_type="b", source="s", data={"y": 2})
    b1 = create_evidence_bundle(toolpack_id="tp", context="v", entries=[e1])
    b2 = create_evidence_bundle(toolpack_id="tp", context="v", entries=[e1, e2])
    assert b1.bundle_digest != b2.bundle_digest


def test_save_and_load_evidence_bundle(tmp_path: Path) -> None:
    entries = [
        create_evidence_entry(event_type="verify_result", source="engine", data={"pass": True}),
        create_evidence_entry(event_type="verify_detail", source="engine", data={"count": 5}),
    ]
    bundle = create_evidence_bundle(
        toolpack_id="tp_demo",
        context="verify",
        entries=entries,
    )

    evidence_dir = tmp_path / "evidence"
    saved_path = save_evidence_bundle(bundle, evidence_dir)
    assert saved_path.exists()
    assert saved_path.suffix == ".jsonl"

    # Verify JSONL format
    lines = saved_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3  # header + 2 entries

    header = json.loads(lines[0])
    assert header["type"] == "bundle_header"
    assert header["bundle_id"] == bundle.bundle_id
    assert header["entry_count"] == 2


def test_load_evidence_bundle_roundtrip(tmp_path: Path) -> None:
    entries = [
        create_evidence_entry(event_type="test", source="test", data={"key": "value"}),
    ]
    original = create_evidence_bundle(
        toolpack_id="tp_rt",
        context="verify",
        entries=entries,
    )

    evidence_dir = tmp_path / "evidence"
    save_evidence_bundle(original, evidence_dir)

    loaded = load_evidence_bundle(evidence_dir / f"{original.bundle_id}.jsonl")
    assert loaded is not None
    assert loaded.bundle_id == original.bundle_id
    assert loaded.toolpack_id == original.toolpack_id
    assert loaded.bundle_digest == original.bundle_digest
    assert len(loaded.entries) == 1
    assert loaded.entries[0].event_type == "test"


def test_load_evidence_bundle_missing_file(tmp_path: Path) -> None:
    result = load_evidence_bundle(tmp_path / "nope.jsonl")
    assert result is None


def test_save_creates_directory(tmp_path: Path) -> None:
    entries = [create_evidence_entry(event_type="t", source="s", data={})]
    bundle = create_evidence_bundle(toolpack_id="tp", context="v", entries=entries)
    deep_dir = tmp_path / "a" / "b" / "c" / "evidence"
    path = save_evidence_bundle(bundle, deep_dir)
    assert path.exists()
