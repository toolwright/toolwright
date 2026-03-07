"""Tests ensuring CLI behavior matches documentation promises.

Covers:
- #10: mint defaults to interactive (non-headless) mode
- #11: mint duration default matches quickstart docs (120s)
- #9: groups command is in CORE_COMMANDS for discoverability
- #5: probe shows "configured" when auth env var is already set
"""

from __future__ import annotations

import os

import click.testing
import pytest


# ── #10: mint defaults to interactive (non-headless) ──────────────


def test_mint_default_is_interactive() -> None:
    """mint should default to --no-headless (interactive browser) since
    the quickstarts tell users to browse around and close the window."""
    from toolwright.cli.main import cli

    # Inspect the Click command to find the headless option's default
    mint_cmd = cli.commands.get("mint")
    assert mint_cmd is not None, "mint command not registered"

    headless_param = None
    for param in mint_cmd.params:
        if param.name == "headless":
            headless_param = param
            break
    assert headless_param is not None, "headless param not found on mint"
    assert headless_param.default is False, (
        "mint should default to --no-headless (interactive mode). "
        "Headless is for scripted/CI capture via --headless or ship."
    )


# ── #11: mint duration matches quickstart expected output ─────────


def test_mint_default_duration_matches_docs() -> None:
    """mint --duration default should be 120s to match quickstart expected output."""
    from toolwright.cli.main import cli

    mint_cmd = cli.commands.get("mint")
    assert mint_cmd is not None

    duration_param = None
    for param in mint_cmd.params:
        if param.name == "duration":
            duration_param = param
            break
    assert duration_param is not None, "duration param not found on mint"
    assert duration_param.default == 120, (
        "mint --duration should default to 120s to match quickstart docs. "
        f"Got {duration_param.default}s."
    )


# ── #9: groups in core commands ───────────────────────────────────


def test_groups_in_core_commands() -> None:
    """groups should be listed in CORE_COMMANDS — it's in the README and
    both quickstarts but was missing from `toolwright --help`."""
    from toolwright.cli.main import CORE_COMMANDS

    assert "groups" in CORE_COMMANDS, (
        "groups must be a core command. The README and both quickstarts "
        "reference `toolwright groups list` as a key workflow step."
    )


# ── #5: probe shows ✓ configured when env var is set ─────────────


def test_probe_shows_configured_when_env_var_set(capsys, monkeypatch) -> None:
    """When the auth env var is already set, the probe should show
    '✓ configured' instead of just the 401 warning with an export hint."""
    from toolwright.cli.mint import ProbeResult, _render_probe_results

    monkeypatch.setenv("TOOLWRIGHT_AUTH_API_GITHUB_COM", "Bearer ghp_test123")

    result = ProbeResult(
        base_status=401,
        auth_required=True,
        auth_scheme="Bearer",
    )
    _render_probe_results(
        result, "https://api.github.com", ["api.github.com"]
    )
    captured = capsys.readouterr()
    # Should show the configured indicator, not just the bare export hint
    assert "configured" in captured.out.lower(), (
        "When TOOLWRIGHT_AUTH_API_GITHUB_COM is already set, probe should "
        "show 'configured' instead of only suggesting export."
    )


def test_probe_shows_export_hint_when_env_var_missing(capsys, monkeypatch) -> None:
    """When the auth env var is NOT set, the probe should show the export hint."""
    from toolwright.cli.mint import ProbeResult, _render_probe_results

    monkeypatch.delenv("TOOLWRIGHT_AUTH_API_GITHUB_COM", raising=False)

    result = ProbeResult(
        base_status=401,
        auth_required=True,
        auth_scheme="Bearer",
    )
    _render_probe_results(
        result, "https://api.github.com", ["api.github.com"]
    )
    captured = capsys.readouterr()
    assert "export" in captured.out, (
        "When env var is missing, probe should show the export command."
    )
    assert "TOOLWRIGHT_AUTH_API_GITHUB_COM" in captured.out


def test_probe_host_shows_configured_when_env_var_set(capsys, monkeypatch) -> None:
    """Per-host probe also shows configured status when env var exists."""
    from toolwright.cli.mint import ProbeResult, _render_probe_results

    monkeypatch.setenv("TOOLWRIGHT_AUTH_API_STRIPE_COM", "Bearer sk_test_xxx")

    result = ProbeResult(
        host_probes={
            "api.stripe.com": {
                "status": 401,
                "content_type": "json",
                "auth_required": True,
                "auth_scheme": "Bearer",
                "error": None,
            }
        },
    )
    _render_probe_results(
        result, "https://dashboard.stripe.com", ["api.stripe.com"]
    )
    captured = capsys.readouterr()
    assert "configured" in captured.out.lower(), (
        "Per-host probe should show 'configured' when env var is set."
    )
