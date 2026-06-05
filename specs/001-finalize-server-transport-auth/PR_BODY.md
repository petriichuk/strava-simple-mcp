# Finalize MCP server transport & auth (local run)

Closes scope of feature `001-finalize-server-transport-auth`. Server now boots
with a single `python src/server.py`, mounts the existing three MCP tools
under `/<MCP_PATH_SECRET>/mcp`, and refuses to start when the path-secret or
bind host violate the contract in
[`contracts/mount-and-auth.md`](specs/001-finalize-server-transport-auth/contracts/mount-and-auth.md).

## Summary

- `src/server.py` rewritten: env-loading via `python-dotenv`, MCP SDK
  version gate (FR-011), path-secret + loopback-bind validators (FR-005,
  FR-006), streamable-HTTP mount at `/<secret>/mcp` (FR-002, FR-004),
  log-redaction middleware (no path in logs), and a per-tool error envelope
  translating Strava 401/404/5xx/network failures into named codes
  (FR-012).
- `scripts/smoke.py` (new): drives all three tools via `mcp` client over
  streamable HTTP, asserts response shape from
  [`contracts/mcp-tools.md`](specs/001-finalize-server-transport-auth/contracts/mcp-tools.md),
  asserts no top-level array exceeds 200 elements (structural FR-007 check),
  and optionally measures cold-start (SC-004).
- `scripts/smoke_auth.py` (new): probes 4 mis-spelt paths for 404
  indistinguishability and forks 3 bad-startup configs (missing /
  short / non-loopback) and asserts exit code 1.
- `requirements.txt`: floored at `mcp>=1.8.0`, added `python-dotenv>=1.0.0`.
- `.env.example`: added MCP_HOST / MCP_PORT / commented MCP_ALLOW_PUBLIC_BIND
  and the `python -c "import secrets; print(secrets.token_urlsafe(32))"`
  generator hint.
- `CLAUDE.md`, `.gitignore`: created/updated.

`src/strava.py`, `src/cache.py`, `src/metrics.py` are **unchanged** per
constitution Principle VI (reuse stable modules). Tool function bodies in
`src/server.py` are preserved verbatim and wrapped only in the new
error-envelope try/except.

## Verified

| Check                                          | Result   |
| ---------------------------------------------- | -------- |
| Python syntax on all 3 files                   | `py_compile` clean |
| MCP handshake over streamable HTTP             | ok — 3 tools registered |
| Cold-start `READY:` line                       | **0.35 s** (budget 5 s, SC-004) |
| 4 probe paths return 404 with clean body       | ok (SC-003) |
| 3 bad-startup configs exit code 1              | ok in **0.28 s each** (budget 3 s, SC-006) |
| Path secret absent from server logs            | `grep -c` returns 0 (FR-004) |
| Error envelope on a dummy-cred Strava failure  | returned `{"error": "internal", ...}` cleanly (T014) |

## Live-doc citations (constitution Principle V, SC-007)

Verified on 2026-05-31 against the following current sources:

**MCP Python SDK — streamable HTTP transport (research R1, R2, R4):**

- https://github.com/modelcontextprotocol/python-sdk
- https://pypi.org/project/mcp/
- https://pypi.org/project/mcp/1.8.0/

Implementation note: the simpler `mcp.settings.streamable_http_path = "/<secret>/mcp"`
+ `mcp.streamable_http_app()` path avoids the parent-mount lifespan bug
called out in
https://github.com/modelcontextprotocol/python-sdk/issues/1367 and
https://github.com/modelcontextprotocol/python-sdk/issues/673 by keeping the
secret-prefix routing inside the FastMCP-generated Starlette app.

**Anthropic claude.ai custom-connector auth (research R5, R6):**

- https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
- https://claude.com/docs/connectors/building
- https://github.com/anthropics/claude-ai-mcp/issues/110
- https://github.com/anthropics/claude-ai-mcp/issues/112
- https://modelcontextprotocol.io/docs/develop/connect-remote-servers

Confirmed: claude.ai custom-connector UI supports authless or OAuth 2.1 +
PKCE only. Path-secret-in-URL is the unofficial fallback chosen for v1 (per
2026-05-31 product-owner decision). OAuth 2.1 + PKCE is the explicit
follow-up before any multi-user exposure.

## Constitution alignment

All six principles in
[`.specify/memory/constitution.md`](.specify/memory/constitution.md) v1.0.0
verified — see the Constitution Check table in
[`plan.md`](specs/001-finalize-server-transport-auth/plan.md).

## Outstanding (user action)

The following items in [`tasks.md`](specs/001-finalize-server-transport-auth/tasks.md)
need the project owner to complete with real Strava credentials and access
to a claude.ai workspace:

- **T009** (live smoke against real Strava data — shape assertions, size
  budgets, FR-009 token rotation)
- **T017–T018** (end-to-end through cloudflared/ngrok + claude.ai custom
  connector)
- **T020** (compact-size audit on the longest representative activity —
  SC-002 upper edge)

These are non-blocking for code review but should be completed before the
EC2 deploy feature is scoped.
