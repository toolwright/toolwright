#!/usr/bin/env python3
"""Deterministic Prove Twice orchestration for the umbrella monorepo.

Flow:
1) Tide browser proof + HAR export
2) Toolwright HAR ingestion + compile
3) Toolwright mint + gate + run config for governed MCP
4) Tide MCP replay proof + run diff
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import textwrap
import time
import urllib.parse
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TIDE_DIR = REPO_ROOT / "tide"
TOOLWRIGHT_DIR = REPO_ROOT


@dataclass(frozen=True)
class ScenarioSpec:
    name: str
    description: str
    server_script: str
    prove_once_workflow_yaml: str
    prove_once_step_id: str
    parity_assertion: str
    preferred_replay_paths: tuple[str, ...]


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    print(f"\n$ {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print(proc.stderr.rstrip(), file=sys.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc.stdout


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_http_ready(port: int, timeout_seconds: float = 10.0) -> None:
    import urllib.request

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1):
                return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"Local demo server did not become ready on port {port}")


def _basic_products_server_script(port: int) -> str:
    return textwrap.dedent(
        f"""\
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

PORT = {port}

class Handler(BaseHTTPRequestHandler):
    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            html = \"\"\"<!doctype html>
<html>
  <body>
    <div id="status">Loaded 1 products</div>
    <script>
      const status = document.getElementById('status');
      let tick = 0;
      const poll = () => {{
        fetch('/api/products')
          .then((r) => r.json())
          .then((data) => {{
            status.innerText = 'Loaded ' + data.length + ' products';
          }})
          .catch(() => {{
            status.innerText = 'Load failed';
          }});
        tick += 1;
        if (tick < 8) {{
          setTimeout(poll, 800);
        }}
      }};
      poll();
    </script>
  </body>
</html>\"\"\"
            self._send(200, "text/html", html.encode("utf-8"))
            return
        if self.path == "/api/products":
            payload = [{{"id": "p1", "name": "Widget", "price": 42}}]
            self._send(200, "application/json", json.dumps(payload).encode("utf-8"))
            return
        self._send(404, "text/plain", b"not found")

server = HTTPServer(("127.0.0.1", PORT), Handler)
server.serve_forever()
"""
    )


def _auth_refresh_server_script(port: int) -> str:
    return textwrap.dedent(
        f"""\
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import urllib.parse

PORT = {port}
ORDERS = [
    {{"id": "o1", "amount_cents": 1999}},
    {{"id": "o2", "amount_cents": 4999}},
    {{"id": "o3", "amount_cents": 2599}},
]

def _parse_json(raw):
    if not raw:
        return {{}}
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {{}}

def _send_json(handler, status, payload, extra_headers=None):
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    if extra_headers:
        for key, value in extra_headers.items():
            handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(json.dumps(payload).encode("utf-8"))

