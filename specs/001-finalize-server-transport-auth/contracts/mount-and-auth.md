# Contract: Mount Path & Auth Behaviour

**Feature**: `001-finalize-server-transport-auth`
**Date**: 2026-05-31
**Scope**: The HTTP-level contract the server presents to a client (MCP
Inspector locally, claude.ai connector via tunnel, or nginx → FastMCP in
production). This contract is the user-observable surface of FR-004 through
FR-006 and FR-011.

---

## URL surface

Let `SECRET = $MCP_PATH_SECRET` (URL-safe ASCII, ≥ 24 chars).

| Request                                | Response                                   |
| -------------------------------------- | ------------------------------------------ |
| `POST /<SECRET>/mcp/...` (handshake)   | MCP protocol response (200/SSE chunks)     |
| `GET  /<SECRET>/mcp/...`               | MCP protocol response                      |
| `OPTIONS /<SECRET>/mcp/...`            | Whatever the SDK responds (CORS preflight) |
| any other path (`/`, `/mcp`, `/health`, `/<wrong-secret>/...`, `/<SECRET>`) | `404 Not Found`, empty or generic body |

**Contractual properties**:
- The 404 body MUST NOT differ between "secret missing" and "secret wrong"
  responses. Both look identical to a probing client.
- The 404 body MUST NOT include the string `"mcp"`, the project name, or any
  hint that an MCP server is mounted elsewhere on this host.
- The server MUST NOT add headers that distinguish the wrong-secret 404 from
  the no-route-here 404 (e.g., no `X-MCP-Reason` header).

**Reserved status codes**:
- The server MUST NOT use `401` or `403` on the gating path — they would
  signal "this would work if you had the right credential" and reveal the
  endpoint.

---

## Startup contract

The startup sequence:

1. Load `.env` (via `python-dotenv` or equivalent — already in
   `requirements.txt` patterns).
2. Read `MCP_PATH_SECRET`. If missing, empty, or `len < 24`:
   - Write to stderr: `ERROR: MCP_PATH_SECRET must be set and ≥ 24 chars`.
   - Exit with code `1`.
3. Read `MCP_HOST` (default `127.0.0.1`) and `MCP_PORT` (default `8080`).
4. If `MCP_HOST != "127.0.0.1"` (or `::1`) and `MCP_ALLOW_PUBLIC_BIND` is not
   set to `"1"`:
   - Write to stderr: `ERROR: refusing to bind <host>; set MCP_ALLOW_PUBLIC_BIND=1 to opt in`.
   - Exit with code `1`.
5. Verify the installed `mcp` package version supports the streamable-HTTP
   transport (e.g., by attempting to import `FastMCP` and checking the
   package version is `>= 1.8.0`). On mismatch, write a single-line error
   naming the installed version, the required floor, and the doc URL from
   research R1. Exit `1`.
6. Initialise the SQLite cache (`cache.init_db()`).
7. Construct `FastMCP("strava-coach", host=MCP_HOST, port=MCP_PORT,
   streamable_http_path="/")`.
8. Construct a Starlette parent app:
   - Mount the MCP application under `/<SECRET>` using the
     `StreamableHTTPSessionManager` + parent-lifespan pattern from research
     R2 (NOT the bare `Mount(..., app=streamable_http_app())` shortcut).
   - All other routes: catch-all returning `404`.
9. Print one ready-state log line including the bound host, port, and
   redacted mount path (e.g.,
   `READY: strava-coach @ 127.0.0.1:8080/<MCP_PATH_SECRET:redacted>/mcp`).
10. Serve until SIGINT/SIGTERM.

**Total cold start budget**: ≤ 5 s (SC-004), from process entry to step 9.

**Exit codes**:
- `0` — clean shutdown on SIGINT/SIGTERM.
- `1` — any startup validation failure (missing secret, weak secret,
  unsafe bind, unsupported SDK version, SQLite init failure).
- `2` — reserved for future use; not emitted in v1.

---

## Log redaction contract

The server MUST NOT emit `MCP_PATH_SECRET`, `STRAVA_CLIENT_SECRET`, or any
Strava token value to any log destination. The ready-state line above
specifies how to render the secret prefix safely.

If the underlying ASGI / uvicorn logger logs the full request path by
default, it MUST be configured to either:
- log only the route name / status (not the path), or
- redact path segments preceding `/mcp`.

This is a hard requirement because access logs are routinely shipped to
nginx → CloudWatch / journalctl, where the secret would otherwise leak.

---

## Connector URL format (for downstream documentation)

The full URL the operator pastes into the claude.ai custom-connector dialog
is:

```
https://<public-host>/<MCP_PATH_SECRET>/mcp
```

- `<public-host>` is the cloudflared/ngrok tunnel hostname (User Story 3) or
  the EC2 domain (future deploy feature).
- The path always ends with `/mcp` — that suffix is the streamable-HTTP
  endpoint inside the mounted FastMCP app.

Quickstart.md restates this in concrete form for User Story 3 setup.
