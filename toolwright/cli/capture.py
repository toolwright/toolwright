"""Capture command implementation."""

import sys
import tempfile
from pathlib import Path
from urllib.request import urlopen

import click

from toolwright.cli.playwright_errors import emit_playwright_error, emit_playwright_missing_package
from toolwright.core.capture.har_parser import HARParser
from toolwright.core.capture.openapi_parser import OpenAPIParser
from toolwright.core.capture.otel_parser import OTELParser
from toolwright.core.capture.redactor import Redactor
from toolwright.storage.filesystem import Storage


def run_capture(
    subcommand: str,
    source: str | None,
    input_format: str,
    allowed_hosts: list[str],
    name: str | None,
    output: str,
    redact: bool,
    headless: bool,
    script_path: str | None,
    duration_seconds: int,
    verbose: bool,
    load_storage_state: str | None = None,
    save_storage_state: str | None = None,
    root_path: str | None = ".toolwright",
) -> None:
    """Run the capture command."""
    if subcommand == "import":
        if not source:
            click.echo("Error: SOURCE is required for 'import' subcommand", err=True)
            sys.exit(1)
        if input_format == "har":
            _import_har(
                source=source,
                allowed_hosts=allowed_hosts,
                name=name,
                output=output,
                root_path=root_path,
                redact=redact,
                verbose=verbose,
            )
        elif input_format == "otel":
            _import_otel(
                source=source,
                allowed_hosts=allowed_hosts,
                name=name,
                output=output,
                root_path=root_path,
                redact=redact,
                verbose=verbose,
            )
        else:
            click.echo(f"Error: Unsupported input format: {input_format}", err=True)
            sys.exit(1)
    elif subcommand == "record":
        if input_format != "har":
            click.echo(
                "Error: --input-format is only supported for 'import' subcommand",
                err=True,
            )
            sys.exit(1)
        if not source:
            click.echo("Error: URL is required for 'record' subcommand", err=True)
            click.echo("Usage: toolwright capture record <URL> --allowed-hosts <host>", err=True)
            sys.exit(1)
        _record_playwright(
            start_url=source,
            allowed_hosts=allowed_hosts,
            name=name,
            output=output,
            root_path=root_path,
            redact=redact,
            headless=headless,
            script_path=script_path,
            duration_seconds=duration_seconds,
            load_storage_state=load_storage_state,
            save_storage_state=save_storage_state,
            verbose=verbose,
        )


def run_capture_openapi(
    source: str,
    allowed_hosts: list[str] | None,
    name: str | None,
    output: str,
    verbose: bool,
    root_path: str | None = ".toolwright",
) -> None:
    """Import an OpenAPI specification.

    Args:
        source: Path to OpenAPI spec file
        allowed_hosts: Optional list of allowed hosts
        name: Optional session name
        output: Output directory
        verbose: Verbose output
    """
    # Fetch URL or resolve local file path
    tmp_file = None
    if source.startswith(("http://", "https://")):
        if verbose:
            click.echo(f"Fetching OpenAPI spec from URL: {source}")
        try:
            response = urlopen(source)  # noqa: S310
            content = response.read()
            # Determine suffix from URL
            suffix = ".json" if source.endswith(".json") else ".yaml"
            if source.endswith((".yml", ".yaml")):
                suffix = ".yaml"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
                tmp_file.write(content)
            source_path = Path(tmp_file.name)
        except Exception as e:
            click.echo(f"Error fetching URL: {e}", err=True)
            sys.exit(1)
    else:
        source_path = Path(source)
        if not source_path.exists():
            click.echo(f"Error: OpenAPI spec not found: {source}", err=True)
            sys.exit(1)

    if verbose:
        click.echo(f"Importing OpenAPI spec: {source}")
        if allowed_hosts:
            click.echo(f"Allowed hosts: {', '.join(allowed_hosts)}")

    # Parse OpenAPI
    parser = OpenAPIParser(allowed_hosts=allowed_hosts or [])

    try:
        session = parser.parse_file(source_path, name=name)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        # Clean up temp file from URL fetch
        temp_dir = Path(tempfile.gettempdir()).resolve()
        if source_path.resolve().parent == temp_dir:
            source_path.unlink(missing_ok=True)

    # Save
    base_path = _resolve_storage_root(output=output, root_path=root_path)
    storage = Storage(base_path=base_path)
    capture_path = storage.save_capture(session)

    click.echo(f"Capture saved: {session.id}")
    click.echo(f"  Location: {capture_path}")
    click.echo(f"  Operations: {len(session.exchanges)}")
    click.echo(f"  Source: OpenAPI {source_path.name}")

    if verbose:
        click.echo("\nImport stats:")
        click.echo(f"  Paths: {parser.stats['total_paths']}")
        click.echo(f"  Operations: {parser.stats['total_operations']}")
        click.echo(f"  Imported: {parser.stats['imported']}")
        click.echo(f"  Skipped: {parser.stats['skipped']}")

    if session.warnings:
        click.echo(f"\nWarnings: {len(session.warnings)}")
        if verbose:
            for warning in session.warnings:
                click.echo(f"  - {warning}")

    # Clean up temp file from URL fetch
    if tmp_file is not None:
        import contextlib
        import os

        with contextlib.suppress(OSError):
            os.unlink(tmp_file.name)


