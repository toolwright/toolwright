"""MCP inspection command registration for the top-level CLI."""

from __future__ import annotations

import click


def register_mcp_commands(*, cli: click.Group) -> None:
    """Register MCP-specific inspection commands on the provided CLI group."""

    @cli.command(hidden=True)
    @click.option(
        "--artifacts", "-a",
        type=click.Path(exists=True),
        help="Path to artifacts directory",
    )
    @click.option(
        "--tools", "-t",
        type=click.Path(exists=True),
        help="Path to tools.json (overrides --artifacts)",
    )
    @click.option(
        "--policy", "-p",
        type=click.Path(exists=True),
        help="Path to policy.yaml (overrides --artifacts)",
    )
    @click.option(
        "--lockfile", "-l",
        type=click.Path(),
        help="Path to lockfile (default: ./toolwright.lock.yaml)",
    )
    @click.option(
        "--rules-path",
        type=click.Path(),
        help="Path to behavioral rules JSON file (enables CORRECT meta-tools)",
    )
    @click.option(
        "--circuit-breaker-path",
        type=click.Path(),
        help="Path to circuit breaker state JSON file (enables KILL meta-tools)",
    )
    @click.pass_context
    def inspect(
        ctx: click.Context,  # noqa: ARG001
        artifacts: str | None,
        tools: str | None,
        policy: str | None,
        lockfile: str | None,
        rules_path: str | None,
        circuit_breaker_path: str | None,
    ) -> None:
        """Start a read-only MCP introspection server.

        Allows operators and CI tools to inspect governance state:
        list actions, check policy, view approval status, get risk summaries.

        \b
        Examples:
          toolwright inspect --artifacts .toolwright/artifacts/*/
          toolwright inspect --tools tools.json --policy policy.yaml
          toolwright inspect --tools tools.json --rules-path rules.json --circuit-breaker-path breakers.json

        \b
        Available tools exposed:
          GOVERN: toolwright_list_actions, toolwright_check_policy,
                  toolwright_get_approval_status, toolwright_risk_summary
          HEAL:   toolwright_diagnose_tool, toolwright_health_check
          KILL:   toolwright_kill_tool, toolwright_enable_tool,
                  toolwright_quarantine_report (requires --circuit-breaker-path)
          CORRECT: toolwright_add_rule, toolwright_list_rules,
                   toolwright_remove_rule (requires --rules-path)

        \b
        Claude Desktop configuration:
          {
            "mcpServers": {
              "toolwright": {
                "command": "toolwright",
                "args": ["inspect", "--tools", "/path/to/tools.json"]
              }
            }
          }
        """
        from toolwright.utils.deps import require_mcp_dependency

        require_mcp_dependency()

        from toolwright.mcp.meta_server import run_meta_server

        run_meta_server(
            artifacts_dir=artifacts,
            tools_path=tools,
            policy_path=policy,
            lockfile_path=lockfile,
            rules_path=rules_path,
            circuit_breaker_path=circuit_breaker_path,
        )
