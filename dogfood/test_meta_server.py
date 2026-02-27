#!/usr/bin/env python3
"""Dogfood test: exercise the Toolwright meta-server (inspect command) over MCP stdio.

This script spawns `toolwright inspect` as a subprocess, sends JSON-RPC 2.0
messages on its stdin, and reads responses from its stdout.  It tests every
meta-tool exposed by the four pillars: GOVERN, HEAL, KILL, CORRECT.

Usage:
    .venv/bin/python dogfood/test_meta_server.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python3"
TOOLWRIGHT = PROJECT_ROOT / ".venv" / "bin" / "toolwright"

# Test artifacts (GitHub dogfood set - has tools + policy + lockfile)
TOOLS_JSON = PROJECT_ROOT / "dogfood" / "github" / "artifact" / "tools.json"
POLICY_YAML = PROJECT_ROOT / "dogfood" / "github" / "artifact" / "policy.yaml"
LOCKFILE_YAML = PROJECT_ROOT / "dogfood" / "github" / "lockfile" / "toolwright.lock.yaml"


# ---------------------------------------------------------------------------
# MCP JSON-RPC helpers
# ---------------------------------------------------------------------------
def make_jsonrpc(method: str, params: dict | None = None, id: int = 1) -> str:
    """Build a JSON-RPC 2.0 request string."""
    msg: dict = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg)


def send_and_recv(proc: subprocess.Popen, message: str, timeout: float = 10.0) -> dict | None:
    """Send a JSON-RPC message and read the response line."""
    assert proc.stdin is not None
    assert proc.stdout is not None

    proc.stdin.write(message + "\n")
    proc.stdin.flush()

    # Read response - the MCP server writes JSON-RPC responses as lines on stdout
    start = time.time()
    while time.time() - start < timeout:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.05)
            continue
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            # Might be log output, skip
            continue
    return None


def pp(label: str, obj: dict | None) -> None:
    """Pretty-print a result."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    if obj is None:
        print("  (no response / timeout)")
    else:
        print(json.dumps(obj, indent=2))


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------
def main() -> int:
    results: list[dict] = []
    passed = 0
    failed = 0

    # Create temp files for circuit-breaker and rules so KILL/CORRECT pillars work
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as cb_f:
        json.dump({}, cb_f)
        cb_path = cb_f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as rules_f:
        json.dump([], rules_f)  # RuleEngine expects a bare JSON array
        rules_path = rules_f.name

    # -----------------------------------------------------------------------
    # 1) Startup test: spawn the meta-server
    # -----------------------------------------------------------------------
    print("\n[1] Starting meta-server via `toolwright inspect` ...")
    cmd = [
        str(TOOLWRIGHT), "inspect",
        "--tools", str(TOOLS_JSON),
        "--policy", str(POLICY_YAML),
        "--lockfile", str(LOCKFILE_YAML),
        "--circuit-breaker-path", cb_path,
        "--rules-path", rules_path,
    ]
    print(f"    cmd: {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    # Give the server a moment to start
    time.sleep(1.0)

    # Check if process is still running
    if proc.poll() is not None:
        stderr_out = proc.stderr.read() if proc.stderr else ""
        print(f"  ERROR: meta-server exited immediately with code {proc.returncode}")
        print(f"  stderr: {stderr_out}")
        return 1

    print("  meta-server is running (PID={})".format(proc.pid))

    # -----------------------------------------------------------------------
    # 2) MCP Initialize
    # -----------------------------------------------------------------------
    print("\n[2] Sending MCP initialize ...")
    init_msg = make_jsonrpc("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "dogfood-test", "version": "0.1"},
    }, id=1)
    resp = send_and_recv(proc, init_msg)
    pp("initialize response", resp)

    if resp and "result" in resp:
        print("  PASS: initialize succeeded")
        passed += 1
        results.append({"test": "initialize", "status": "PASS"})

        # Send initialized notification
        notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert proc.stdin is not None
        proc.stdin.write(notif + "\n")
        proc.stdin.flush()
        time.sleep(0.3)
    else:
        print("  FAIL: initialize did not return result")
        failed += 1
        results.append({"test": "initialize", "status": "FAIL", "response": resp})

    # -----------------------------------------------------------------------
    # 3) tools/list - enumerate all meta-tools
    # -----------------------------------------------------------------------
    print("\n[3] Calling tools/list ...")
    list_msg = make_jsonrpc("tools/list", {}, id=2)
    resp = send_and_recv(proc, list_msg)
    pp("tools/list response", resp)

    tool_names = []
    if resp and "result" in resp:
        tools = resp["result"].get("tools", [])
        tool_names = [t["name"] for t in tools]
        print(f"  Found {len(tool_names)} meta-tools: {tool_names}")
        passed += 1
        results.append({"test": "tools/list", "status": "PASS", "tools": tool_names})
    else:
        print("  FAIL: tools/list did not return result")
        failed += 1
        results.append({"test": "tools/list", "status": "FAIL", "response": resp})

    # -----------------------------------------------------------------------
    # Helper to call a tool
    # -----------------------------------------------------------------------
    call_id = 10

    def call_tool(name: str, arguments: dict | None = None) -> dict | None:
        nonlocal call_id
        call_id += 1
        msg = make_jsonrpc("tools/call", {
            "name": name,
            "arguments": arguments or {},
        }, id=call_id)
        return send_and_recv(proc, msg)

    # -----------------------------------------------------------------------
    # 4) GOVERN pillar tests
    # -----------------------------------------------------------------------
    print("\n" + "="*60)
    print("  GOVERN PILLAR TESTS")
    print("="*60)

    # 4a) toolwright_list_actions
    print("\n[4a] toolwright_list_actions (no filter) ...")
    resp = call_tool("toolwright_list_actions")
    pp("list_actions", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            print(f"  Total actions: {data.get('total', '?')}")
            passed += 1
            results.append({"test": "list_actions", "status": "PASS", "total": data.get("total")})
        else:
            print("  FAIL: empty content")
            failed += 1
            results.append({"test": "list_actions", "status": "FAIL"})
    else:
        print("  FAIL: no result")
        failed += 1
        results.append({"test": "list_actions", "status": "FAIL", "response": resp})

    # 4b) toolwright_list_actions with risk filter
    print("\n[4b] toolwright_list_actions (filter_risk=high) ...")
    resp = call_tool("toolwright_list_actions", {"filter_risk": "high"})
    pp("list_actions (high risk)", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            print(f"  High-risk actions: {data.get('total', '?')}")
            passed += 1
            results.append({"test": "list_actions_high", "status": "PASS", "total": data.get("total")})
        else:
            failed += 1
            results.append({"test": "list_actions_high", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "list_actions_high", "status": "FAIL"})

    # 4c) toolwright_check_policy - GET action (should be allowed)
    print("\n[4c] toolwright_check_policy (get_repo) ...")
    resp = call_tool("toolwright_check_policy", {"action_name": "get_repo"})
    pp("check_policy (get_repo)", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            print(f"  Allowed: {data.get('allowed')}, Reason: {data.get('reason')}")
            passed += 1
            results.append({"test": "check_policy_get", "status": "PASS", "data": data})
        else:
            failed += 1
            results.append({"test": "check_policy_get", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "check_policy_get", "status": "FAIL"})

    # 4d) toolwright_check_policy - DELETE action (should require confirmation)
    print("\n[4d] toolwright_check_policy (delete_repo) ...")
    resp = call_tool("toolwright_check_policy", {"action_name": "delete_repo"})
    pp("check_policy (delete_repo)", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            print(f"  Allowed: {data.get('allowed')}, Requires confirmation: {data.get('requires_confirmation')}")
            passed += 1
            results.append({"test": "check_policy_delete", "status": "PASS", "data": data})
        else:
            failed += 1
            results.append({"test": "check_policy_delete", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "check_policy_delete", "status": "FAIL"})

    # 4e) toolwright_check_policy - non-existent action
    print("\n[4e] toolwright_check_policy (nonexistent_action) ...")
    resp = call_tool("toolwright_check_policy", {"action_name": "nonexistent_action"})
    pp("check_policy (nonexistent)", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            if "error" in data:
                print(f"  Correctly returned error: {data['error']}")
                passed += 1
                results.append({"test": "check_policy_notfound", "status": "PASS"})
            else:
                failed += 1
                results.append({"test": "check_policy_notfound", "status": "FAIL"})
        else:
            failed += 1
            results.append({"test": "check_policy_notfound", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "check_policy_notfound", "status": "FAIL"})

    # 4f) toolwright_get_approval_status
    print("\n[4f] toolwright_get_approval_status (get_repo) ...")
    resp = call_tool("toolwright_get_approval_status", {"action_name": "get_repo"})
    pp("get_approval_status (get_repo)", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            print(f"  Status: {data.get('status')}")
            passed += 1
            results.append({"test": "approval_status", "status": "PASS", "data": data})
        else:
            failed += 1
            results.append({"test": "approval_status", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "approval_status", "status": "FAIL"})

    # 4g) toolwright_list_pending_approvals
    print("\n[4g] toolwright_list_pending_approvals ...")
    resp = call_tool("toolwright_list_pending_approvals")
    pp("list_pending_approvals", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            print(f"  Pending: {data.get('total_pending', '?')}")
            passed += 1
            results.append({"test": "pending_approvals", "status": "PASS", "data": data})
        else:
            failed += 1
            results.append({"test": "pending_approvals", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "pending_approvals", "status": "FAIL"})

    # 4h) toolwright_get_action_details
    print("\n[4h] toolwright_get_action_details (get_repo) ...")
    resp = call_tool("toolwright_get_action_details", {"action_name": "get_repo"})
    pp("get_action_details (get_repo)", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            print(f"  Method: {data.get('method')}, Path: {data.get('path')}, Risk: {data.get('risk_tier')}")
            passed += 1
            results.append({"test": "action_details", "status": "PASS", "data": data})
        else:
            failed += 1
            results.append({"test": "action_details", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "action_details", "status": "FAIL"})

    # 4i) toolwright_risk_summary
    print("\n[4i] toolwright_risk_summary ...")
    resp = call_tool("toolwright_risk_summary")
    pp("risk_summary", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            print(f"  Total actions: {data.get('total_actions')}")
            by_risk = data.get("by_risk_tier", {})
            for tier in ["low", "medium", "high", "critical"]:
                info = by_risk.get(tier, {})
                print(f"    {tier}: {info.get('count', 0)} actions")
            passed += 1
            results.append({"test": "risk_summary", "status": "PASS", "data": data})
        else:
            failed += 1
            results.append({"test": "risk_summary", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "risk_summary", "status": "FAIL"})

    # 4j) toolwright_get_flows
    print("\n[4j] toolwright_get_flows ...")
    resp = call_tool("toolwright_get_flows")
    pp("get_flows", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            print(f"  Actions with flows: {data.get('total_actions_with_flows', 0)}")
            passed += 1
            results.append({"test": "get_flows", "status": "PASS", "data": data})
        else:
            failed += 1
            results.append({"test": "get_flows", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "get_flows", "status": "FAIL"})

    # -----------------------------------------------------------------------
    # 5) HEAL pillar tests
    # -----------------------------------------------------------------------
    print("\n" + "="*60)
    print("  HEAL PILLAR TESTS")
    print("="*60)

    # 5a) toolwright_health_check - existing tool
    print("\n[5a] toolwright_health_check (get_repo) ...")
    resp = call_tool("toolwright_health_check", {"tool_id": "get_repo"})
    pp("health_check (get_repo)", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            print(f"  Exists: {data.get('exists')}, Approved: {data.get('approved')}, Healthy: {data.get('healthy')}")
            passed += 1
            results.append({"test": "health_check", "status": "PASS", "data": data})
        else:
            failed += 1
            results.append({"test": "health_check", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "health_check", "status": "FAIL"})

    # 5b) toolwright_diagnose_tool - existing tool
    print("\n[5b] toolwright_diagnose_tool (get_repo) ...")
    resp = call_tool("toolwright_diagnose_tool", {"tool_id": "get_repo"})
    pp("diagnose_tool (get_repo)", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            print(f"  Healthy: {data.get('healthy')}, Issues: {data.get('issues')}")
            passed += 1
            results.append({"test": "diagnose_tool", "status": "PASS", "data": data})
        else:
            failed += 1
            results.append({"test": "diagnose_tool", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "diagnose_tool", "status": "FAIL"})

    # 5c) toolwright_diagnose_tool - nonexistent tool
    print("\n[5c] toolwright_diagnose_tool (nonexistent_tool) ...")
    resp = call_tool("toolwright_diagnose_tool", {"tool_id": "nonexistent_tool"})
    pp("diagnose_tool (nonexistent)", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            if not data.get("healthy", True):
                print(f"  Correctly unhealthy: issues={data.get('issues')}")
                passed += 1
                results.append({"test": "diagnose_notfound", "status": "PASS"})
            else:
                failed += 1
                results.append({"test": "diagnose_notfound", "status": "FAIL"})
        else:
            failed += 1
            results.append({"test": "diagnose_notfound", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "diagnose_notfound", "status": "FAIL"})

    # -----------------------------------------------------------------------
    # 6) KILL pillar tests
    # -----------------------------------------------------------------------
    print("\n" + "="*60)
    print("  KILL PILLAR TESTS")
    print("="*60)

    # 6a) toolwright_quarantine_report (should be empty initially)
    print("\n[6a] toolwright_quarantine_report (initial, should be empty) ...")
    resp = call_tool("toolwright_quarantine_report")
    pp("quarantine_report (initial)", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            print(f"  Total quarantined: {data.get('total', '?')}")
            passed += 1
            results.append({"test": "quarantine_initial", "status": "PASS", "data": data})
        else:
            failed += 1
            results.append({"test": "quarantine_initial", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "quarantine_initial", "status": "FAIL"})

    # 6b) toolwright_kill_tool
    print("\n[6b] toolwright_kill_tool (get_repo, reason='dogfood test') ...")
    resp = call_tool("toolwright_kill_tool", {"tool_id": "get_repo", "reason": "dogfood test"})
    pp("kill_tool", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            if data.get("state") == "open":
                print("  PASS: tool killed (circuit breaker open)")
                passed += 1
                results.append({"test": "kill_tool", "status": "PASS"})
            else:
                failed += 1
                results.append({"test": "kill_tool", "status": "FAIL", "data": data})
        else:
            failed += 1
            results.append({"test": "kill_tool", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "kill_tool", "status": "FAIL"})

    # 6c) toolwright_quarantine_report (should now have get_repo)
    print("\n[6c] toolwright_quarantine_report (after kill) ...")
    resp = call_tool("toolwright_quarantine_report")
    pp("quarantine_report (after kill)", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            print(f"  Total quarantined: {data.get('total', '?')}")
            tools = data.get("tools", [])
            if any(t.get("tool_id") == "get_repo" for t in tools):
                print("  PASS: get_repo is in quarantine")
                passed += 1
                results.append({"test": "quarantine_after_kill", "status": "PASS"})
            else:
                print("  FAIL: get_repo not found in quarantine")
                failed += 1
                results.append({"test": "quarantine_after_kill", "status": "FAIL", "data": data})
        else:
            failed += 1
            results.append({"test": "quarantine_after_kill", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "quarantine_after_kill", "status": "FAIL"})

    # 6d) toolwright_enable_tool
    print("\n[6d] toolwright_enable_tool (get_repo) ...")
    resp = call_tool("toolwright_enable_tool", {"tool_id": "get_repo"})
    pp("enable_tool", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            if data.get("state") == "closed":
                print("  PASS: tool re-enabled (circuit breaker closed)")
                passed += 1
                results.append({"test": "enable_tool", "status": "PASS"})
            else:
                failed += 1
                results.append({"test": "enable_tool", "status": "FAIL", "data": data})
        else:
            failed += 1
            results.append({"test": "enable_tool", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "enable_tool", "status": "FAIL"})

    # -----------------------------------------------------------------------
    # 7) CORRECT pillar tests
    # -----------------------------------------------------------------------
    print("\n" + "="*60)
    print("  CORRECT PILLAR TESTS")
    print("="*60)

    # 7a) toolwright_list_rules (should be empty initially)
    print("\n[7a] toolwright_list_rules (initial, should be empty) ...")
    resp = call_tool("toolwright_list_rules")
    pp("list_rules (initial)", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            print(f"  Total rules: {data.get('total', '?')}")
            passed += 1
            results.append({"test": "list_rules_initial", "status": "PASS", "data": data})
        else:
            failed += 1
            results.append({"test": "list_rules_initial", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "list_rules_initial", "status": "FAIL"})

    # 7b) toolwright_add_rule
    print("\n[7b] toolwright_add_rule (prerequisite) ...")
    resp = call_tool("toolwright_add_rule", {
        "kind": "prerequisite",
        "target_tool_id": "delete_repo",
        "description": "Must call get_repo before delete_repo",
        "required_tool_ids": ["get_repo"],
    })
    pp("add_rule", resp)
    added_rule_id = None
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            added_rule_id = data.get("rule_id")
            print(f"  Rule ID: {added_rule_id}")
            passed += 1
            results.append({"test": "add_rule", "status": "PASS", "rule_id": added_rule_id})
        else:
            failed += 1
            results.append({"test": "add_rule", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "add_rule", "status": "FAIL"})

    # 7c) toolwright_list_rules (should now have 1 rule)
    print("\n[7c] toolwright_list_rules (after add) ...")
    resp = call_tool("toolwright_list_rules")
    pp("list_rules (after add)", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            total = data.get("total", 0)
            print(f"  Total rules: {total}")
            if total >= 1:
                passed += 1
                results.append({"test": "list_rules_after_add", "status": "PASS"})
            else:
                failed += 1
                results.append({"test": "list_rules_after_add", "status": "FAIL"})
        else:
            failed += 1
            results.append({"test": "list_rules_after_add", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "list_rules_after_add", "status": "FAIL"})

    # 7d) toolwright_remove_rule
    if added_rule_id:
        print(f"\n[7d] toolwright_remove_rule ({added_rule_id}) ...")
        resp = call_tool("toolwright_remove_rule", {"rule_id": added_rule_id})
        pp("remove_rule", resp)
        if resp and "result" in resp:
            content = resp["result"].get("content", [])
            if content:
                data = json.loads(content[0].get("text", "{}"))
                if data.get("removed"):
                    print("  PASS: rule removed")
                    passed += 1
                    results.append({"test": "remove_rule", "status": "PASS"})
                else:
                    failed += 1
                    results.append({"test": "remove_rule", "status": "FAIL", "data": data})
            else:
                failed += 1
                results.append({"test": "remove_rule", "status": "FAIL"})
        else:
            failed += 1
            results.append({"test": "remove_rule", "status": "FAIL"})
    else:
        print("\n[7d] SKIP: no rule_id from add_rule")
        results.append({"test": "remove_rule", "status": "SKIP"})

    # 7e) toolwright_add_rule with prohibition kind
    print("\n[7e] toolwright_add_rule (prohibition) ...")
    resp = call_tool("toolwright_add_rule", {
        "kind": "prohibition",
        "target_tool_id": "delete_repo",
        "description": "Never call delete_repo in production",
    })
    pp("add_rule (prohibition)", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            if data.get("kind") == "prohibition":
                print("  PASS: prohibition rule added")
                passed += 1
                results.append({"test": "add_prohibition", "status": "PASS"})
            else:
                failed += 1
                results.append({"test": "add_prohibition", "status": "FAIL"})
        else:
            failed += 1
            results.append({"test": "add_prohibition", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "add_prohibition", "status": "FAIL"})

    # -----------------------------------------------------------------------
    # 8) Edge case: call unknown tool
    # -----------------------------------------------------------------------
    print("\n" + "="*60)
    print("  EDGE CASE TESTS")
    print("="*60)

    print("\n[8] Calling unknown tool ...")
    resp = call_tool("toolwright_nonexistent_tool")
    pp("unknown tool", resp)
    if resp and "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            data = json.loads(content[0].get("text", "{}"))
            if "error" in data:
                print(f"  PASS: correctly returned error: {data['error']}")
                passed += 1
                results.append({"test": "unknown_tool", "status": "PASS"})
            else:
                failed += 1
                results.append({"test": "unknown_tool", "status": "FAIL"})
        else:
            failed += 1
            results.append({"test": "unknown_tool", "status": "FAIL"})
    else:
        failed += 1
        results.append({"test": "unknown_tool", "status": "FAIL"})

    # -----------------------------------------------------------------------
    # Cleanup
    # -----------------------------------------------------------------------
    proc.terminate()
    proc.wait(timeout=5)

    # Clean up temp files
    Path(cb_path).unlink(missing_ok=True)
    Path(rules_path).unlink(missing_ok=True)

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    total = passed + failed
    print("\n" + "="*60)
    print(f"  DOGFOOD RESULTS: {passed}/{total} passed, {failed} failed")
    print("="*60)

    for r in results:
        status = r["status"]
        marker = "PASS" if status == "PASS" else ("SKIP" if status == "SKIP" else "FAIL")
        print(f"  [{marker}] {r['test']}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
