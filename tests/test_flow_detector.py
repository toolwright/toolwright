"""Tests for the flow detection engine (Phase 3.1)."""

from __future__ import annotations

from toolwright.core.normalize.flow_detector import FlowDetector
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


class TestFlowDetectorExactMatch:
    """Test flow detection from exact field name matches."""

    def test_response_field_matches_path_param(self):
        """If GET /products returns {id}, and GET /products/{product_id} needs product_id, detect flow."""
        detector = FlowDetector()
        ep_list = _ep(
            method="GET",
            path="/api/v1/products",
            response_body_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                },
            },
        )
        ep_detail = _ep(
            method="GET",
            path="/api/v1/products/{id}",
            parameters=[
                Parameter(name="id", location=ParameterLocation.PATH, required=True),
            ],
        )
        graph = detector.detect([ep_list, ep_detail])
        assert isinstance(graph, FlowGraph)
        assert len(graph.edges) >= 1
        edge = graph.edges[0]
        assert edge.source_id == ep_list.signature_id
        assert edge.target_id == ep_detail.signature_id
        assert edge.linking_field == "id"

    def test_response_field_matches_request_body(self):
        """If GET /users returns {id}, and POST /orders body needs user_id, detect flow."""
        detector = FlowDetector()
        ep_users = _ep(
            method="GET",
            path="/api/v1/users",
            response_body_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                },
            },
        )
        ep_orders = _ep(
            method="POST",
            path="/api/v1/orders",
            request_body_schema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer"},
                    "product_id": {"type": "integer"},
                },
            },
        )
        graph = detector.detect([ep_users, ep_orders])
        # Should detect user_id suffix match to users.id
        edges_from_users = [e for e in graph.edges if e.source_id == ep_users.signature_id]
        assert len(edges_from_users) >= 1

    def test_no_self_edges(self):
        """An endpoint should not link to itself."""
        detector = FlowDetector()
        ep = _ep(
            method="GET",
            path="/api/v1/items",
            response_body_schema={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
            },
            parameters=[
                Parameter(name="id", location=ParameterLocation.QUERY),
            ],
        )
        graph = detector.detect([ep])
        assert len(graph.edges) == 0


class TestFlowDetectorSuffixMatch:
    """Test flow detection from suffix matches like id -> product_id."""

    def test_suffix_match_product_id(self):
        detector = FlowDetector()
        ep_products = _ep(
            method="GET",
            path="/api/v1/products",
            response_body_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                },
            },
        )
        ep_cart = _ep(
            method="POST",
            path="/api/v1/cart",
            request_body_schema={
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer"},
                    "quantity": {"type": "integer"},
                },
            },
        )
        graph = detector.detect([ep_products, ep_cart])
        edges = [e for e in graph.edges if e.source_id == ep_products.signature_id]
        assert len(edges) >= 1
        assert any(e.linking_field in ("id", "product_id") for e in edges)

    def test_suffix_match_confidence(self):
        """Suffix matches should have lower confidence than exact matches."""
        detector = FlowDetector()
        ep_source = _ep(
            method="GET",
            path="/api/v1/items",
            response_body_schema={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
            },
        )
        ep_exact = _ep(
            method="GET",
            path="/api/v1/items/{id}",
            parameters=[
                Parameter(name="id", location=ParameterLocation.PATH, required=True),
            ],
        )
        ep_suffix = _ep(
            method="POST",
            path="/api/v1/orders",
            request_body_schema={
                "type": "object",
                "properties": {"item_id": {"type": "integer"}},
            },
        )
        graph = detector.detect([ep_source, ep_exact, ep_suffix])
        exact_edges = [
            e for e in graph.edges
            if e.target_id == ep_exact.signature_id
        ]
        suffix_edges = [
            e for e in graph.edges
            if e.target_id == ep_suffix.signature_id
        ]
        if exact_edges and suffix_edges:
            assert exact_edges[0].confidence >= suffix_edges[0].confidence


class TestFlowDetectorNoFalsePositives:
    """Avoid spurious edges."""

    def test_generic_fields_ignored(self):
        """Common fields like 'type', 'status', 'created_at' should not produce edges."""
        detector = FlowDetector()
        ep1 = _ep(
            method="GET",
            path="/api/v1/items",
            response_body_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "type": {"type": "string"},
                    "status": {"type": "string"},
                    "created_at": {"type": "string"},
                },
            },
        )
        ep2 = _ep(
            method="GET",
            path="/api/v1/orders",
            parameters=[
                Parameter(name="status", location=ParameterLocation.QUERY),
            ],
        )
        graph = detector.detect([ep1, ep2])
        # 'status' should not produce a flow edge
        status_edges = [e for e in graph.edges if e.linking_field == "status"]
        assert len(status_edges) == 0


class TestFlowGraph:
    """Test FlowGraph model methods."""

    def test_edges_from(self):
        graph = FlowGraph(edges=[
            FlowEdge(source_id="a", target_id="b", linking_field="id", confidence=0.9),
            FlowEdge(source_id="a", target_id="c", linking_field="id", confidence=0.7),
            FlowEdge(source_id="b", target_id="c", linking_field="ref", confidence=0.8),
        ])
        assert len(graph.edges_from("a")) == 2
        assert len(graph.edges_from("b")) == 1
        assert len(graph.edges_from("x")) == 0

    def test_edges_to(self):
        graph = FlowGraph(edges=[
            FlowEdge(source_id="a", target_id="c", linking_field="id", confidence=0.9),
            FlowEdge(source_id="b", target_id="c", linking_field="ref", confidence=0.8),
        ])
        assert len(graph.edges_to("c")) == 2
        assert len(graph.edges_to("a")) == 0


class TestFlowSequences:
    """Test flow sequence extraction from graphs."""

    def test_detect_returns_sequences(self):
        """A chain A -> B -> C should produce a sequence."""
        detector = FlowDetector()
        ep_a = _ep(
            method="GET",
            path="/api/v1/products",
            response_body_schema={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
            },
        )
        ep_b = _ep(
            method="POST",
            path="/api/v1/cart",
            parameters=[
                Parameter(name="product_id", location=ParameterLocation.BODY),
            ],
            request_body_schema={
                "type": "object",
                "properties": {"product_id": {"type": "integer"}},
            },
            response_body_schema={
                "type": "object",
                "properties": {"cart_id": {"type": "string"}},
            },
        )
        ep_c = _ep(
            method="POST",
            path="/api/v1/checkout",
            request_body_schema={
                "type": "object",
                "properties": {"cart_id": {"type": "string"}},
            },
        )
        graph = detector.detect([ep_a, ep_b, ep_c])
        sequences = graph.find_sequences()
        assert len(sequences) >= 1
        # The longest sequence should have at least 2 steps
        longest = max(sequences, key=lambda s: len(s.steps))
        assert len(longest.steps) >= 2
