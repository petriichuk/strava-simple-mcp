# Research: Finalize MCP Server Transport & Auth

**Feature**: `001-finalize-server-transport-auth`
**Date**: 2026-05-31
**Purpose**: Resolve the two volatile-surface unknowns called out in SPEC.md
and required by constitution Principle V (verify live docs): (a) the current
MCP Python SDK transport API, and (b) the auth options supported by the
Anthropic claude.ai custom-connector flow.

All NEEDS CLARIFICATION items below resolve to **Decision / Rationale /
Alternatives** triples. URLs cited are the doc sources consulted on
2026-05-31; principle V also requires they appear in the PR description.

---

## R1. MCP Python SDK — streamable HTTP transport identifier

**Decision**: Use `transport="streamable-http"` (hyphen, lowercase) when
invoking `FastMCP.run(...)`. Pin `mcp>=1.8.0` in `requirements.txt`; floor at
`1.27.0` is preferred for the 2026 line.

**Rationale**: The current `mcp` PyPI package (1.27.2 on 2026-05-29) dispatches
only three transport strings in `FastMCP.run`: `"stdio"` (default), `"sse"`
(legacy, deprecated), and `"streamable-http"`. The hyphenated form is the only
accepted identifier for streamable HTTP. Streamable HTTP shipped in 1.8.0
(2025-05-08) — earlier versions cannot serve this transport at all.

**Alternatives considered**:
- `"streamable_http"` / `"http"` — rejected; not accepted by the dispatcher.
  `"http"` does appear in client tooling (`claude mcp add --transport http`)
  but is not a server-side transport keyword.
- `"sse"` — rejected; legacy, being deprecated by both the SDK and Anthropic's
  connector. New servers should not start there.

**Sources**:
- https://github.com/modelcontextprotocol/python-sdk (README, "Streamable HTTP Transport")
- https://pypi.org/project/mcp/
- https://pypi.org/project/mcp/1.8.0/

---

## R2. MCP Python SDK — mounting under a custom (secret) path

**Decision**: Mount the MCP ASGI app under the secret-derived prefix using a
`StreamableHTTPSessionManager` instance plus an `AsyncExitStack`-backed
lifespan on the parent Starlette app. **Do not** use the simpler
`Mount("/<secret>", app=mcp.streamable_http_app())` shortcut as the only
mounting mechanism.

