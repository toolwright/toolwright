Usage: toolwright [OPTIONS] COMMAND [ARGS]...

  Turn observed web/API traffic into safe, versioned, agent-ready MCP tools.

Options:
  --version         Show the version and exit.
  -v, --verbose     Enable verbose output
  --help-all        Show help including advanced commands
  --root DIRECTORY  Canonical state root for captures, artifacts, reports, and
                    locks  [default: .toolwright]
  --no-interactive  Disable interactive prompts (same as
                    TOOLWRIGHT_NON_INTERACTIVE=1)
  --help            Show this message and exit.

Core Commands:
  status      Show governance status for a toolpack.
  ship        Ship a governed agent end-to-end.
  init        Initialize toolwright in a project directory.
  mint        Capture traffic and compile a governed toolpack.
  gate        Approve or block tools via lockfile-based governance.
  serve       Start the governed MCP server on stdio transport.
  groups      List and inspect auto-generated tool groups.
  config      Print a ready-to-paste MCP client config snippet (Claude,
              Cursor, Codex).
  verify      Run verification contracts (replay, outcomes, provenance).
  drift       Detect drift between captures or against a baseline.
  repair      Diagnose, plan, and apply fixes for a governed toolpack.
  diff        Generate a risk-classified change report.
  dashboard   Open the full-screen governance dashboard.
  rules       Manage behavioral rules for tool usage constraints.
  kill        Kill a tool by forcing its circuit breaker open.
  enable      Re-enable a killed tool by resetting its circuit breaker.
  quarantine  List all tools with open or half-open circuit breakers.
  health      Probe endpoint health for all tools in a manifest.
  run         Execute a toolpack with policy enforcement.
  use         Set the default toolpack for this project.
  demo        One-command proof of governance enforcement.
  rename      Rename a toolpack's display name.
  watch       Monitor reconciliation loop health and events.
  snapshots   List toolpack snapshots.
  rollback    Rollback to a toolpack snapshot.
  share       Package a toolpack into a signed .twp bundle for sharing.
  install     Verify and install a .twp toolpack bundle.
  recipes     Browse and use bundled API recipes.

Advanced:
  auth     Manage authentication profiles and check auth configuration.
  capture  Import traffic from HAR/OTEL/OpenAPI files or capture with
           Playwright.

  Use 'toolwright <command> --help' for details on any command.
  Use 'toolwright --help-all' to see all commands including advanced.
Usage: toolwright mint [OPTIONS] START_URL

  Capture traffic and compile a governed toolpack.

  Example:
    toolwright mint https://example.com -a api.example.com --print-mcp-config
    toolwright mint https://app.example.com -a api.example.com --auth-profile myapp
    toolwright mint https://app.example.com --webmcp -a api.example.com
    toolwright mint https://example.myshopify.com --recipe shopify

Options:
  -a, --allowed-hosts TEXT        Hosts to include (required unless --recipe
                                  provides them, repeatable)
  -n, --name TEXT                 Optional toolpack/session name
  -s, --scope TEXT                Scope to apply during compile  [default:
                                  first_party_only]
  --headless / --no-headless      Run browser headless during capture
                                  (default: interactive)  [default: no-
                                  headless]
  --script PATH                   Python script with async run(page, context)
                                  for scripted capture
  --duration INTEGER              Capture duration in seconds when no script
                                  is provided  [default: 120]
  -o, --output PATH               Output root directory (defaults to --root)
  --deterministic / --volatile-metadata
                                  Deterministic metadata by default; use
                                  --volatile-metadata for ephemeral
                                  IDs/timestamps  [default: deterministic]
  --runtime [local|container]     Runtime mode metadata/emission (container
                                  emits runtime files)  [default: local]
  --runtime-build                 Build container image after emitting runtime
                                  files (requires Docker)
  --runtime-tag TEXT              Container image tag to use when
                                  --runtime=container
  --runtime-version-pin TEXT      Exact requirement line for toolwright
                                  runtime when --runtime=container
  --print-mcp-config              Print a ready-to-paste Claude Desktop MCP
                                  config snippet
  --auth-profile TEXT             Auth profile name to use for authenticated
                                  capture
  --webmcp                        Discover WebMCP tools
                                  (navigator.modelContext) on the target page
  --redaction-profile [default_safe|high_risk_pii]
                                  Redaction profile to apply during capture
                                  (default: built-in patterns)
  -H, --extra-header TEXT         Extra header to inject at serve time
                                  (repeatable, format: 'Name: value')
  --no-probe                      Skip pre-flight API probing (auth, GraphQL,
                                  OpenAPI detection)
  -r, --recipe TEXT               Use a bundled API recipe (e.g., shopify,
                                  github). Sets hosts, headers, auth.
  --help                          Show this message and exit.