def _import_har(
    source: str,
    allowed_hosts: list[str],
    name: str | None,
    output: str,
    root_path: str | None,
    redact: bool,
    verbose: bool,
) -> None:
    """Import a HAR file."""
    source_path = Path(source)
    if not source_path.exists():
        click.echo(f"Error: HAR file not found: {source}", err=True)
        sys.exit(1)

    if verbose:
        click.echo(f"Importing HAR file: {source}")
        click.echo(f"Allowed hosts: {', '.join(allowed_hosts)}")

    # Parse HAR
    parser = HARParser(allowed_hosts=allowed_hosts)
    session = parser.parse_file(source_path, name=name)

    # Redact if enabled
    if redact:
        if verbose:
            click.echo("Applying redaction...")
        redactor = Redactor()
        session = redactor.redact_session(session)

    # Save
    # Note: output is typically .toolwright/captures, but Storage expects .toolwright
    # so we go up one level if the output ends with /captures
    base_path = _resolve_storage_root(output=output, root_path=root_path)
    storage = Storage(base_path=base_path)
    capture_path = storage.save_capture(session)

    click.echo(f"Capture saved: {session.id}")
    click.echo(f"  Location: {capture_path}")
    click.echo(f"  Exchanges: {len(session.exchanges)}")
    click.echo(f"  Filtered: {session.filtered_requests}")
    if session.warnings:
        click.echo(f"  Warnings: {len(session.warnings)}")
        if verbose:
            for warning in session.warnings:
                click.echo(f"    - {warning}")


def _import_otel(
    source: str,
    allowed_hosts: list[str],
    name: str | None,
    output: str,
    root_path: str | None,
    redact: bool,
    verbose: bool,
) -> None:
    """Import an OTEL trace export file."""
    source_path = Path(source)
    if not source_path.exists():
        click.echo(f"Error: OTEL file not found: {source}", err=True)
        sys.exit(1)

    if verbose:
        click.echo(f"Importing OTEL file: {source}")
        click.echo(f"Allowed hosts: {', '.join(allowed_hosts)}")

    parser = OTELParser(allowed_hosts=allowed_hosts)
    session = parser.parse_file(source_path, name=name)

    if redact:
        if verbose:
            click.echo("Applying redaction...")
        redactor = Redactor()
        session = redactor.redact_session(session)

    base_path = _resolve_storage_root(output=output, root_path=root_path)
    storage = Storage(base_path=base_path)
    capture_path = storage.save_capture(session)

    click.echo(f"Capture saved: {session.id}")
    click.echo(f"  Location: {capture_path}")
    click.echo(f"  Exchanges: {len(session.exchanges)}")
    click.echo(f"  Filtered: {session.filtered_requests}")
    if session.warnings:
        click.echo(f"  Warnings: {len(session.warnings)}")
        if verbose:
            for warning in session.warnings:
                click.echo(f"    - {warning}")


def _record_playwright(
    start_url: str,
    allowed_hosts: list[str],
    name: str | None,
    output: str,
    root_path: str | None,
    redact: bool,
    headless: bool,
    script_path: str | None,
    duration_seconds: int,
    verbose: bool,
    load_storage_state: str | None = None,
    save_storage_state: str | None = None,
) -> None:
    """Record traffic using Playwright browser automation."""
    try:
        from toolwright.core.capture.playwright_capture import PlaywrightCapture
    except ImportError:
        emit_playwright_missing_package()
        sys.exit(1)

    if verbose:
        click.echo(f"Starting Playwright capture: {start_url}")
        click.echo(f"Allowed hosts: {', '.join(allowed_hosts)}")
        click.echo(f"Headless: {headless}")
        if script_path:
            click.echo(f"Scripted capture: {script_path}")
        elif headless:
            click.echo(f"Duration: {duration_seconds}s")

    # Run capture
    try:
        import asyncio

        capture = PlaywrightCapture(
            allowed_hosts=allowed_hosts,
            headless=headless,
            storage_state_path=load_storage_state,
            save_storage_state_path=save_storage_state,
        )
        session = asyncio.run(
            capture.capture(
                start_url=start_url,
                name=name,
                duration_seconds=duration_seconds if headless and not script_path else None,
                script_path=script_path,
                settle_delay_seconds=1.0 if script_path else 0.0,
            )
        )
    except KeyboardInterrupt:
        click.echo("\nCapture interrupted.")
        sys.exit(0)
    except Exception as exc:
        emit_playwright_error(exc, verbose=verbose, operation="capture")
        sys.exit(1)

    # Redact if enabled
    if redact:
        if verbose:
            click.echo("Applying redaction...")
        redactor = Redactor()
        session = redactor.redact_session(session)

    # Check if we captured anything
    if not session.exchanges:
        click.echo("Warning: No API traffic was captured.", err=True)
        click.echo("Make sure your allowed hosts match the API endpoints.", err=True)
        click.echo(f"Allowed hosts: {', '.join(allowed_hosts)}", err=True)
        sys.exit(1)

    # Save
    base_path = _resolve_storage_root(output=output, root_path=root_path)
    storage = Storage(base_path=base_path)
    capture_path = storage.save_capture(session)

    click.echo(f"\nCapture saved: {session.id}")
    click.echo(f"  Location: {capture_path}")
    click.echo(f"  Exchanges: {len(session.exchanges)}")

    if verbose:
        click.echo("\nCapture stats:")
        click.echo(f"  Total requests: {capture.stats['total_requests']}")
        click.echo(f"  Captured: {capture.stats['captured']}")
        click.echo(f"  Filtered (host): {capture.stats['filtered_host']}")
        click.echo(f"  Filtered (static): {capture.stats['filtered_static']}")
        click.echo(f"  Filtered (resource): {capture.stats['filtered_resource_type']}")

    if session.warnings:
        click.echo(f"\nWarnings: {len(session.warnings)}")
        if verbose:
            for warning in session.warnings:
                click.echo(f"  - {warning}")


def _resolve_storage_root(output: str, root_path: str | None) -> Path:
    """Resolve capture output into canonical storage root."""
    target = Path(output)
    if target.name == "captures":
        return target.parent
    if root_path is not None and target == Path(root_path):
        return target
    return target
