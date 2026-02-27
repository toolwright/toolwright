"""Tests for flow detection wiring into compile pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from toolwright.cli.compile import compile_capture_session
from toolwright.models.capture import CaptureSession, HttpExchange, HTTPMethod


def test_compile_wires_flow_detection(tmp_path: Path) -> None:
    """Compile with parent/child paths should produce enables/depends_on in tools.json."""
    session = CaptureSession(
        id="test-flow",
        name="Flow Test",
        source="manual",
        allowed_hosts=["api.example.com"],
        exchanges=[
            HttpExchange(
                url="https://api.example.com/posts",
                method=HTTPMethod.GET,
                host="api.example.com",
                path="/posts",
                response_status=200,
                response_body_json=[{"id": 1, "title": "Hello"}],
                response_content_type="application/json",
            ),
            HttpExchange(
                url="https://api.example.com/posts/1/comments",
                method=HTTPMethod.GET,
                host="api.example.com",
                path="/posts/1/comments",
                response_status=200,
                response_body_json=[{"id": 10, "body": "Nice"}],
                response_content_type="application/json",
            ),
        ],
    )

    result = compile_capture_session(
        session=session,
        scope_name="first_party_only",
        scope_file=None,
        output_format="manifest",
        output_dir=str(tmp_path),
        deterministic=True,
    )

    assert result.tools_path is not None
    tools = json.loads(result.tools_path.read_text())
    actions = tools["actions"]

    # Find the parent and child actions
    parent = next((a for a in actions if "posts" in a["path"] and "{" not in a["path"]), None)
    child = next((a for a in actions if "comments" in a["path"]), None)

    assert parent is not None, f"No parent action found in {[a['path'] for a in actions]}"
    assert child is not None, f"No child action found in {[a['path'] for a in actions]}"

    # Parent should enable child, child should depend on parent
    assert "enables" in parent, f"Parent {parent['name']} missing 'enables'"
    assert child["name"] in parent["enables"]
    assert "depends_on" in child, f"Child {child['name']} missing 'depends_on'"
    assert parent["name"] in child["depends_on"]