Usage: toolwright serve [OPTIONS]

  Start the governed MCP server on stdio transport.

  Exposes compiled tools as callable actions that AI agents can use safely,
  with policy enforcement, confirmation requirements, and audit logging.

  For production use with automatic validation, see `toolwright run`.

  Examples:
    # Resolve all paths from a toolpack
    toolwright serve --toolpack .toolwright/toolpacks/<id>/toolpack.yaml

    # With explicit manifest   toolwright serve --tools tools.json --policy
    policy.yaml

    # Expose a curated toolset   toolwright serve --toolpack toolpack.yaml
    --toolset readonly

    # With upstream API configuration   toolwright serve --toolpack
    toolpack.yaml --base-url https://api.example.com

    # Dry run mode (no actual API calls)   toolwright serve --toolpack
    toolpack.yaml --dry-run

  Claude Desktop configuration (see Claude Desktop docs for your platform):
    {
      "mcpServers": {
        "my-api": {
          "command": "toolwright",
          "args": ["serve", "--toolpack", "/path/to/toolpack.yaml"]
        }
      }
    }

Options:
  -t, --tools PATH                Path to tools.json manifest
  --toolpack PATH                 Path to toolpack.yaml (resolves
                                  manifest/policy/toolsets paths)
  --toolsets PATH                 Path to toolsets.yaml (defaults to sibling
                                  of --tools if present)
  --toolset TEXT                  Named toolset to expose (defaults to
                                  readonly when toolsets.yaml exists)
  -p, --policy PATH               Path to policy.yaml (optional)
  -l, --lockfile PATH             Path to approved lockfile (required by
                                  default unless --unsafe-no-lockfile)
  --base-url TEXT                 Base URL for upstream API (overrides
                                  manifest hosts)
  --auth TEXT                     Authorization header value for upstream
                                  requests (also reads TOOLWRIGHT_AUTH_HEADER
                                  env var)
  -H, --extra-header TEXT         Extra header to inject into upstream
                                  requests (repeatable, format: 'Name: value')
  --audit-log PATH                Path for audit log file
  --dry-run                       Evaluate policy but don't execute upstream
                                  calls
  --confirm-store PATH            Path to local out-of-band confirmation store
  --allow-private-cidr TEXT       Allow private CIDR targets (repeatable;
                                  default denies private ranges)
  --allow-redirects               Allow redirects (each hop is re-validated
                                  against allowlists)
  --unsafe-no-lockfile            Allow runtime without approved lockfile
                                  (unsafe escape hatch)
  --rules-path PATH               Path to behavioral rules JSON file (enables
                                  CORRECT pillar runtime enforcement)
  --circuit-breaker-path PATH     Path to circuit breaker state JSON file
                                  (enables KILL pillar runtime enforcement)
  --watch                         Enable continuous health monitoring
                                  (reconciliation loop)
  --watch-config PATH             Path to watch config YAML (default:
                                  .toolwright/watch.yaml)
  --auto-heal [off|safe|all]      Auto-heal policy (requires --watch): off,
                                  safe, or all
  --verbose-tools                 Use full verbose tool descriptions instead
                                  of compact ones
  --tool-filter TEXT              Glob pattern to filter tools by name (e.g.
                                  'get_*')
  --max-risk [low|medium|high|critical]
                                  Maximum risk tier to expose (filters out
                                  higher-risk tools)
  -s, --scope TEXT                Comma-separated tool groups to serve (e.g.,
                                  'products,orders'). Use 'toolwright groups
                                  list' to see available groups.
  --no-tool-limit                 Override the 200-tool safety limit. Not
                                  recommended.
  --schema-validation [strict|warn|off]
                                  Output schema validation mode: strict
                                  (client validates), warn (lenient, default),
                                  off (skip)  [default: warn]
  --shape-baselines PATH          Path to shape_baselines.json for autonomous
                                  drift probing (requires --watch)
  --shape-probe-interval INTEGER  Interval in seconds between shape drift
                                  probes (requires --shape-baselines)
                                  [default: 300]
  --http                          Use HTTP transport (StreamableHTTP) instead
                                  of stdio
  --host TEXT                     Host to bind the HTTP server to (requires
                                  --http)  [default: 127.0.0.1]
  --port INTEGER                  Port for the HTTP server (requires --http)
                                  [default: 8745]
  --help                          Show this message and exit.
