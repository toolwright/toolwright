"""Out-of-band confirmation store for runtime step-up approvals."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from toolwright.models.decision import ReasonCode

SCHEMA_VERSION = 1
TOKEN_PREFIX = "cfrmv1"


class ConfirmationStore:
    """SQLite-backed confirmation challenge store."""

    def __init__(self, db_path: str | Path = ".toolwright/state/confirmations.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._signing_key_path = self.db_path.parent / "confirmation_signing.key"
        self._signing_key = self._load_or_create_signing_key()
        self._lock = threading.Lock()
        self._initialize()

    def _load_or_create_signing_key(self) -> bytes:
        if self._signing_key_path.exists():
            return self._signing_key_path.read_bytes()
        key = secrets.token_bytes(32)
        self._signing_key_path.write_bytes(key)
        os.chmod(self._signing_key_path, 0o600)
        return key

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_info (
                    version INTEGER NOT NULL
                )
                """
            )
            current = conn.execute("SELECT version FROM schema_info LIMIT 1").fetchone()
            if current is None:
                conn.execute("INSERT INTO schema_info(version) VALUES (?)", (SCHEMA_VERSION,))
            elif int(current["version"]) != SCHEMA_VERSION:
                raise ValueError(
                    f"Unsupported confirmations schema version {current['version']} "
                    f"(expected {SCHEMA_VERSION})"
                )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS confirmations (
                    token_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    toolset_name TEXT,
                    artifacts_digest TEXT NOT NULL,
                    lockfile_digest TEXT,
                    reason TEXT,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    granted_at REAL,
                    denied_at REAL,
                    used_at REAL
                )
                """
            )

        if self.db_path.exists():
            os.chmod(self.db_path, 0o600)

    def create_challenge(
        self,
        *,
        tool_id: str,
        request_digest: str,
        toolset_name: str | None,
        artifacts_digest: str,
        lockfile_digest: str | None,
        ttl_seconds: int,
    ) -> str:
        """Create a new pending challenge and return token id."""
        now = time.time()
        expires_at = now + max(1, ttl_seconds)
        nonce = secrets.token_hex(12)
        token_id = self._issue_token(
            nonce=nonce,
            tool_id=tool_id,
            request_digest=request_digest,
            toolset_name=toolset_name,
            artifacts_digest=artifacts_digest,
            lockfile_digest=lockfile_digest,
            expires_at=expires_at,
        )

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO confirmations(
                    token_id, status, tool_id, request_digest, toolset_name, artifacts_digest,
                    lockfile_digest, created_at, expires_at
                ) VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token_id,
                    tool_id,
                    request_digest,
                    toolset_name,
                    artifacts_digest,
                    lockfile_digest,
                    now,
                    expires_at,
                ),
            )
        return token_id

    def _issue_token(
        self,
        *,
        nonce: str,
        tool_id: str,
        request_digest: str,
        toolset_name: str | None,
        artifacts_digest: str,
        lockfile_digest: str | None,
        expires_at: float,
    ) -> str:
        payload = {
            "nonce": nonce,
            "tool_id": tool_id,
            "request_digest": request_digest,
            "toolset_name": toolset_name,
            "artifacts_digest": artifacts_digest,
            "lockfile_digest": lockfile_digest,
            "expires_at": int(expires_at),
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        encoded = base64.urlsafe_b64encode(serialized).decode("ascii").rstrip("=")
        signature = hmac.new(self._signing_key, serialized, hashlib.sha256).hexdigest()
        return f"{TOKEN_PREFIX}.{encoded}.{signature}"

    def _decode_token(self, token_id: str) -> dict[str, object] | None:
        # Backward compatibility for legacy random token IDs.
        if not token_id.startswith(f"{TOKEN_PREFIX}."):
            return None
        parts = token_id.split(".")
        if len(parts) != 3:
            return None
        _prefix, encoded, signature = parts
        try:
            padded = encoded + "=" * (-len(encoded) % 4)
            serialized = base64.urlsafe_b64decode(padded.encode("ascii"))
        except Exception:
            return None
        expected = hmac.new(self._signing_key, serialized, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None
        try:
            decoded = json.loads(serialized.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(decoded, dict):
            return None
        return decoded

    def grant(self, token_id: str) -> bool:
        """Grant a pending challenge token."""
        now = time.time()
        with self._lock, self._connect() as conn:
            result = conn.execute(
                """
                UPDATE confirmations
                SET status = 'granted', granted_at = ?
                WHERE token_id = ? AND status = 'pending' AND expires_at > ?
                """,
                (now, token_id, now),
            )
        return result.rowcount > 0

    def deny(self, token_id: str, reason: str | None = None) -> bool:
        """Deny a pending or granted challenge token."""
        now = time.time()
        with self._lock, self._connect() as conn:
            result = conn.execute(
                """
                UPDATE confirmations
                SET status = 'denied', denied_at = ?, reason = ?
                WHERE token_id = ? AND status IN ('pending', 'granted')
                """,
                (now, reason, token_id),
            )
        return result.rowcount > 0

    def list_pending(self) -> list[dict[str, Any]]:
        """List all pending confirmation tokens."""
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE confirmations
                SET status = 'expired'
                WHERE status IN ('pending', 'granted') AND expires_at <= ?
                """,
                (now,),
            )
            rows = conn.execute(
                """
                SELECT token_id, tool_id, request_digest, toolset_name, created_at, expires_at
                FROM confirmations
                WHERE status = 'pending'
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def consume_if_granted(
        self,
        *,
        token_id: str,
        tool_id: str,
        request_digest: str,
        toolset_name: str | None,
        artifacts_digest: str,
        lockfile_digest: str | None,
    ) -> tuple[bool, ReasonCode]:
        """Consume a granted token if all bindings match exactly."""
        now = time.time()
        with self._lock, self._connect() as conn:
            decoded = self._decode_token(token_id)
            if decoded is None and token_id.startswith(f"{TOKEN_PREFIX}."):
                return False, ReasonCode.DENIED_CONFIRMATION_INVALID
            if decoded is not None:
                token_exp_raw = decoded.get("expires_at", 0)
                if isinstance(token_exp_raw, int | float | str):
                    token_exp = float(token_exp_raw)
                else:
                    return False, ReasonCode.DENIED_CONFIRMATION_INVALID
                if token_exp <= now:
                    return False, ReasonCode.DENIED_CONFIRMATION_EXPIRED
                if (
                    decoded.get("tool_id") != tool_id
                    or decoded.get("request_digest") != request_digest
                    or decoded.get("toolset_name") != toolset_name
                    or decoded.get("artifacts_digest") != artifacts_digest
                    or decoded.get("lockfile_digest") != lockfile_digest
                ):
                    return False, ReasonCode.DENIED_CONFIRMATION_INVALID

            row = conn.execute(
                """
                SELECT *
                FROM confirmations
                WHERE token_id = ?
                """,
                (token_id,),
            ).fetchone()

            if row is None:
                return False, ReasonCode.DENIED_CONFIRMATION_INVALID

            status = str(row["status"])
            if status == "used":
                return False, ReasonCode.DENIED_CONFIRMATION_REPLAY

            if status == "expired" or row["expires_at"] <= now:
                if status != "expired":
                    conn.execute(
                        "UPDATE confirmations SET status='expired' WHERE token_id = ?",
                        (token_id,),
                    )
                return False, ReasonCode.DENIED_CONFIRMATION_EXPIRED

            if status != "granted":
                return False, ReasonCode.DENIED_CONFIRMATION_INVALID

            if (
                row["tool_id"] != tool_id
                or row["request_digest"] != request_digest
                or row["toolset_name"] != toolset_name
                or row["artifacts_digest"] != artifacts_digest
                or row["lockfile_digest"] != lockfile_digest
            ):
                return False, ReasonCode.DENIED_CONFIRMATION_INVALID

            result = conn.execute(
                """
                UPDATE confirmations
                SET status = 'used', used_at = ?
                WHERE token_id = ? AND status = 'granted'
                """,
                (now, token_id),
            )
            if result.rowcount == 0:
                return False, ReasonCode.DENIED_CONFIRMATION_REPLAY

        return True, ReasonCode.ALLOWED_CONFIRMATION_GRANTED
