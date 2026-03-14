"""Tests for enforce CLI wiring and proxy lockfile defaults."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from toolwright.cli.enforce import run_enforce
from toolwright.cli.main import cli


def _write_tools_and_policy(tmp_path: Path) -> tuple[Path, Path]:
    tools_path = tmp_path / "tools.json"
    policy_path = tmp_path / "policy.yaml"
    tools_path.write_text(
        json.dumps(
            {
                "actions": [
                    {
                        "name": "get_user",
                        "method": "GET",
                        "path": "/api/users/{id}",
                        "host": "api.example.com",
                        "risk_tier": "low",
                    }
                ]
            }
        )
    )
    policy_path.write_text(
        """
name: test_policy
rules:
  - id: allow_get
    name: Allow GET requests
    type: allow
    match:
      methods: [GET]
default_action: deny
""".strip()
    )
    return tools_path, policy_path


class TestEnforceCLIWiring:
    def test_cli_passes_unsafe_no_lockfile_flag(self, tmp_path: Path) -> None:
        tools_path, policy_path = _write_tools_and_policy(tmp_path)
        runner = CliRunner()

        with patch("toolwright.cli.enforce.run_enforce") as mock_run:
            result = runner.invoke(
                cli,
                [
                    "enforce",
                    "--tools",
                    str(tools_path),
                    "--policy",
                    str(policy_path),
                    "--mode",
                    "proxy",
                    "--unsafe-no-lockfile",
                ],
            )

        assert result.exit_code == 0
        assert mock_run.call_args.kwargs["unsafe_no_lockfile"] is True

    def test_proxy_mode_requires_lockfile_by_default(self, tmp_path: Path) -> None:
        tools_path, policy_path = _write_tools_and_policy(tmp_path)
        runner = CliRunner()

        result = runner.invoke(
            cli,
            [
                "enforce",
                "--tools",
                str(tools_path),
                "--policy",
                str(policy_path),
                "--mode",
                "proxy",
            ],
        )

        assert result.exit_code == 1
        assert "Proxy mode requires --lockfile" in result.output


class TestRunEnforce:
    def test_run_enforce_allows_unsafe_proxy_without_lockfile(self, tmp_path: Path) -> None:
        tools_path, policy_path = _write_tools_and_policy(tmp_path)

        class FakeHTTPServer:
            def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
                pass

            def serve_forever(self) -> None:
                raise KeyboardInterrupt

            def shutdown(self) -> None:
                return None

        with patch("toolwright.cli.enforce.HTTPServer", FakeHTTPServer):
            run_enforce(
                tools_path=str(tools_path),
                toolsets_path=None,
                toolset_name=None,
                policy_path=str(policy_path),
                port=18081,
                audit_log=None,
                dry_run=True,
                verbose=False,
                mode="proxy",
                base_url=None,
                auth_header=None,
                lockfile_path=None,
                confirmation_store_path=str(tmp_path / "confirmations.db"),
                allow_private_cidrs=None,
                allow_redirects=False,
                unsafe_no_lockfile=True,
            )

    def test_evaluate_mode_does_not_start_server(self, tmp_path: Path) -> None:
        """H6: evaluate mode should evaluate and exit, not start HTTP server."""
        tools_path, policy_path = _write_tools_and_policy(tmp_path)

        # HTTPServer should NOT be instantiated in evaluate mode
        with patch("toolwright.cli.enforce.HTTPServer") as mock_server:
            run_enforce(
                tools_path=str(tools_path),
                toolsets_path=None,
                toolset_name=None,
                policy_path=str(policy_path),
                port=18082,
                audit_log=None,
                dry_run=False,
                verbose=False,
                mode="evaluate",
                base_url=None,
                auth_header=None,
                lockfile_path=None,
                confirmation_store_path=str(tmp_path / "confirmations.db"),
                allow_private_cidrs=None,
                allow_redirects=False,
                unsafe_no_lockfile=False,
            )
            mock_server.assert_not_called()
