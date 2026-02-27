"""Tests for inspect MCP read-only tooling and compliance reporting."""

from __future__ import annotations

import json


class TestMetaServerReadOnlyTools:
    """`mcp inspect` must remain introspection-only."""

    def test_meta_server_does_not_expose_helper_mutation_methods(self):
        from toolwright.mcp.meta_server import ToolwrightMetaMCPServer

        server = ToolwrightMetaMCPServer()
        assert not hasattr(server, "_capture_har")
        assert not hasattr(server, "_compile_capture")
        assert not hasattr(server, "_drift_check")


class TestComplianceReport:
    """Test EU AI Act compliance report generation."""

    def test_compliance_report_generates(self):
        from toolwright.core.compliance.report import ComplianceReporter

        reporter = ComplianceReporter()
        report = reporter.generate(
            tools_manifest={
                "actions": [
                    {"name": "get_products", "risk_tier": "safe", "method": "GET"},
                    {"name": "create_order", "risk_tier": "high", "method": "POST"},
                ],
            },
            approval_history=[
                {"action": "get_products", "status": "approved", "by": "human"},
                {"action": "create_order", "status": "approved", "by": "human"},
            ],
            drift_history=[],
        )
        assert "human_oversight" in report
        assert "tool_inventory" in report
        assert "risk_management" in report

    def test_compliance_report_counts_risk_tiers(self):
        from toolwright.core.compliance.report import ComplianceReporter

        reporter = ComplianceReporter()
        report = reporter.generate(
            tools_manifest={
                "actions": [
                    {"name": "a", "risk_tier": "safe", "method": "GET"},
                    {"name": "b", "risk_tier": "high", "method": "POST"},
                    {"name": "c", "risk_tier": "critical", "method": "DELETE"},
                ],
            },
        )
        risk = report["risk_management"]
        assert risk["by_tier"]["safe"] == 1
        assert risk["by_tier"]["high"] == 1
        assert risk["by_tier"]["critical"] == 1

    def test_compliance_report_human_oversight(self):
        from toolwright.core.compliance.report import ComplianceReporter

        reporter = ComplianceReporter()
        report = reporter.generate(
            tools_manifest={"actions": []},
            approval_history=[
                {"action": "x", "status": "approved", "by": "admin@corp.com"},
            ],
        )
        oversight = report["human_oversight"]
        assert oversight["approval_count"] == 1

    def test_compliance_report_json_serializable(self):
        from toolwright.core.compliance.report import ComplianceReporter

        reporter = ComplianceReporter()
        report = reporter.generate(
            tools_manifest={"actions": [{"name": "a", "risk_tier": "low", "method": "GET"}]},
        )
        # Should be JSON-serializable
        serialized = json.dumps(report)
        assert serialized