**Rationale**: `FastMCP.streamable_http_app()` returns a Starlette ASGI app
that exposes the streamable-HTTP endpoint and is mountable. However, when
mounted as a sub-app under a Starlette/FastAPI parent, the MCP session
manager's lifespan does not get initialised through the parent's startup
flow, surfacing as `RuntimeError: Task group is not initialized` on the first
request (issues #1367, #673). The fix recommended by maintainers is to take
the session manager directly and wire its lifespan into the parent app's
`AsyncExitStack`. This pattern remains forward-compatible with `mount()` if
the lifespan bug is resolved upstream.

**Alternatives considered**:
- Mount the FastMCP app at root and rely on nginx to add the secret prefix —
  rejected; nginx path stripping is fragile and the SDK does not support
  base-URL rewriting (issue #242). Easier to bake the prefix into the
  application than to manage it in the proxy.
- Run a thin reverse proxy in-process that strips the secret before
  forwarding to a root-mounted FastMCP — rejected; gratuitous complexity for
  no gain.

**Sources**:
- https://github.com/modelcontextprotocol/python-sdk (README, "Mounting to an Existing ASGI Server")
- https://github.com/modelcontextprotocol/python-sdk/issues/1367
- https://github.com/modelcontextprotocol/python-sdk/issues/673
- https://github.com/modelcontextprotocol/python-sdk/issues/242

---

## R3. MCP Python SDK — host / port configuration

**Decision**: Configure host and port via `FastMCP(...)` constructor kwargs:
`FastMCP("strava-coach", host=host, port=port, streamable_http_path="/")`.
Read `host` and `port` from environment with safe defaults (`127.0.0.1` and
`8080`). Refuse to start on a non-loopback host unless an explicit opt-in env
variable (`MCP_ALLOW_PUBLIC_BIND=1`) is set.

**Rationale**: FastMCP exposes three equivalent configuration surfaces
(constructor kwargs, `mcp.settings.*`, and `uvicorn` flags when embedded).
Constructor kwargs keep config close to construction and avoid spreading
settings across init and runtime. The SDK has no built-in `MCP_HOST` /
`MCP_PORT` env support, so the application reads env explicitly.

**Alternatives considered**:
- Read `mcp.settings.host` / `mcp.settings.port` — equivalent at runtime but
  spreads config across the file. Rejected on readability grounds.
- Run via `uvicorn module:app` from the CLI and ignore FastMCP host/port —
  acceptable but loses single-command start (`python src/server.py`) and
  duplicates startup logic between local and EC2 paths.

**Sources**:
- https://github.com/modelcontextprotocol/python-sdk (README "Streamable HTTP Transport")

---

## R4. MCP Python SDK — minimum version pin

**Decision**: `requirements.txt` pins `mcp>=1.8.0` (the minimum that supports
streamable-HTTP) and the implementation targets `mcp>=1.27.0` for active
development. Startup will assert the installed version supports the transport
and emit an actionable error if not (FR-011).

**Rationale**: 1.8.0 is the lower bound where the feature exists; 1.27.x is
the current line. A floor of 1.27.0 trades very recent stability for the bug
fixes that landed between 1.8 and 1.27 (including several around streamable
HTTP edge cases).

**Sources**: as R1.

---

## R5. Anthropic claude.ai custom connector — auth options

**Decision**: For v1, use the **secret-in-URL-path** scheme. Path lives in
`MCP_PATH_SECRET` (minimum 24 characters of high-entropy randomness). OAuth
2.1 + PKCE is acknowledged as the Anthropic-blessed path and is deferred to
a follow-up feature.

**Rationale**: As of 2026-05-31, the claude.ai custom-connector UI exposes
only (a) the server URL and (b) Advanced Settings with `OAuth Client ID` and
`OAuth Client Secret`. There is no custom-header field; Anthropic closed the
"support custom headers" feature requests as **not planned**. The two
supported flows are: **authless** (unacceptable here — exposes the user's
Strava history publicly) and **OAuth 2.1 + PKCE** (the blessed but
significant-effort path). Path-secret is the unofficial fallback the
community uses; Anthropic does not document or endorse it.

**Trade-offs accepted (per user decision on 2026-05-31)**:
- Path-secret leaks into HTTP referrer headers, browser history, and
  server-side access logs (including nginx default logs and any
  request-logging middleware between the connector and the MCP server).
  Mitigations: never log the path in our own code; configure nginx
  `access_log` to redact the prefix; rotate the secret if it leaks.
- Secret rotation requires re-registering the connector URL in claude.ai.
  Acceptable for a single-user personal deployment.
- This is a single-user system; the blast radius of a leaked URL is the
  user's own Strava history, not other users'.

**Alternatives considered**:
- **OAuth 2.1 + PKCE now** — rejected for this feature on scope grounds.
  Implementing DCR or CIMD plus the required `.well-known/oauth-protected-resource`
  and `.well-known/oauth-authorization-server` endpoints, redirect handling at
  `https://claude.ai/api/mcp/auth_callback`, and token storage is a feature
  of its own. Deferred to a follow-up feature, ideally landed before any
  multi-user exposure.
- **Authless** — rejected; violates constitution Principle IV.
- **Static `Authorization: Bearer` header** — not configurable in the
  claude.ai connector UI.

**Sources**:
- https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
- https://claude.com/docs/connectors/building
- https://github.com/anthropics/claude-ai-mcp/issues/110
- https://github.com/anthropics/claude-ai-mcp/issues/112
- https://modelcontextprotocol.io/docs/develop/connect-remote-servers
- https://www.blockchain-council.org/claude-ai/securing-mcp-server-for-claude-auth-authorization-secret-management/

---

## R6. Anthropic claude.ai custom connector — transport

**Decision**: Streamable HTTP (matches R1). Legacy HTTP+SSE is acknowledged
as deprecated and not built against.

**Rationale**: Anthropic's "Building custom connectors" doc states: "Claude
supports both Streamable HTTP and the legacy HTTP+SSE transport. The legacy
HTTP+SSE transport is being deprecated in favor of Streamable HTTP." New
servers should target streamable HTTP exclusively.

**Sources**:
- https://claude.com/docs/connectors/building
- https://modelcontextprotocol.io/docs/develop/connect-remote-servers

---

## R7. TLS and certificate posture

**Decision**: For local-only User Story 1 testing, plain HTTP on loopback is
fine (MCP Inspector connects directly). For User Story 3 (end-to-end through
a tunnel), use **cloudflared** or **ngrok**, both of which terminate TLS with
a publicly-trusted certificate. For the future EC2 deploy, terminate TLS at
nginx with a certbot-issued cert per `deploy/`.

**Rationale**: The Anthropic connector originates from Anthropic's cloud and
will not accept self-signed certificates — only publicly-trusted CA chains
work. Tunnels and certbot satisfy this trivially.

**Sources**:
- https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp

---

## R8. Reverse-proxy guidance (forward-look for EC2, informs nginx vhost choices)

**Decision (informational for this feature; binding for the EC2 deploy
feature)**:
- Mount the secret prefix in the app, NOT in nginx. Do not strip path at the
  proxy.
- `proxy_buffering off;` to keep streamable-HTTP chunks flowing.
- `proxy_http_version 1.1;` + `proxy_set_header Connection "";` for keep-alive.
- `proxy_read_timeout 300s;` to tolerate longer tool calls.
- Expose `Mcp-Session-Id` in CORS responses if a browser client is ever used
  (not required for the claude.ai connector path).

**Rationale**: There is no maintainer-blessed nginx config in the python-sdk
repo (issue #242 still open). The community consensus and Prefect-maintained
FastMCP deployment doc converge on the settings above. Encoding them in
research now means the EC2 vhost in `deploy/` can be reviewed against this
baseline.

**Sources**:
- https://gofastmcp.com/deployment/http
- https://github.com/modelcontextprotocol/python-sdk/issues/242
- https://github.com/modelcontextprotocol/python-sdk/issues/1168

---

## Open follow-ups (carried forward, NOT blocking this feature)

- **OAuth 2.1 + PKCE feature**: Land before any multi-user exposure or a
  domain that is widely shared.
- **nginx vhost review against R8**: When the EC2 deploy feature picks up
  `deploy/nginx.conf`, audit against the proxy settings above.
- **Secret-rotation procedure**: Document a one-command rotation that
  regenerates `MCP_PATH_SECRET`, restarts the server, and reminds the
  operator to re-register the connector URL in claude.ai.
- **Access-log redaction**: Configure nginx (in the EC2 feature) to redact
  the path-secret segment from access logs.
