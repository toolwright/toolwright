"""Out-of-band confirmation command implementation."""

from __future__ import annotations

import sys

import click

from toolwright.core.enforce import ConfirmationStore


def run_confirm_grant(token_id: str, db_path: str, verbose: bool) -> None:
    """Grant a pending confirmation token."""
    store = ConfirmationStore(db_path)
    granted = store.grant(token_id)
    if not granted:
        click.echo(f"Token not granted: {token_id}", err=True)
        sys.exit(1)

    click.echo(f"Granted: {token_id}")
    if verbose:
        click.echo(f"Store: {db_path}")


def run_confirm_deny(token_id: str, db_path: str, reason: str | None, verbose: bool) -> None:
    """Deny a pending confirmation token."""
    store = ConfirmationStore(db_path)
    denied = store.deny(token_id, reason)
    if not denied:
        click.echo(f"Token not denied: {token_id}", err=True)
        sys.exit(1)

    click.echo(f"Denied: {token_id}")
    if reason:
        click.echo(f"Reason: {reason}")
    if verbose:
        click.echo(f"Store: {db_path}")


def run_confirm_list(db_path: str, verbose: bool) -> None:
    """List pending confirmation tokens."""
    store = ConfirmationStore(db_path)
    pending = store.list_pending()
    click.echo(f"Pending confirmations: {len(pending)}")
    for item in pending:
        click.echo(
            f"- {item['token_id']} tool_id={item['tool_id']} "
            f"toolset={item['toolset_name'] or '-'} expires_at={int(item['expires_at'])}"
        )
    if verbose:
        click.echo(f"Store: {db_path}")
