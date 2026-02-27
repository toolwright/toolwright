"""DecisionTrace JSONL emission helpers."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class DecisionTraceEmitter:
    """Emit strict DecisionTrace records to audit.log.jsonl."""

    def __init__(
        self,
        *,
        output_path: str | Path | None,
        run_id: str,
        lockfile_digest: str | None,
        policy_digest: str | None,
    ) -> None:
        self.path = Path(output_path) if output_path else None
        self.run_id = run_id
        self.lockfile_digest = lockfile_digest
        self.policy_digest = policy_digest
        self._lock = threading.Lock()
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        *,
        tool_id: str | None,
        scope_id: str | None,
        request_fingerprint: str | None,
        decision: str,
        reason_code: str,
        evidence_refs: list[str] | None = None,
        confirmation_issuer: str | None = None,
        provenance_mode: str = "runtime",
        extra: dict[str, Any] | None = None,
    ) -> None:
        if self.path is None:
            return

        record: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "tool_id": tool_id,
            "scope_id": scope_id,
            "request_fingerprint": request_fingerprint,
            "decision": decision,
            "reason_code": reason_code,
            "evidence_refs": evidence_refs or [],
            "lockfile_digest": self.lockfile_digest,
            "policy_digest": self.policy_digest,
            "confirmation_issuer": confirmation_issuer,
            "provenance_mode": provenance_mode,
        }
        if extra:
            record.update(extra)

        with self._lock, open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
