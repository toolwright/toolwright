"""Auth provider — runtime credential injection via environment variables.

Toolwright resolves credentials at runtime from environment variables
following the convention TOOLWRIGHT_AUTH_<NORMALIZED_HOST>. The token is
injected into upstream requests by the HTTP execution layer and never
appears in tool definitions, logs, or model context.

See toolwright/cli/commands_auth.py for the host→env-var normalization
and toolwright/mcp/action_handlers.py for the injection point.
"""
