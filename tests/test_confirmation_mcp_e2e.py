"""MCP stdio integration test for confirmation lifecycle.

Proves the product promise: a real MCP client communicating over NDJSON
can trigger and complete the confirmation flow:
  1. tools/call POST tool → confirmation_required response
  2. Grant token out-of-band via ConfirmationStore
  3. Retry tools/call with token → dry_run (ALLOW) response
  4. Replay same token → blocked (DENY) response
"""

from __future__ import annotations

import json
import signal
import subprocess
import threading
from pathlib import Path

import pytest
import yaml

from toolwright.core.enforce import ConfirmationStore


def _write_post_toolpack(tmp_path: Path) -> Path:
    """Create a minimal toolpack containing a POST tool that triggers confirmation."""
    toolpack_dir = tmp_path / "toolpack"
    artifact_dir = toolpack_dir / "artifact"
    lockfile_dir = toolpack_dir / "lockfile"
    artifact_dir.mkdir(parents=True)
    lockfile_dir.mkdir(parents=True)

    tools_path = artifact_dir / "tools.json"
    tools_path.write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "schema_version": "1.0",
                "name": "ConfirmTest",
                "allowed_hosts": ["httpbin.org"],
                "actions": [
                    {
                        "name": "create_item",
                        "method": "POST",
                        "path": "/post",
                        "host": "httpbin.org",
                        "signature_id": "sig_create_item",
                        "tool_id": "sig_create_item",
                        "risk_tier": "medium",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                            },
                        },
                    },
                    {
                        "name": "get_item",
                        "method": "GET",
                        "path": "/get",
                        "host": "httpbin.org",
                        "signature_id": "sig_get_item",
                        "tool_id": "sig_get_item",
                        "risk_tier": "low",
                        "input_schema": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                ],
            }
        )
    )

    toolsets_path = artifact_dir / "toolsets.yaml"
    toolsets_path.write_text(
        yaml.safe_dump(
            {
                "version": "1.0.0",
                "schema_version": "1.0",
                "toolsets": {
                    "operator": {"actions": ["create_item", "get_item"]},
                },
            }
        )
    )

    policy_path = artifact_dir / "policy.yaml"
    policy_path.write_text(
        yaml.safe_dump(
            {
                "version": "1.0.0",
                "schema_version": "1.0",
                "name": "ConfirmTest Policy",
                "default_action": "deny",
                "rules": [
                    {
                        "id": "allow_all",
                        "name": "Allow all methods",
                        "type": "allow",
                        "priority": 100,
                        "match": {"methods": ["GET", "POST"]},
                    },
                ],
            }
        )
    )

    baseline_path = artifact_dir / "baseline.json"
    baseline_path.write_text("{}")

    toolpack_path = toolpack_dir / "toolpack.yaml"
    toolpack_path.write_text(
        yaml.safe_dump(
            {
                "version": "1.0.0",
                "schema_version": "1.0",
                "toolpack_id": "tp_confirm_test",
                "created_at": "1970-01-01T00:00:00+00:00",
                "capture_id": "cap_confirm",
                "artifact_id": "art_confirm",
                "scope": "operator",
                "allowed_hosts": ["httpbin.org"],
                "origin": {"start_url": "https://httpbin.org", "name": "ConfirmTest"},
                "paths": {
                    "tools": "artifact/tools.json",
                    "toolsets": "artifact/toolsets.yaml",
                    "policy": "artifact/policy.yaml",
                    "baseline": "artifact/baseline.json",
                    "lockfiles": {"pending": "lockfile/toolwright.lock.pending.yaml"},
                },
            },
            sort_keys=False,
        )
    )

    # Create empty pending lockfile
    pending = lockfile_dir / "toolwright.lock.pending.yaml"
    pending.write_text("version: '1.0.0'\nschema_version: '1.0'\ntools: {}\n")

    return toolpack_path


