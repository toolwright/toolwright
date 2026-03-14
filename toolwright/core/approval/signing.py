"""Approval signer identity and signature helpers."""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from toolwright.core.approval.lockfile import ToolApproval

DEFAULT_KEYS_DIR = "keys"
DEFAULT_PRIVATE_KEY = "approval_ed25519_private.pem"
DEFAULT_PUBLIC_KEY = "approval_ed25519_public.pem"
DEFAULT_TRUST_STORE = "trusted_signers.json"


class ApprovalSigner:
    """Local Ed25519 signer + trust store for approval records."""

    def __init__(self, root_path: str | Path = ".toolwright", *, read_only: bool = False) -> None:
        self.root_path = Path(root_path)
        self.keys_dir = self.root_path / "state" / DEFAULT_KEYS_DIR
        self.read_only = read_only
        if not self.read_only:
            self.keys_dir.mkdir(parents=True, exist_ok=True)
        self.private_key_path = self.keys_dir / DEFAULT_PRIVATE_KEY
        self.public_key_path = self.keys_dir / DEFAULT_PUBLIC_KEY
        self.trust_store_path = self.keys_dir / DEFAULT_TRUST_STORE
        self.algorithm = "ed25519"
        self._private_key: Ed25519PrivateKey | None = None
        self._public_key: Ed25519PublicKey | None = None
        self.key_id = ""
        if not self.read_only:
            self._private_key, self._public_key = self._load_or_create_keypair()
            self.key_id = self._compute_key_id(self._public_key)

    def _load_or_create_keypair(self) -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
        if self.private_key_path.exists():
            private_key = serialization.load_pem_private_key(
                self.private_key_path.read_bytes(),
                password=None,
            )
            if not isinstance(private_key, Ed25519PrivateKey):
                raise ValueError("approval private key is not an Ed25519 key")
            return private_key, private_key.public_key()

        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.private_key_path.write_bytes(private_bytes)
        self.public_key_path.write_bytes(public_bytes)
        os.chmod(self.private_key_path, 0o600)
        os.chmod(self.public_key_path, 0o644)
        return private_key, public_key

    def _compute_key_id(self, public_key: Ed25519PublicKey) -> str:
        raw = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return hashlib.sha256(raw).hexdigest()[:16]

    def _load_trust_store(self) -> dict[str, object]:
        if not self.trust_store_path.exists():
            return {"version": "1.0", "trusted_keys": []}
        payload = json.loads(self.trust_store_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {"version": "1.0", "trusted_keys": []}
        trusted = payload.get("trusted_keys", [])
        if not isinstance(trusted, list):
            payload["trusted_keys"] = []
        payload.setdefault("version", "1.0")
        return payload

    def _save_trust_store(self, payload: dict[str, object]) -> None:
        self.trust_store_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.chmod(self.trust_store_path, 0o600)

    def _public_key_raw(self) -> bytes:
        if self._public_key is None:
            raise ValueError("approval signer public key not available in read-only mode")
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def _ensure_key_trusted_for_signer(self, signer_id: str) -> None:
        if self.read_only:
            raise ValueError("approval trust store cannot be modified in read-only mode")
        payload = self._load_trust_store()
        trusted_keys = payload.get("trusted_keys")
        assert isinstance(trusted_keys, list)

        for item in trusted_keys:
            if not isinstance(item, dict):
                continue
            if (
                item.get("key_id") == self.key_id
                and item.get("signer_id") == signer_id
                and item.get("status", "active") == "active"
            ):
                return

        trusted_keys.append(
            {
                "key_id": self.key_id,
                "signer_id": signer_id,
                "algorithm": self.algorithm,
                "status": "active",
                "created_at": datetime.now(UTC).isoformat(),
                "public_key": base64.urlsafe_b64encode(self._public_key_raw()).decode("ascii"),
            }
        )
        payload["trusted_keys"] = trusted_keys
        self._save_trust_store(payload)

    def rotate_key(self, signer_id: str | None = None) -> str:
        """Rotate active signing key while preserving existing trust entries."""
        if self.read_only:
            raise ValueError("approval signer cannot rotate keys in read-only mode")
        self.private_key_path.unlink(missing_ok=True)
        self.public_key_path.unlink(missing_ok=True)
        self._private_key, self._public_key = self._load_or_create_keypair()
        self.key_id = self._compute_key_id(self._public_key)
        if signer_id:
            self._ensure_key_trusted_for_signer(signer_id)
        return self.key_id

    def revoke_key(self, key_id: str) -> bool:
        """Revoke a trusted signing key id."""
        if self.read_only:
            raise ValueError("approval signer cannot revoke keys in read-only mode")
        payload = self._load_trust_store()
        trusted_keys = payload.get("trusted_keys")
        assert isinstance(trusted_keys, list)
        changed = False
        for item in trusted_keys:
            if not isinstance(item, dict):
                continue
            if item.get("key_id") != key_id:
                continue
            item["status"] = "revoked"
            item["revoked_at"] = datetime.now(UTC).isoformat()
            changed = True
        if changed:
            payload["trusted_keys"] = trusted_keys
            self._save_trust_store(payload)
        return changed

    def _signature_payload(
        self,
        *,
        tool: ToolApproval,
        approved_by: str,
        approved_at: datetime,
        reason: str | None,
        mode: str,
    ) -> str:
        toolsets = ",".join(sorted(set(tool.toolsets)))
        approved_toolsets = ",".join(sorted(set(tool.approved_toolsets)))
        status = tool.status.value if hasattr(tool.status, "value") else str(tool.status)
        risk_tier = getattr(tool, "risk_tier", "low") or "low"
        return "|".join(
            [
                tool.signature_id or tool.tool_id,
                tool.name,
                tool.method.upper(),
                tool.path,
                tool.host.lower(),
                tool.risk_tier,
                toolsets,
                approved_toolsets,
                status,
                risk_tier,
                approved_by,
                approved_at.isoformat(),
                reason or "",
                mode,
            ]
        )

    def sign_approval(
        self,
        *,
        tool: ToolApproval,
        approved_by: str,
        approved_at: datetime,
        reason: str | None,
        mode: str = "1-of-1",
    ) -> str:
        """Sign an approval record with local Ed25519 key."""
        if self._private_key is None:
            raise ValueError("approval signer private key not available in read-only mode")
        self._ensure_key_trusted_for_signer(approved_by)
        payload = self._signature_payload(
            tool=tool,
            approved_by=approved_by,
            approved_at=approved_at,
            reason=reason,
            mode=mode,
        )
        signature = self._private_key.sign(payload.encode("utf-8"))
        encoded = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
        return f"ed25519:{self.key_id}:{encoded}"

    def verify_approval(
        self,
        *,
        tool: ToolApproval,
        approved_by: str,
        approved_at: datetime | None,
        reason: str | None,
        mode: str = "1-of-1",
        signature: str,
    ) -> bool:
        """Verify approval signature against trusted active signer keys."""
        if approved_at is None:
            return False
        parts = signature.split(":")
        if len(parts) != 3:
            return False
        algorithm, key_id, encoded_sig = parts
        if algorithm != self.algorithm:
            return False

        payload = self._signature_payload(
            tool=tool,
            approved_by=approved_by,
            approved_at=approved_at,
            reason=reason,
            mode=mode,
        ).encode("utf-8")

        padded = encoded_sig + "=" * (-len(encoded_sig) % 4)
        try:
            signature_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
        except ValueError:
            return False

        payload_store = self._load_trust_store()
        trusted_keys = payload_store.get("trusted_keys")
        if not isinstance(trusted_keys, list):
            return False

        for item in trusted_keys:
            if not isinstance(item, dict):
                continue
            if item.get("key_id") != key_id:
                continue
            if item.get("algorithm") != self.algorithm:
                continue
            if item.get("status", "active") != "active":
                continue
            if item.get("signer_id") != approved_by:
                continue
            raw_key = item.get("public_key")
            if not isinstance(raw_key, str):
                continue
            try:
                decoded_key = base64.urlsafe_b64decode(raw_key.encode("ascii"))
                public_key = Ed25519PublicKey.from_public_bytes(decoded_key)
                public_key.verify(signature_bytes, payload)
                return True
            except (ValueError, InvalidSignature):
                continue

        return False


def resolve_approval_root(
    *,
    lockfile_path: str | Path | None = None,
    fallback_root: str | Path | None = None,
) -> Path:
    """Resolve canonical root path for approval trust material."""

    def _find_toolwright_root(candidate: Path) -> Path | None:
        for parent in (candidate, *candidate.parents):
            if parent.name == ".toolwright":
                return parent
        return None

    env_root = os.environ.get("TOOLWRIGHT_ROOT")
    if env_root:
        return Path(env_root)

    resolved_fallback: Path | None = None
    if fallback_root:
        resolved = Path(fallback_root).resolve()
        if resolved.name == ".toolwright":
            resolved_fallback = resolved
        elif resolved.parent.name == "state":
            resolved_fallback = resolved.parent.parent
        else:
            resolved_fallback = _find_toolwright_root(resolved)

    if lockfile_path:
        resolved_lockfile = Path(lockfile_path).resolve()
        resolved_lock_root = _find_toolwright_root(resolved_lockfile)
        if resolved_lock_root is not None:
            return resolved_lock_root
        if resolved_fallback is not None:
            return resolved_fallback
        return Path(".toolwright")

    if resolved_fallback is not None:
        return resolved_fallback

    return Path(".toolwright")


def resolve_approver(actor: str | None) -> str:
    """Resolve approver identity and enforce optional allowlist."""
    resolved = actor or getpass.getuser()
    allowlist = os.environ.get("TOOLWRIGHT_APPROVERS", "").strip()
    if not allowlist:
        return resolved
    allowed = {item.strip() for item in allowlist.split(",") if item.strip()}
    if resolved not in allowed:
        raise ValueError(
            f"Approver '{resolved}' is not allowlisted. "
            "Set TOOLWRIGHT_APPROVERS to permit this identity."
        )
    return resolved
