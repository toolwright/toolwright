"""Tests for flow-aware drift detection (Phase 3.3)."""

from __future__ import annotations

from toolwright.core.drift.engine import DriftEngine
from toolwright.models.endpoint import Endpoint, Parameter
from toolwright.models.flow import FlowEdge, FlowGraph


def _ep(
    method: str = "GET",
    path: str = "/api/v1/items",
    host: str = "api.example.com",
    response_body_schema: dict | None = None,
    parameters: list[Parameter] | None = None,
) -> Endpoint:
    return Endpoint(
        method=method,
        path=path,
        host=host,
        url=f"https://{host}{path}",
        parameters=parameters or [],
        response_body_schema=response_body_schema,
    )


class TestFlowAwareDrift:
    """Test that removing an endpoint in a flow flags the entire flow."""

    def test_removing_flow_source_flags_flow(self):
        """If products is removed and orders depends on it, flag the flow."""
        engine = DriftEngine()
        ep_products = _ep(
            method="GET",
            path="/api/v1/products",
            response_body_schema={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
            },
        )
        ep_orders = _ep(
            method="POST",
            path="/api/v1/orders",
        )
        flow_graph = FlowGraph(edges=[
            FlowEdge(
                source_id=ep_products.signature_id,
                target_id=ep_orders.signature_id,
                linking_field="id",
                confidence=0.9,
            ),
        ])

        # Baseline has both, new only has orders (products removed)
        report = engine.compare(
            from_endpoints=[ep_products, ep_orders],
            to_endpoints=[ep_orders],
            deterministic=True,
            flow_graph=flow_graph,
        )

        # Should have a flow-related drift item
        flow_drifts = [d for d in report.drifts if "flow" in d.title.lower() or "flow" in d.description.lower()]
        assert len(flow_drifts) >= 1

    def test_removing_flow_target_flags_flow(self):
        """If orders is removed and products enables it, flag the flow."""
        engine = DriftEngine()
        ep_products = _ep(
            method="GET",
            path="/api/v1/products",
        )
        ep_orders = _ep(
            method="POST",
            path="/api/v1/orders",
        )
        flow_graph = FlowGraph(edges=[
            FlowEdge(
                source_id=ep_products.signature_id,
                target_id=ep_orders.signature_id,
                linking_field="id",
                confidence=0.9,
            ),
        ])

        report = engine.compare(
            from_endpoints=[ep_products, ep_orders],
            to_endpoints=[ep_products],
            deterministic=True,
            flow_graph=flow_graph,
        )

        flow_drifts = [d for d in report.drifts if "flow" in d.title.lower() or "flow" in d.description.lower()]
        assert len(flow_drifts) >= 1

    def test_no_flow_no_extra_drifts(self):
        """Without a flow graph, removing an endpoint should not produce flow drifts."""
        engine = DriftEngine()
        ep = _ep(method="GET", path="/api/v1/items")

        report = engine.compare(
            from_endpoints=[ep],
            to_endpoints=[],
            deterministic=True,
        )

        flow_drifts = [d for d in report.drifts if "flow" in d.title.lower()]
        assert len(flow_drifts) == 0

    def test_flow_drift_severity(self):
        """Flow-broken drifts should be at least WARNING severity."""
        engine = DriftEngine()
        ep_a = _ep(method="GET", path="/api/v1/a")
        ep_b = _ep(method="GET", path="/api/v1/b")
        flow_graph = FlowGraph(edges=[
            FlowEdge(source_id=ep_a.signature_id, target_id=ep_b.signature_id,
                      linking_field="id", confidence=0.9),
        ])

        report = engine.compare(
            from_endpoints=[ep_a, ep_b],
            to_endpoints=[ep_b],
            deterministic=True,
            flow_graph=flow_graph,
        )

        flow_drifts = [d for d in report.drifts if "flow" in d.title.lower()]
        for d in flow_drifts:
            assert d.severity.value in ("warning", "error", "critical")