class Handler(BaseHTTPRequestHandler):
    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        return _parse_json(raw)

    def _bearer_token(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        return auth.split(" ", 1)[1]

    def _require_access(self):
        token = self._bearer_token()
        if token == "at2" or token == "at3":
            return token
        _send_json(self, 401, {{"error": "invalid_token", "hint": "refresh"}})
        return None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/":
            html = \"\"\"<!doctype html>
<html>
  <body>
    <div id="status">Booting...</div>
    <script>
      const status = document.getElementById('status');
      const setStatus = (value) => {{ status.innerText = value; }};

      async function token(payload) {{
        const response = await fetch('/oauth/token', {{
          method: 'POST',
          headers: {{ 'content-type': 'application/json' }},
          body: JSON.stringify(payload),
        }});
        if (!response.ok) {{
          throw new Error('token_failed_' + response.status);
        }}
        return response.json();
      }}

      async function bootstrap() {{
        let creds = await token({{
          grant_type: 'password',
          username: 'demo',
          password: 'demo',
        }});

        async function api(path) {{
          let resp = await fetch(path, {{
            headers: {{ Authorization: `Bearer ${{creds.access_token}}` }},
          }});

          if (resp.status === 401) {{
            creds = await token({{
              grant_type: 'refresh_token',
              refresh_token: creds.refresh_token,
            }});
            resp = await fetch(path, {{
              headers: {{ Authorization: `Bearer ${{creds.access_token}}` }},
            }});
          }}

          if (!resp.ok) {{
            throw new Error('api_failed_' + resp.status);
          }}
          return resp.json();
        }}

        const profile = await api('/api/profile');
        let cursor = null;
        let total = 0;
        do {{
          const route = cursor ? `/api/orders?cursor=${{cursor}}` : '/api/orders';
          const page = await api(route);
          total += page.items.length;
          cursor = page.next_cursor;
        }} while (cursor);

        await fetch('/healthz');
        setStatus(`Orders loaded ${{total}} total for ${{profile.name}}`);
      }}

      bootstrap().catch(() => setStatus('Load failed'));
    </script>
  </body>
</html>\"\"\"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        if path == "/healthz":
            _send_json(self, 200, {{"ok": True, "service": "demo"}})
            return

        if path == "/api/profile":
            if self._require_access() is None:
                return
            _send_json(self, 200, {{"id": "u1", "name": "Ada"}})
            return

        if path == "/api/orders":
            if self._require_access() is None:
                return
            query = urllib.parse.parse_qs(parsed.query)
            cursor = query.get("cursor", [None])[0]
            if cursor in (None, ""):
                payload = {{"items": ORDERS[:2], "next_cursor": "page2"}}
            elif cursor == "page2":
                payload = {{"items": ORDERS[2:], "next_cursor": None}}
            else:
                payload = {{"items": [], "next_cursor": None}}
            _send_json(self, 200, payload)
            return

        _send_json(self, 404, {{"error": "not_found"}})

    def do_POST(self):
        if self.path != "/oauth/token":
            _send_json(self, 404, {{"error": "not_found"}})
            return

        body = self._read_json()
        grant_type = body.get("grant_type")

        if (
            grant_type == "password"
            and body.get("username") == "demo"
            and body.get("password") == "demo"
        ):
            _send_json(
                self,
                200,
                {{
                    "access_token": "at1",
                    "refresh_token": "rt1",
                    "token_type": "bearer",
                    "expires_in": 1,
                }},
                extra_headers={{"Set-Cookie": "session=seed123; HttpOnly; Secure"}},
            )
            return

        if grant_type == "refresh_token" and body.get("refresh_token") in {{"rt1", "rt2"}}:
            access_token = "at2" if body.get("refresh_token") == "rt1" else "at3"
            refresh_token = "rt2" if body.get("refresh_token") == "rt1" else "rt3"
            _send_json(
                self,
                200,
                {{
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "token_type": "bearer",
                    "expires_in": 60,
                }},
            )
            return

        _send_json(self, 400, {{"error": "invalid_grant"}})

server = HTTPServer(("127.0.0.1", PORT), Handler)
server.serve_forever()
"""
    )


def _basic_products_workflow_yaml(port: int) -> str:
    return textwrap.dedent(
        f"""\
        version: 1
        name: prove-once-browser
        redaction_profile: default_safe
        steps:
          - type: browser
            id: browse
            headless: true
            actions:
              - action: goto
                url: http://127.0.0.1:{port}/
              - action: assert_text
                text: Loaded 1 products
            evidence:
              screenshot: false
              trace: true
              har: true
          - type: http
            id: products_http
            method: GET
            url: http://127.0.0.1:{port}/api/products
            expect:
              status: 200
              body_contains: '"id": "p1"'
        """
    )


def _auth_refresh_workflow_yaml(port: int) -> str:
    return textwrap.dedent(
        f"""\
        version: 1
        name: prove-once-auth-refresh
        redaction_profile: high_risk_pii
        steps:
          - type: browser
            id: browse_auth
            headless: true
            actions:
              - action: goto
                url: http://127.0.0.1:{port}/
              - action: assert_text
                text: Orders loaded 3 total for Ada
            evidence:
              screenshot: false
              trace: true
              har: true
          - type: http
            id: refresh_http
            method: POST
            url: http://127.0.0.1:{port}/oauth/token
            json:
              grant_type: refresh_token
              refresh_token: rt2
            expect:
              status: 200
              body_contains: '"access_token":'
          - type: http
            id: health_http
            method: GET
            url: http://127.0.0.1:{port}/healthz
            expect:
              status: 200
              body_contains: '"ok": true'
        """
    )


def build_scenario(name: str, port: int) -> ScenarioSpec:
    if name == "basic_products":
        return ScenarioSpec(
            name="basic_products",
            description="Baseline product list capture + governed replay.",
            server_script=_basic_products_server_script(port),
            prove_once_workflow_yaml=_basic_products_workflow_yaml(port),
            prove_once_step_id="products_http",
            parity_assertion="products endpoint returns id=p1",
            preferred_replay_paths=("/api/products",),
        )
    if name == "auth_refresh":
        return ScenarioSpec(
            name="auth_refresh",
            description="OAuth-style auth refresh + pagination + governed replay.",
            server_script=_auth_refresh_server_script(port),
            prove_once_workflow_yaml=_auth_refresh_workflow_yaml(port),
            prove_once_step_id="health_http",
            parity_assertion="governed replay remains reachable after auth-refresh capture",
            preferred_replay_paths=("/healthz", "/api/profile"),
        )
    raise ValueError(f"Unknown scenario '{name}'")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local Prove Twice demo flow.")
    parser.add_argument(
        "--workdir",
        default="/tmp/prove_twice_demo",
        help="Working directory for generated artifacts.",
    )
    parser.add_argument(
        "--scenario",
        choices=["basic_products", "auth_refresh"],
        default="basic_products",
        help="Scenario fixture to execute.",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep existing workdir contents (default clears workdir).",
    )
    return parser


def _write_demo_server(path: Path, scenario: ScenarioSpec) -> None:
    path.write_text(scenario.server_script, encoding="utf-8")


def _last_non_empty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    raise RuntimeError("Command produced no parsable output")


def _resolve_path(text: str) -> Path:
    path = Path(text)
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def _extract_capture_id(output: str) -> str:
    match = re.search(r"(cap_[A-Za-z0-9_]+)", output)
    if not match:
        raise RuntimeError("Could not parse capture id from output")
    return match.group(1)


def _extract_toolpack_path(output: str) -> Path:
    match = re.search(r"Toolpack:\s+(.+)", output)
    if not match:
        raise RuntimeError("Could not parse toolpack path from mint output")
    return Path(match.group(1).strip())


def _normalize_path(path: str) -> str:
    p = path.strip()
    if not p.startswith("/"):
        p = f"/{p}"
    return p.rstrip("/") or "/"


def _path_is_auth_related(path: str, name: str) -> bool:
    haystack = f"{path} {name}".lower()
    keywords = ("auth", "oauth", "token", "refresh", "login", "signin", "session")
    return any(keyword in haystack for keyword in keywords)


def _required_fields(action: dict[str, Any]) -> list[str]:
    schema = action.get("input_schema", {})
    required = schema.get("required", [])
    if isinstance(required, list):
        return [str(item) for item in required]
    return []


def _default_arg_for_field(field: str, field_schema: dict[str, Any]) -> Any:
    if isinstance(field_schema.get("enum"), list) and field_schema["enum"]:
        return field_schema["enum"][0]

    field_type = str(field_schema.get("type", "")).lower()
    if field_type == "integer":
        return 1
    if field_type == "number":
        return 1.0
    if field_type == "boolean":
        return True

    lowered = field.lower()
    if lowered == "id":
        return "p1"
    if lowered == "cursor":
        return "page2"
    if lowered == "grant_type":
        return "refresh_token"
    if lowered == "refresh_token":
        return "rt2"
    if lowered in {"username", "password"}:
        return "demo"
    return "demo"


def pick_tool_call(
    toolpack_path: Path,
    preferred_paths: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, dict[str, Any]]:
    tools_path = toolpack_path.parent / "artifact" / "tools.json"
    data = json.loads(tools_path.read_text(encoding="utf-8"))
    actions = data.get("actions", [])
    if not actions:
        raise RuntimeError(
            "No actions found in tools.json. "
            f"Expected captured API traffic, got 0 actions in: {tools_path}"
        )

    ordered_preferences: list[str] = []
    for path in preferred_paths or []:
        if isinstance(path, str):
            normalized = _normalize_path(path)
            if normalized not in ordered_preferences:
                ordered_preferences.append(normalized)

    best_score: float = -1e9
    best_action: dict[str, Any] | None = None
    for index, raw_action in enumerate(actions):
        action = dict(raw_action)
        method = str(action.get("method", "GET")).upper()
        path = _normalize_path(str(action.get("path", "/")))
        name = str(action.get("name", ""))
        required = _required_fields(action)

        score = 0.0
        preference_rank: int | None = None
        for pref_index, pref in enumerate(ordered_preferences):
            if path == pref or path.startswith(f"{pref}/"):
                preference_rank = pref_index
                break
        if preference_rank is not None:
            score += 1000.0 - (preference_rank * 10.0)
        if method == "GET":
            score += 20.0
        if not _path_is_auth_related(path, name):
            score += 10.0
        if not required:
            score += 5.0
        score -= float(len(required))
        score -= index * 0.001  # stable tie-breaker for deterministic selection

        if score > best_score:
            best_score = score
            best_action = action

    if best_action is None:
        raise RuntimeError("Could not choose a replay tool call from tools.json actions")

    schema = best_action.get("input_schema", {})
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
    args: dict[str, Any] = {}
    for field in _required_fields(best_action):
        field_schema = properties.get(field, {})
        if not isinstance(field_schema, dict):
            field_schema = {}
        args[field] = _default_arg_for_field(field, field_schema)
    return str(best_action["name"]), args


def _step_ok(run_dir: Path, step_id: str) -> bool:
    summary = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    for result in summary.get("results", []):
        if result.get("step_id") == step_id:
            return bool(result.get("ok"))
    return False


def _load_first_har_from_zip(zip_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(zip_path, "r") as handle:
        members = [name for name in handle.namelist() if name.endswith(".har")]
        if not members:
            raise RuntimeError(f"No .har member found in zip: {zip_path}")
        return json.loads(handle.read(members[0]).decode("utf-8"))


def _find_token_leaks(text: str) -> list[str]:
    probes = [
        "Bearer at1",
        "Bearer at2",
        "\"access_token\": \"at1\"",
        "\"access_token\": \"at2\"",
        "\"refresh_token\": \"rt1\"",
        "\"refresh_token\": \"rt2\"",
        "session=seed123",
    ]
    return [probe for probe in probes if probe in text]


def _validate_auth_refresh_artifacts(
    run_once_dir: Path,
    exported_har: Path,
    workdir: Path,
) -> Path:
    artifacts_dir = run_once_dir / "artifacts"
    har_candidates = sorted(artifacts_dir.glob("*.har.zip"))
    if not har_candidates:
        raise RuntimeError(f"Expected browser HAR zip artifact in {artifacts_dir}")

    har_obj = _load_first_har_from_zip(har_candidates[0])
    entries = har_obj.get("log", {}).get("entries", [])
    if not isinstance(entries, list):
        entries = []

    oauth_hits = 0
    orders_hits = 0
    auth_headers_redacted = True
    request_bodies_redacted = True
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        request = entry.get("request", {})
        if not isinstance(request, dict):
            continue

        url = str(request.get("url", ""))
        path = urllib.parse.urlparse(url).path
        if path == "/oauth/token":
            oauth_hits += 1
        if path == "/api/orders":
            orders_hits += 1

        headers = request.get("headers", [])
        if isinstance(headers, list):
            for header in headers:
                if not isinstance(header, dict):
                    continue
                if str(header.get("name", "")).lower() == "authorization":
                    value = str(header.get("value", ""))
                    if value != "***REDACTED***":
                        auth_headers_redacted = False

        post_data = request.get("postData", {})
        if (
            isinstance(post_data, dict)
            and "text" in post_data
            and str(post_data.get("text")) != "***REDACTED_BODY***"
        ):
            request_bodies_redacted = False

    redacted_har_text = json.dumps(har_obj, sort_keys=True)
    redacted_har_leaks = _find_token_leaks(redacted_har_text)

    exported_har_text = exported_har.read_text(encoding="utf-8")
    exported_har_leaks = _find_token_leaks(exported_har_text)

    checks = {
        "oauth_token_request_count": oauth_hits,
        "orders_request_count": orders_hits,
        "authorization_headers_redacted": auth_headers_redacted,
        "request_bodies_redacted": request_bodies_redacted,
        "redacted_har_leaks": redacted_har_leaks,
        "exported_har_leaks": exported_har_leaks,
        "ok": (
            oauth_hits >= 2
            and orders_hits >= 2
            and auth_headers_redacted
            and request_bodies_redacted
            and not redacted_har_leaks
            and not exported_har_leaks
        ),
    }

    checks_path = workdir / "auth_refresh_checks.json"
    checks_path.write_text(json.dumps(checks, indent=2) + "\n", encoding="utf-8")
    if not checks["ok"]:
        raise RuntimeError(f"Auth refresh redaction checks failed. See: {checks_path}")
    return checks_path


def main(argv: list[str]) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    workdir = Path(args.workdir).resolve()
    if workdir.exists() and not args.keep:
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    port = _pick_free_port()
    host_with_port = f"127.0.0.1:{port}"
    scenario = build_scenario(args.scenario, port)
    server_script = workdir / "demo_server.py"
    _write_demo_server(server_script, scenario)

    server_proc = subprocess.Popen(
        [sys.executable, str(server_script)],
        cwd=str(workdir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        _wait_http_ready(port)
        print(f"Local demo server ready on http://127.0.0.1:{port}")
        print(f"Scenario: {scenario.name} ({scenario.description})")

        tide_once = workdir / "tide_once.yaml"
        tide_once.write_text(scenario.prove_once_workflow_yaml, encoding="utf-8")

        run_once_output = _run(
            [
                "uv",
                "run",
                "--project",
                str(TIDE_DIR),
                "--extra",
                "playwright",
                "--extra",
                "mcp",
                "tide",
                "run",
                str(tide_once),
            ]
        )
        run_once_dir = _resolve_path(_last_non_empty_line(run_once_output))
        har_out = workdir / "traffic.har"
        _run(
            [
                "uv",
                "run",
                "--project",
                str(TIDE_DIR),
                "--extra",
                "mcp",
                "tide",
                "export",
                "toolwright",
                str(run_once_dir),
                "--out",
                str(har_out),
            ]
        )
        auth_checks_path: Path | None = None
        if scenario.name == "auth_refresh":
            auth_checks_path = _validate_auth_refresh_artifacts(run_once_dir, har_out, workdir)

        tw_root = workdir / ".toolwright"
        import_output = _run(
            [
                "uv",
                "run",
                "--project",
                str(TOOLWRIGHT_DIR),
                "toolwright",
                "--root",
                str(tw_root),
                "capture",
                "import",
                str(har_out),
                "-a",
                host_with_port,
                "-a",
                "127.0.0.1",
                "-a",
                "localhost",
                "-n",
                "tide_har_capture",
            ]
        )
        capture_id = _extract_capture_id(import_output)
        _run(
            [
                "uv",
                "run",
                "--project",
                str(TOOLWRIGHT_DIR),
                "toolwright",
                "--root",
                str(tw_root),
                "compile",
                "--capture",
                capture_id,
                "--scope",
                "first_party_only",
            ]
        )

        mint_output = _run(
            [
                "uv",
                "run",
                "--project",
                str(TOOLWRIGHT_DIR),
                "--extra",
                "playwright",
                "toolwright",
                "--root",
                str(tw_root),
                "mint",
                f"http://127.0.0.1:{port}/",
                "-a",
                host_with_port,
                "-a",
                "127.0.0.1",
                "--duration",
                "5",
            ]
        )
        toolpack_path = _extract_toolpack_path(mint_output)
        lockfile_pending = toolpack_path.parent / "lockfile" / "toolwright.lock.pending.yaml"
        _run(
            [
                "uv",
                "run",
                "--project",
                str(TOOLWRIGHT_DIR),
                "toolwright",
                "--root",
                str(tw_root),
                "gate",
                "allow",
                "--all",
                "--toolset",
                "readonly",
                "--lockfile",
                str(lockfile_pending),
            ]
        )
        run_cfg = _run(
            [
                "uv",
                "run",
                "--project",
                str(TOOLWRIGHT_DIR),
                "toolwright",
                "run",
                "--toolpack",
                str(toolpack_path),
                "--print-config-and-exit",
            ]
        )
        cfg = json.loads(run_cfg)
        server_name = next(iter(cfg["mcpServers"]))
        server = cfg["mcpServers"][server_name]
        server_cmd = [server["command"], *server["args"]]
        server_cmd.extend(["--base-url", f"http://127.0.0.1:{port}"])
        server_cmd.extend(["--allow-private-cidr", "127.0.0.0/8"])

        tool_name, tool_args = pick_tool_call(
            toolpack_path,
            preferred_paths=list(scenario.preferred_replay_paths),
        )
        tide_replay = workdir / "tide_replay.yaml"
        tide_replay.write_text(
            textwrap.dedent(
                f"""\
                version: 1
                name: prove-again-mcp-{scenario.name}
                redaction_profile: default_safe
                steps:
                  - type: mcp
                    id: replay_mcp
                    server_cmd: {json.dumps(server_cmd)}
                    tool_name: {tool_name}
                    arguments: {json.dumps(tool_args)}
                    expect:
                      decision: allow
                """
            ),
            encoding="utf-8",
        )

        run_replay_output = _run(
            [
                "uv",
                "run",
                "--project",
                str(TIDE_DIR),
                "--extra",
                "mcp",
                "tide",
                "run",
                str(tide_replay),
            ]
        )
        run_replay_dir = _resolve_path(_last_non_empty_line(run_replay_output))
        diff_output = _run(
            [
                "uv",
                "run",
                "--project",
                str(TIDE_DIR),
                "tide",
                "diff",
                str(run_once_dir),
                str(run_replay_dir),
                "--format",
                "json",
            ]
        )
        (workdir / "prove_twice_diff.json").write_text(diff_output, encoding="utf-8")
        _run(
            [
                "uv",
                "run",
                "--project",
                str(TIDE_DIR),
                "tide",
                "pack",
                str(run_replay_dir),
                "--out",
                str(workdir / "replay_bundle.zip"),
            ]
        )

        parity_rows = [
            {
                "assertion": scenario.parity_assertion,
                "prove_once_step": scenario.prove_once_step_id,
                "prove_again_step": "replay_mcp",
                "prove_once_ok": _step_ok(run_once_dir, scenario.prove_once_step_id),
                "prove_again_ok": _step_ok(run_replay_dir, "replay_mcp"),
            }
        ]
        parity_ok = all(row["prove_once_ok"] and row["prove_again_ok"] for row in parity_rows)
        report_path = workdir / "prove_twice_report.md"
        lines = [
            "# Prove Twice Report",
            "",
            f"- scenario: `{scenario.name}`",
            f"- prove_once_run: `{run_once_dir}`",
            f"- prove_again_run: `{run_replay_dir}`",
            f"- parity_ok: `{parity_ok}`",
            "",
            "| Assertion | Prove Once | Prove Again |",
            "| --- | --- | --- |",
        ]
        for row in parity_rows:
            left = "pass" if row["prove_once_ok"] else "fail"
            right = "pass" if row["prove_again_ok"] else "fail"
            lines.append(f"| {row['assertion']} | {left} | {right} |")
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        print("\nProve Twice complete.")
        print(f"- Tide run #1: {run_once_dir}")
        print(f"- Exported HAR: {har_out}")
        print(f"- Cask root: {tw_root}")
        print(f"- Toolpack: {toolpack_path}")
        print(f"- Tide run #2: {run_replay_dir}")
        print(f"- Diff JSON: {workdir / 'prove_twice_diff.json'}")
        print(f"- Parity report: {report_path}")
        if auth_checks_path:
            print(f"- Auth refresh checks: {auth_checks_path}")
        return 0
    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server_proc.kill()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
