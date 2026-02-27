"""Evidence collection and bundle creation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from toolwright.models.verify import EvidenceBundle, EvidenceEntry


def create_evidence_entry(
    *,
    event_type: str,
    source: str,
    data: dict[str, Any],
    redaction_profile: str = "default_safe",
) -> EvidenceEntry:
    """Create an evidence entry with computed digest."""
    canonical = json.dumps(data, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return EvidenceEntry(
        event_type=event_type,
        source=source,
        data=data,
        redaction_profile=redaction_profile,
        digest=digest,
    )


def create_evidence_bundle(
    *,
    toolpack_id: str,
    context: str,
    entries: list[EvidenceEntry],
    redaction_profile: str = "default_safe",
) -> EvidenceBundle:
    """Create an evidence bundle with computed bundle digest."""
    entry_digests = [e.digest for e in entries]
    bundle_digest = hashlib.sha256(
        "|".join(entry_digests).encode("utf-8")
    ).hexdigest()

    return EvidenceBundle(
        toolpack_id=toolpack_id,
        context=context,
        entries=entries,
        redaction_profile=redaction_profile,
        bundle_digest=bundle_digest,
    )


def save_evidence_bundle(bundle: EvidenceBundle, evidence_dir: Path) -> Path:
    """Save an evidence bundle as JSONL under the evidence directory.

    Returns the path to the written file.
    """
    evidence_dir.mkdir(parents=True, exist_ok=True)
    bundle_file = evidence_dir / f"{bundle.bundle_id}.jsonl"

    lines: list[str] = []
    # Write header line with bundle metadata
    header = {
        "type": "bundle_header",
        "bundle_id": bundle.bundle_id,
        "created_at": bundle.created_at,
        "toolpack_id": bundle.toolpack_id,
        "context": bundle.context,
        "redaction_profile": bundle.redaction_profile,
        "bundle_digest": bundle.bundle_digest,
        "entry_count": len(bundle.entries),
    }
    lines.append(json.dumps(header, sort_keys=True, default=str))

    # Write each entry as a line
    for entry in bundle.entries:
        line = entry.model_dump(mode="json")
        lines.append(json.dumps(line, sort_keys=True, default=str))

    bundle_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return bundle_file


def load_evidence_bundle(bundle_path: Path) -> EvidenceBundle | None:
    """Load an evidence bundle from a JSONL file."""
    if not bundle_path.exists():
        return None

    raw = bundle_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in raw.strip().split("\n") if line.strip()]
    if not lines:
        return None

    header = json.loads(lines[0])
    entries: list[EvidenceEntry] = []
    for line in lines[1:]:
        data = json.loads(line)
        entries.append(EvidenceEntry(**data))

    return EvidenceBundle(
        bundle_id=header.get("bundle_id", ""),
        created_at=header.get("created_at", ""),
        toolpack_id=header.get("toolpack_id", ""),
        context=header.get("context", ""),
        entries=entries,
        redaction_profile=header.get("redaction_profile", "default_safe"),
        bundle_digest=header.get("bundle_digest", ""),
    )