class _MCPClient:
    """Thin NDJSON client for MCP stdio protocol."""

    def __init__(self, proc: subprocess.Popen) -> None:
        self.proc = proc
        self._msg_id = 0
        self.stderr_lines: list[bytes] = []
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.stderr_lines.append(line)

    def send(self, method: str, params: dict | None = None, *, is_notification: bool = False) -> int | None:
        self._msg_id += 1
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if not is_notification:
            msg["id"] = self._msg_id
        if params is not None:
            msg["params"] = params
        data = json.dumps(msg).encode() + b"\n"
        assert self.proc.stdin is not None
        self.proc.stdin.write(data)
        self.proc.stdin.flush()
        return None if is_notification else self._msg_id

    def recv(self, timeout: float = 10.0) -> dict:
        """Read next JSON-RPC response (skipping notifications)."""
        import select

        assert self.proc.stdout is not None
        while True:
            ready, _, _ = select.select([self.proc.stdout], [], [], timeout)
            if not ready:
                raise TimeoutError("No response from MCP server")
            line = self.proc.stdout.readline()
            if not line:
                stderr_text = b"".join(self.stderr_lines).decode(errors="replace")
                raise RuntimeError(f"Server EOF. stderr:\n{stderr_text}")
            msg = json.loads(line)
            if "id" in msg:
                return msg

    def initialize(self) -> dict:
        self.send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        )
        resp = self.recv()
        assert resp.get("id") == self._msg_id
        self.send("notifications/initialized", is_notification=True)
        return resp

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        msg_id = self.send("tools/call", {"name": name, "arguments": arguments or {}})
        resp = self.recv()
        assert resp.get("id") == msg_id
        return resp

    def close(self) -> None:
        self.proc.terminate()
        self.proc.wait(timeout=5)


def _find_cask_exe() -> str:
    """Find the toolwright executable in the venv."""
    import shutil

    # Prefer venv toolwright
    venv_cask = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "toolwright"
    if venv_cask.exists():
        return str(venv_cask)
    found = shutil.which("toolwright")
    if found:
        return found
    pytest.skip("toolwright executable not found")
    return ""  # unreachable


def test_confirmation_lifecycle_over_mcp_stdio(tmp_path: Path) -> None:
    """Full confirmation lifecycle via MCP NDJSON protocol.

    1. tools/call POST tool → confirmation_required
    2. Grant token via ConfirmationStore
    3. Retry with token → dry_run (allowed)
    4. Replay with same token → blocked (denied)
    """
    toolpack_path = _write_post_toolpack(tmp_path)
    confirm_db = tmp_path / "confirmations.db"
    cask_exe = _find_cask_exe()

    proc = subprocess.Popen(
        [
            cask_exe,
            "serve",
            "--toolpack",
            str(toolpack_path),
            "--dry-run",
            "--unsafe-no-lockfile",
            "--toolset",
            "operator",
            "--confirm-store",
            str(confirm_db),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        client = _MCPClient(proc)
        init_resp = client.initialize()
        assert "result" in init_resp

        # Step 1: Call POST tool → should require confirmation
        resp1 = client.call_tool("create_item", {"name": "test_item"})
        result1 = resp1["result"]
        content_text = result1["content"][0]["text"]
        payload1 = json.loads(content_text)

        assert payload1["status"] == "confirmation_required", f"Expected confirmation, got: {payload1}"
        assert payload1["decision"] == "confirm"
        assert payload1["reason_code"] == "confirmation_required"
        token_id = payload1["confirmation_token_id"]
        assert token_id is not None
        assert token_id.startswith("cfrmv1.")

        # Step 2: Grant token out-of-band via ConfirmationStore
        store = ConfirmationStore(str(confirm_db))
        assert store.grant(token_id), f"Failed to grant token: {token_id}"

        # Step 3: Retry with granted token → should succeed (dry_run)
        resp2 = client.call_tool("create_item", {"name": "test_item", "confirmation_token_id": token_id})
        result2 = resp2["result"]
        content_text2 = result2["content"][0]["text"]
        payload2 = json.loads(content_text2)

        assert payload2["status"] == "dry_run", f"Expected dry_run, got: {payload2}"
        assert payload2["decision"] == "allow"
        assert payload2["reason_code"] == "allowed_confirmation_granted"

        # Step 4: Replay with same token → should be denied
        resp3 = client.call_tool("create_item", {"name": "test_item", "confirmation_token_id": token_id})
        result3 = resp3["result"]
        content_text3 = result3["content"][0]["text"]
        payload3 = json.loads(content_text3)

        assert payload3["status"] == "blocked", f"Expected blocked, got: {payload3}"
        assert payload3["decision"] == "deny"
        assert payload3["reason_code"] == "denied_confirmation_replay"

    finally:
        proc.terminate()
        proc.wait(timeout=5)
