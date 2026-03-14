"""Tests for flow metadata in compiled artifacts (Phase 3.2)."""

from __future__ import annotations

from toolwright.core.compile.tools import ToolManifestGenerator
from toolwright.models.endpoint import Endpoint, Parameter, ParameterLocation
from toolwright.models.flow import FlowEdge, FlowGraph


def _ep(
    method: str = "GET",
    path: str = "/api/v1/items",
    response_body_schema: dict | None = None,
    request_body_schema: dict | None = None,
    parameters: list[Parameter] | None = None,
    tags: list[str] | None = None,
) -> Endpoint:
    return Endpoint(
        method=method,
        path=path,
        host="api.example.com",
        url=f"https://api.example.com{path}",
        tags=tags or [],
        parameters=parameters or [],
        response_body_schema=response_body_schema,
        request_body_schema=request_body_schema,
    )


class TestFlowMetadataInActions:
    """Test that flow edges produce depends_on / enables in tool actions."""

    def test_enables_field_added(self):
        gen = ToolManifestGenerator()
        ep_list = _ep(
            method="GET",
            path="/api/v1/products",
            response_body_schema={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
            },
        )
        ep_detail = _ep(
            method="GET",
            path="/api/v1/products/{id}",
            parameters=[
                Parameter(name="id", location=ParameterLocation.PATH, required=True),
            ],
        )
        flow_graph = FlowGraph(edges=[
            FlowEdge(
                source_id=ep_list.signature_id,
                target_id=ep_detail.signature_id,
                linking_field="id",
                confidence=0.9,
            ),
        ])
        manifest = gen.generate([ep_list, ep_detail], flow_graph=flow_graph)
        actions = manifest["actions"]
        list_action = next(a for a in actions if "products" in a["path"] and "{id}" not in a["path"])
        detail_action = next(a for a in actions if "{id}" in a["path"])

        assert "enables" in list_action
        assert detail_action["name"] in list_action["enables"]

    def test_depends_on_field_added(self):
        gen = ToolManifestGenerator()
        ep_list = _ep(
            method="GET",
            path="/api/v1/products",
            response_body_schema={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
            },
        )
        ep_detail = _ep(
            method="GET",
            path="/api/v1/products/{id}",
            parameters=[
                Parameter(name="id", location=ParameterLocation.PATH, required=True),
            ],
        )
        flow_graph = FlowGraph(edges=[
            FlowEdge(
                source_id=ep_list.signature_id,
                target_id=ep_detail.signature_id,
                linking_field="id",
                confidence=0.9,
            ),
        ])
        manifest = gen.generate([ep_list, ep_detail], flow_graph=flow_graph)
        actions = manifest["actions"]
        detail_action = next(a for a in actions if "{id}" in a["path"])

        assert "depends_on" in detail_action
        list_action = next(a for a in actions if "products" in a["path"] and "{id}" not in a["path"])
        assert list_action["name"] in detail_action["depends_on"]

    def test_no_flow_graph_no_fields(self):
        """Without a flow graph, actions should not have depends_on/enables."""
        gen = ToolManifestGenerator()
        ep = _ep(method="GET", path="/api/v1/items")
        manifest = gen.generate([ep])
        action = manifest["actions"][0]
        assert "depends_on" not in action
        assert "enables" not in action

    def test_description_includes_dependency_hint(self):
        """Tool descriptions should mention dependencies when flow exists."""
        gen = ToolManifestGenerator()
        ep_list = _ep(
            method="GET",
            path="/api/v1/products",
            response_body_schema={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
            },
        )
        ep_detail = _ep(
            method="GET",
            path="/api/v1/products/{id}",
            parameters=[
                Parameter(name="id", location=ParameterLocation.PATH, required=True),
            ],
        )
        flow_graph = FlowGraph(edges=[
            FlowEdge(
                source_id=ep_list.signature_id,
                target_id=ep_detail.signature_id,
                linking_field="id",
                confidence=0.9,
            ),
        ])
        manifest = gen.generate([ep_list, ep_detail], flow_graph=flow_graph)
        detail_action = next(a for a in manifest["actions"] if "{id}" in a["path"])
        # Description should hint at the dependency
        assert "first" in detail_action["description"].lower() or "depends" in detail_action["description"].lower()

    def test_dependency_hints_capped_at_500_chars(self):
        """C1: descriptions must not grow unbounded from dependency hints."""
        gen = ToolManifestGenerator()
        # Create a target endpoint with an already-long description
        ep_target = _ep(
            method="GET",
            path="/api/v1/details/{id}",
            parameters=[
                Parameter(name="id", location=ParameterLocation.PATH, required=True),
            ],
        )
        # Create many source endpoints that link to target
        sources = []
        edges = []
        for i in range(20):
            src = _ep(
                method="GET",
                path=f"/api/v1/source_{i}",
                response_body_schema={
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                },
            )
            sources.append(src)
            edges.append(FlowEdge(
                source_id=src.signature_id,
                target_id=ep_target.signature_id,
                linking_field="id",
                confidence=0.9,
            ))
        flow_graph = FlowGraph(edges=edges)
        manifest = gen.generate(sources + [ep_target], flow_graph=flow_graph)
        detail_action = next(a for a in manifest["actions"] if "{id}" in a["path"])
        assert len(detail_action["description"]) <= 500