Usage: toolwright gate [OPTIONS] COMMAND [ARGS]...

  Approve or block tools via lockfile-based governance.

Options:
  --help  Show this message and exit.

Commands:
  allow     Approve one or more tools for use.
  block     Block one or more tools.
  check     Check if all tools are approved (CI gate).
  reseal    Re-sign existing approval signatures (migration / repair...
  snapshot  Materialize a baseline snapshot for an approved lockfile.
  status    List tool approvals from the lockfile.
  sync      Sync lockfile with a tools manifest.
Usage: toolwright gate allow [OPTIONS] [TOOL_IDS]...

  Approve one or more tools for use.

  Examples:
    toolwright gate allow get_users create_user
    toolwright gate allow --all --toolpack toolpack.yaml
    toolwright gate allow --all
    toolwright gate allow get_users --by security@example.com

Options:
  --toolpack PATH      Path to toolpack.yaml (auto-resolves lockfile path)
  -l, --lockfile PATH  Path to lockfile (default: ./toolwright.lock.yaml)
  --all                Approve all pending tools
  -y, --yes            Skip confirmation prompt (required with --all)
  --toolset TEXT       Approve tools within a specific toolset
  --by TEXT            Who is approving (default: $USER)
  --reason TEXT        Approval reason (recorded in lockfile signature
                       metadata)
  --help               Show this message and exit.
Usage: toolwright gate status [OPTIONS]

  List tool approvals from the lockfile.

  Examples:
    toolwright gate status
    toolwright gate status --toolpack toolpack.yaml
    toolwright gate status --status pending
    toolwright gate status --by-group --toolpack toolpack.yaml

Options:
  --toolpack PATH                 Path to toolpack.yaml (auto-resolves
                                  lockfile path)
  -l, --lockfile PATH             Path to lockfile (default:
                                  ./toolwright.lock.yaml)
  -s, --status [pending|approved|rejected]
                                  Filter by approval status
  --by-group                      Show approval summary grouped by tool group
  --help                          Show this message and exit.
Usage: toolwright rules [OPTIONS] COMMAND [ARGS]...

  Manage behavioral rules for tool usage constraints.

Options:
  --rules-path PATH  Path to the behavioral rules JSON file.  [default:
                     .toolwright/rules.json]
  --help             Show this message and exit.

Commands:
  activate  Activate a DRAFT or DISABLED rule.
  add       Add a new behavioral rule.
  disable   Disable an ACTIVE rule.
  drafts    List behavioral rules in DRAFT status.
  export    Export all rules to a JSON file.
  import    Import rules from a JSON file.
  list      List all behavioral rules.
  remove    Remove a behavioral rule by ID.
  show      Show details of a specific rule.
  template  Manage rule templates.
Usage: toolwright rules add [OPTIONS]

  Add a new behavioral rule.

Options:
  -k, --kind [prerequisite|prohibition|parameter|sequence|rate|approval]
                                  Rule kind.  [required]
  -t, --target TEXT               Target tool IDs (repeatable).
  -d, --description TEXT          Rule description.  [required]
  --requires TEXT                 Required tool IDs (for prerequisite rules).
  --max-calls INTEGER             Maximum call count (for rate rules).
  --param-name TEXT               Parameter name (for parameter rules).
  --allowed-values TEXT           Comma-separated allowed values (for
                                  parameter rules).
  --blocked-values TEXT           Comma-separated blocked values (for
                                  parameter rules).
  --pattern TEXT                  Regex pattern for parameter validation (for
                                  parameter rules).
  --rule-id TEXT                  Custom rule ID (auto-generated if omitted).
  --help                          Show this message and exit.
Usage: toolwright rules template [OPTIONS] COMMAND [ARGS]...

  Manage rule templates.

Options:
  --help  Show this message and exit.

Commands:
  apply  Apply a rule template to the active toolpack.
  list   List available rule templates.
  show   Show details of a rule template.
Usage: toolwright recipes [OPTIONS] COMMAND [ARGS]...

  Browse and use bundled API recipes.

Options:
  --help  Show this message and exit.

Commands:
  list  List available API recipes.
  show  Show details of an API recipe.
Usage: toolwright groups [OPTIONS] COMMAND [ARGS]...

  List and inspect auto-generated tool groups.

Options:
  --help  Show this message and exit.

Commands:
  list  List all tool groups with their tool counts.
  show  Show tools in a specific group.
Usage: toolwright auth [OPTIONS] COMMAND [ARGS]...

  Manage authentication profiles and check auth configuration.

Options:
  --help  Show this message and exit.

Commands:
  check   Check auth configuration for the active toolpack.
  clear   Delete an auth profile.
  list    List all auth profiles.
  login   Launch headful browser for one-time login, saving storage state.
  status  Show the status of an auth profile.
Usage: toolwright auth check [OPTIONS]

  Check auth configuration for the active toolpack.

  Verifies that the correct env vars are set for each host in the toolpack's
  allowed_hosts list. By default, also probes each host with a lightweight GET
  to verify the token works.

  \b Examples:   toolwright auth check                  # Check auth + probe
  toolwright auth check --no-probe       # Check env vars only   toolwright
  auth check --toolpack tp.yaml

Options:
  --toolpack PATH  Path to toolpack.yaml (auto-resolves if omitted)
  --no-probe       Skip HTTP probing (check env vars only)
  --help           Show this message and exit.
Usage: toolwright config [OPTIONS]

  Print a ready-to-paste MCP client config snippet (Claude, Cursor, Codex).

Options:
  --toolpack PATH             Path to toolpack.yaml (auto-resolved if not
                              given)
  --name TEXT                 Override the MCP server name (defaults to
                              toolpack_id)
  --format [json|yaml|codex]  Output format for config snippet  [default:
                              json]
  --help                      Show this message and exit.

  Examples:
    toolwright config --toolpack toolpack.yaml
    toolwright config --toolpack toolpack.yaml --format yaml
    toolwright config --toolpack toolpack.yaml --name my-api
    toolwright config --toolpack toolpack.yaml --format codex
Usage: toolwright drift [OPTIONS]

  Detect drift between captures or against a baseline.

  Examples:
    toolwright drift --from cap_old --to cap_new
    toolwright drift --baseline baseline.json --capture-id cap_new
    toolwright drift --shape-baselines shape_baselines.json
    toolwright drift --shape-baselines shape_baselines.json --tool get_products --response-file response.json

Options:
  --from TEXT                     Source capture ID
  --to TEXT                       Target capture ID
  --baseline PATH                 Baseline file path
  --capture-id TEXT               Capture ID to compare against baseline
  --capture-path PATH             Capture path to compare against baseline
  -c, --capture TEXT              Deprecated alias for --capture-id/--capture-
                                  path
  --shape-baselines PATH          Shape baselines file for response drift
  --tool TEXT                     Tool name for shape-based drift detection
  --response-file PATH            JSON response body file for shape drift
  -o, --output PATH               Output directory (defaults to
                                  <root>/reports)
  -f, --format [json|markdown|both]
                                  Report format
  --deterministic / --volatile-metadata
                                  Deterministic drift output by default; use
                                  --volatile-metadata for ephemeral
                                  IDs/timestamps  [default: deterministic]
  --help                          Show this message and exit.
Usage: toolwright repair [OPTIONS] COMMAND [ARGS]...

  Diagnose, plan, and apply fixes for a governed toolpack.

  Subcommands:
    diagnose  Diagnose issues from audit logs, drift, and verify reports
    plan      Show the current repair plan (Terraform-style)
    apply     Apply patches from the repair plan

Options:
  --help  Show this message and exit.

Commands:
  apply     Apply patches from the current repair plan.
  diagnose  Diagnose issues and propose fixes for a governed toolpack.
  plan      Show the current repair plan (Terraform-style output).
Usage: toolwright repair plan [OPTIONS]

  Show the current repair plan (Terraform-style output).

  Reads the repair plan from .toolwright/state/repair_plan.json and displays
  patches grouped by safety level: SAFE, APPROVAL_REQUIRED, MANUAL.

  \b Examples:   toolwright repair plan   toolwright repair plan --root
  /path/to/project

Options:
  --root PATH  Project root (default: auto-detect)
  --help       Show this message and exit.
Usage: toolwright kill [OPTIONS] TOOL_ID

  Kill a tool by forcing its circuit breaker open.

  The tool will be blocked from execution until manually re-enabled with
  `toolwright enable`.

  Examples:
    toolwright kill dangerous_tool --reason "broken endpoint"
    toolwright kill search --reason "rate limiting detected"

Options:
  -r, --reason TEXT     Reason for killing the tool.
  --breaker-state PATH  Path to circuit breaker state file.
  -y, --yes             Skip confirmation prompt.
  --help                Show this message and exit.
Usage: toolwright enable [OPTIONS] TOOL_ID

  Re-enable a killed tool by resetting its circuit breaker.

  Examples:
    toolwright enable dangerous_tool

Options:
  --breaker-state PATH  Path to circuit breaker state file.
  --help                Show this message and exit.
Usage: toolwright quarantine [OPTIONS]

  List all tools with open or half-open circuit breakers.

  Shows tools that are currently blocked or in recovery mode.

  Examples:
    toolwright quarantine

Options:
  --breaker-state PATH  Path to circuit breaker state file.
  --help                Show this message and exit.
Usage: toolwright health [OPTIONS]

  Probe endpoint health for all tools in a manifest.

  Sends non-mutating probes (HEAD/OPTIONS) to each endpoint and reports
  status, response time, and failure classification.

  Exits 0 if all healthy, 1 if any unhealthy.

  \b Examples:   toolwright health --tools output/tools.json   toolwright
  health --tools my-api/tools.json

Options:
  --tools PATH  Path to tools.json manifest.  [required]
  --help        Show this message and exit.
Usage: toolwright verify [OPTIONS]

  Run verification contracts (replay, outcomes, provenance).

Options:
  --toolpack PATH                 Path to toolpack.yaml (auto-resolved if not
                                  given)
  --mode [contracts|baseline-check|replay|outcomes|provenance|all]
                                  Verification mode  [default: all]
  --lockfile PATH                 Optional lockfile override (pending allowed)
  --playbook PATH                 Path to deterministic playbook
  --ui-assertions PATH            Path to UI assertion list
  -o, --output PATH               Output directory for verification reports
                                  (defaults to <root>/reports)
  --strict / --no-strict          Strict gating mode  [default: strict]
  --top-k INTEGER                 Top candidate APIs per assertion  [default:
                                  5]
  --min-confidence FLOAT          Minimum confidence threshold for provenance
                                  pass  [default: 0.7]
  --unknown-budget FLOAT          Maximum ratio of unknown provenance
                                  assertions before gating  [default: 0.2]
  --help                          Show this message and exit.

  Examples:
    toolwright verify --toolpack toolpack.yaml
    toolwright verify --toolpack toolpack.yaml --mode baseline-check
    toolwright verify --toolpack toolpack.yaml --mode contracts --strict
    toolwright verify --toolpack toolpack.yaml --mode provenance
Usage: toolwright ship [OPTIONS] [URL]

  Ship a governed agent end-to-end.

  The flagship guided lifecycle: capture, review, approve, snapshot, verify,
  and serve — all in one flow.

  Optionally pass a URL to run the automated path (capture + compile + smart
  approve + serve). Without a URL, runs the interactive flow.

  Examples:
    toolwright ship                                      # Interactive
    toolwright ship https://app.example.com -a api.example.com  # Automated

Options:
  -a, --allowed-host TEXT  API host(s) to capture (used with URL argument)
  --help                   Show this message and exit.
Usage: toolwright status [OPTIONS]

  Show governance status for a toolpack.

  The compass command — always-available orientation showing lockfile state,
  baseline, drift, verification, pending approvals, alerts, and recommended
  next action.

  Examples:
    toolwright status
    toolwright status --toolpack .toolwright/toolpacks/stripe-api/toolpack.yaml
    toolwright status --json

Options:
  --toolpack PATH  Path to toolpack.yaml (auto-discovered if not given)
  --json           Output status as JSON to stdout
  --help           Show this message and exit.
Usage: toolwright diff [OPTIONS]

  Generate a risk-classified change report.

Options:
  --toolpack PATH                 Path to toolpack.yaml (auto-resolved if not
                                  given)
  --baseline PATH                 Baseline toolpack.yaml or snapshot directory
  -o, --output PATH               Output directory for diff artifacts
  --format [json|markdown|github-md|both]
                                  Diff output format  [default: both]
  --help                          Show this message and exit.
Usage: toolwright doctor [OPTIONS]

  Validate toolpack readiness for execution.

Options:
  --toolpack PATH                 Path to toolpack.yaml  [required]
  --runtime [auto|local|container]
                                  Runtime to validate  [default: auto]
  --help                          Show this message and exit.