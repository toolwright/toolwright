"""Tests for mint orchestration."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import yaml
from click.testing import CliRunner

from toolwright.cli.approve import ApprovalSyncResult
from toolwright.cli.compile import CompileResult
from toolwright.cli.main import cli
from toolwright.cli.mint import build_mcp_config_snippet, run_mint
from toolwright.models.capture import CaptureSession, CaptureSource, HttpExchange, HTTPMethod
from toolwright.models.scope import Scope


def _write_artifact_fixture(tmp_path: Path) -> Path:
    artifact_dir = tmp_path / "artifacts" / "art_demo"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "tools.json").write_text(
        '{"version":"1.0.0","schema_version":"1.0","actions":[]}'
    )
    (artifact_dir / "toolsets.yaml").write_text(
        "version: '1.0.0'\nschema_version: '1.0'\ntoolsets: {readonly: {actions: []}}\n"
    )
    (artifact_dir / "policy.yaml").write_text(
        "version: '1.0.0'\nschema_version: '1.0'\nname: Demo\ndefault_action: allow\nrules: []\n"
    )
    (artifact_dir / "baseline.json").write_text("{}")
    (artifact_dir / "coverage_report.json").write_text(
        '{"version":"1.0.0","schema_version":"1.0","kind":"coverage_report","metrics":{"precision":1.0,"recall":1.0}}'
    )
    (artifact_dir / "contracts.yaml").write_text("version: '1.0.0'\nkind: contracts\n")
    (artifact_dir / "contract.yaml").write_text("openapi: 3.1.0\n")
    (artifact_dir / "contract.json").write_text('{"openapi":"3.1.0"}')
    return artifact_dir


class TestMint:
    def test_run_mint_creates_toolpack(self, tmp_path: Path, capsys) -> None:
        artifact_dir = _write_artifact_fixture(tmp_path)
        session = CaptureSession(
            id="cap_demo",
            name="Demo Capture",
            source=CaptureSource.PLAYWRIGHT,
            allowed_hosts=["api.example.com"],
            created_at=datetime(2026, 2, 5, tzinfo=UTC),
            exchanges=[
                HttpExchange(
                    url="https://api.example.com/users",
                    method=HTTPMethod.GET,
                    host="api.example.com",
                    path="/users",
                )
            ],
        )

        compile_result = CompileResult(
            artifact_id="art_demo",
            output_path=artifact_dir,
            scope=Scope(name="agent_safe_readonly"),
            endpoint_count=1,
            generated_at=session.created_at,
            artifacts_created=(
                ("Tool Manifest", artifact_dir / "tools.json"),
                ("Toolsets", artifact_dir / "toolsets.yaml"),
                ("Policy", artifact_dir / "policy.yaml"),
                ("Baseline", artifact_dir / "baseline.json"),
            ),
            tools_path=artifact_dir / "tools.json",
            toolsets_path=artifact_dir / "toolsets.yaml",
            policy_path=artifact_dir / "policy.yaml",
            baseline_path=artifact_dir / "baseline.json",
            contracts_path=artifact_dir / "contracts.yaml",
            contract_yaml_path=artifact_dir / "contract.yaml",
            contract_json_path=artifact_dir / "contract.json",
        )

        capture_calls: dict[str, object] = {}

        class FakePlaywrightCapture:
            def __init__(self, allowed_hosts: list[str], headless: bool = False, storage_state_path: str | None = None) -> None:
                capture_calls["allowed_hosts"] = allowed_hosts
                capture_calls["headless"] = headless
                capture_calls["storage_state_path"] = storage_state_path

            async def capture(self, **kwargs):
                capture_calls["capture_kwargs"] = kwargs
                return session

        with patch(
            "toolwright.core.capture.playwright_capture.PlaywrightCapture",
            FakePlaywrightCapture,
        ), patch(
            "toolwright.cli.mint.compile_capture_session",
            return_value=compile_result,
        ), patch(
            "toolwright.cli.mint.sync_lockfile",
            return_value=ApprovalSyncResult(
                lockfile_path=tmp_path / "dummy.lock.yaml",
                artifacts_digest="abc123",
                changes={"new": [], "modified": [], "removed": [], "unchanged": []},
                has_pending=True,
                pending_count=2,
            ),
        ) as mock_sync:
            run_mint(
                start_url="https://app.example.com",
                allowed_hosts=["api.example.com"],
                name="Demo",
                scope_name="agent_safe_readonly",
                headless=True,
                script_path=None,
                duration_seconds=30,
                output_root=str(tmp_path),
                deterministic=True,
                print_mcp_config=True,
                verbose=False,
            )

        out = capsys.readouterr().out
        assert "Mint complete:" in out
        assert "toolwright serve --toolpack" in out
        assert "toolwright gate allow --all --toolset readonly" in out

        toolpack_files = list((tmp_path / "toolpacks").glob("*/toolpack.yaml"))
        assert len(toolpack_files) == 1
        with open(toolpack_files[0]) as f:
            payload = yaml.safe_load(f)
        assert payload["schema_version"] == "1.0"
        assert payload["capture_id"] == "cap_demo"
        assert payload["paths"]["tools"] == "artifact/tools.json"
        assert payload["paths"]["contracts"] == "artifact/contracts.yaml"
        assert payload["paths"]["lockfiles"]["pending"] == "lockfile/toolwright.lock.pending.yaml"
        assert (toolpack_files[0].parent / "artifact" / "coverage_report.json").exists()

        assert capture_calls["headless"] is True
        assert capture_calls["capture_kwargs"]["duration_seconds"] == 30

        assert mock_sync.call_count == 1
        sync_kwargs = mock_sync.call_args.kwargs
        assert sync_kwargs["capture_id"] == "cap_demo"
        assert sync_kwargs["scope"] == "agent_safe_readonly"
        assert sync_kwargs["tools_path"].endswith("artifact/tools.json")

    def test_run_mint_webmcp_appends_discovered_exchanges(self, tmp_path: Path) -> None:
        artifact_dir = _write_artifact_fixture(tmp_path)
        session = CaptureSession(
            id="cap_demo",
            name="Demo Capture",
            source=CaptureSource.PLAYWRIGHT,
            allowed_hosts=["api.example.com"],
            created_at=datetime(2026, 2, 5, tzinfo=UTC),
            exchanges=[
                HttpExchange(
                    url="https://api.example.com/users",
                    method=HTTPMethod.GET,
                    host="api.example.com",
                    path="/users",
                )
            ],
        )
        webmcp_exchange = HttpExchange(
            url="https://app.example.com#webmcp-tool-search_products",
            method=HTTPMethod.GET,
            host="app.example.com",
            path="/webmcp/search_products",
            response_status=200,
            response_body_json={"webmcp_tool": True, "name": "search_products"},
            source=CaptureSource.WEBMCP,
        )

        compile_result = CompileResult(
            artifact_id="art_demo",
            output_path=artifact_dir,
            scope=Scope(name="agent_safe_readonly"),
            endpoint_count=1,
            generated_at=session.created_at,
            artifacts_created=(
                ("Tool Manifest", artifact_dir / "tools.json"),
                ("Toolsets", artifact_dir / "toolsets.yaml"),
                ("Policy", artifact_dir / "policy.yaml"),
                ("Baseline", artifact_dir / "baseline.json"),
            ),
            tools_path=artifact_dir / "tools.json",
            toolsets_path=artifact_dir / "toolsets.yaml",
            policy_path=artifact_dir / "policy.yaml",
            baseline_path=artifact_dir / "baseline.json",
            contracts_path=artifact_dir / "contracts.yaml",
            contract_yaml_path=artifact_dir / "contract.yaml",
            contract_json_path=artifact_dir / "contract.json",
        )

        class FakePlaywrightCapture:
            def __init__(self, allowed_hosts: list[str], headless: bool = False, storage_state_path: str | None = None) -> None:
                self.allowed_hosts = allowed_hosts
                self.headless = headless
                self.storage_state_path = storage_state_path

            async def capture(self, **kwargs):  # noqa: ANN003, ARG002
                return session

        with patch(
            "toolwright.core.capture.playwright_capture.PlaywrightCapture",
            FakePlaywrightCapture,
        ), patch(
            "toolwright.cli.mint.discover_webmcp_exchanges",
            return_value=[webmcp_exchange],
        ) as mock_discover, patch(
            "toolwright.cli.mint.compile_capture_session",
            return_value=compile_result,
        ) as mock_compile, patch(
            "toolwright.cli.mint.sync_lockfile",
            return_value=ApprovalSyncResult(
                lockfile_path=tmp_path / "dummy.lock.yaml",
                artifacts_digest="abc123",
                changes={"new": [], "modified": [], "removed": [], "unchanged": []},
                has_pending=True,
                pending_count=2,
            ),
        ):
            run_mint(
                start_url="https://app.example.com",
                allowed_hosts=["api.example.com"],
                name="Demo",
                scope_name="agent_safe_readonly",
                headless=True,
                script_path=None,
                duration_seconds=30,
                output_root=str(tmp_path),
                deterministic=True,
                print_mcp_config=False,
                webmcp=True,
                verbose=False,
            )

        mock_discover.assert_called_once()
        compiled_session = mock_compile.call_args.kwargs["session"]
        assert len(compiled_session.exchanges) == 2
        assert any(exchange.path == "/webmcp/search_products" for exchange in compiled_session.exchanges)

    def test_build_mcp_config_snippet(self, tmp_path: Path) -> None:
        snippet = build_mcp_config_snippet(
            toolpack_path=tmp_path / "toolpack.yaml",
            server_name="demo",
        )
        payload = json.loads(snippet)
        server = payload["mcpServers"]["demo"]
        assert isinstance(server["command"], str)
        assert server["command"]
        assert "serve" in server["args"]
        assert "--toolpack" in server["args"]

    def test_mint_cli_wires_arguments(self) -> None:
        runner = CliRunner()
        with patch("toolwright.cli.mint.run_mint") as mock_run:
            result = runner.invoke(
                cli,
                [
                    "mint",
                    "https://app.example.com",
                    "-a",
                    "api.example.com",
                    "--duration",
                    "20",
                    "--print-mcp-config",
                ],
            )

        assert result.exit_code == 0
        kwargs = mock_run.call_args.kwargs
        assert kwargs["start_url"] == "https://app.example.com"
        assert kwargs["allowed_hosts"] == ["api.example.com"]
        assert kwargs["duration_seconds"] == 20
        assert kwargs["print_mcp_config"] is True
        assert kwargs["runtime_mode"] == "local"
        assert kwargs["runtime_build"] is False
        assert kwargs["runtime_tag"] is None
        assert kwargs["runtime_version_pin"] is None

    def test_mint_missing_playwright_exact_error(self, monkeypatch) -> None:
        runner = CliRunner()

        async def _raise_import_error(self, **kwargs):  # noqa: ANN001, ARG001
            raise ImportError("No module named 'playwright'")

        monkeypatch.setattr(
            "toolwright.core.capture.playwright_capture.PlaywrightCapture.capture",
            _raise_import_error,
        )

        result = runner.invoke(
            cli,
            [
                "mint",
                "https://app.example.com",
                "-a",
                "api.example.com",
            ],
        )

        assert result.exit_code != 0
        assert "Minting toolpack from" in result.stdout
        assert (
            result.stderr
            == 'Error: Playwright not installed. Install with: pip install "toolwright[playwright]"\n'
        )

    def test_mint_missing_browsers_exact_error(self, monkeypatch) -> None:
        runner = CliRunner()

        async def _raise_missing_browser(self, **kwargs):  # noqa: ANN001, ARG001
            raise RuntimeError(
                "BrowserType.launch: Executable doesn't exist. "
                "Please run playwright install chromium"
            )

        monkeypatch.setattr(
            "toolwright.core.capture.playwright_capture.PlaywrightCapture.capture",
            _raise_missing_browser,
        )

        result = runner.invoke(
            cli,
            [
                "mint",
                "https://app.example.com",
                "-a",
                "api.example.com",
            ],
        )

        assert result.exit_code != 0
        assert "Minting toolpack from" in result.stdout
        assert (
            result.stderr
            == "Error: Playwright browsers not installed. Run: playwright install chromium\n"
        )

    def test_mint_missing_browsers_verbose_still_single_line(self, monkeypatch) -> None:
        runner = CliRunner()

        async def _raise_missing_browser(self, **kwargs):  # noqa: ANN001, ARG001
            raise RuntimeError("Executable doesn't exist; run playwright install chromium")

        monkeypatch.setattr(
            "toolwright.core.capture.playwright_capture.PlaywrightCapture.capture",
            _raise_missing_browser,
        )

        result = runner.invoke(
            cli,
            [
                "-v",
                "mint",
                "https://app.example.com",
                "-a",
                "api.example.com",
            ],
        )

        assert result.exit_code != 0
        assert "Traceback" not in result.stderr
        assert (
            result.stderr
            == "Error: Playwright browsers not installed. Run: playwright install chromium\n"
        )
