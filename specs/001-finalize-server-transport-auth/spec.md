# Feature Specification: Finalize MCP Server Transport & Auth (Local Run)

**Feature Branch**: `001-finalize-server-transport-auth`
**Created**: 2026-05-31
**Status**: Draft
**Input**: User description: "Read SPEC.md, then finalize src/server.py's transport and auth against the current MCP Python SDK and Anthropic custom-connector docs, and get it running locally."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Server runs locally and serves the three tools (Priority: P1)

As the project owner, I want to start the Strava Coach MCP server on my laptop
with a single command, so that I can confirm the three tools — recent
activities, weekly summary, and activity detail — return compact, correctly
shaped responses against my real Strava data before I touch the EC2 deploy.

**Why this priority**: Nothing in this project — auth gating, EC2 deploy,
claude.ai connector wiring — matters until the server actually starts and
responds. A working local invocation is the MVP that proves the chosen
transport in the MCP Python SDK is real, current, and compatible with the
existing tool definitions.

**Independent Test**: Set the required environment variables in a local `.env`,
run the start command from the project root, point a local MCP client (e.g.,
MCP Inspector) at the configured local URL, and successfully call each of the
three tools. Each response must parse as JSON and contain the expected
top-level fields. Delivers value because the project owner can now exercise
the full read-only Strava workflow without exposing anything publicly.

**Acceptance Scenarios**:

1. **Given** a populated `.env` with Strava credentials and a path secret,
   **When** the start command is run from the project root,
   **Then** the server reports a ready state within a few seconds and listens
   on a loopback interface at the configured port.
2. **Given** a running local server,
   **When** an MCP client invokes `list_recent_activities` with `limit=5`,
   **Then** the response is parseable JSON containing up to 5 activity
   summaries with date, type, distance, duration, average pace, and average HR
   fields populated where the source data exists.
3. **Given** a running local server,
   **When** an MCP client invokes `get_weekly_summary` with `weeks=4`,
   **Then** the response is parseable JSON containing up to 4 ISO-week rollups
   with run count, kilometres, and total hours.
4. **Given** a running local server and a known recent activity id,
   **When** an MCP client invokes `get_activity_detail` for that id,
   **Then** the response is parseable JSON containing official splits, computed
   stream metrics (first/second-half HR & pace, decoupling, HR drift), and
   time-in-zone — and the response is fully derived from compact summaries,
   never raw stream arrays.

---

### User Story 2 - Path-secret auth gates the public endpoint (Priority: P2)

As the project owner, I want the MCP application mounted only under a
secret-derived URL segment, so that I can later expose the same server through
nginx without leaking the user's full Strava history to anyone who guesses the
base URL.

**Why this priority**: The constitution forbids unauthenticated public exposure
(Principle IV). The path-secret approach is the explicit fallback noted in
SPEC.md when the Anthropic custom connector cannot configure a custom auth
header. Confirming this gate works locally is what makes the eventual EC2
deploy safe — without it, the project cannot leave the laptop.

**Independent Test**: With the server running and a non-empty path secret in
the environment, send requests to the configured loopback URL using both the
correct secret path and several incorrect paths. The correct path must accept
the MCP handshake; every other path must return a response indicating the
resource does not exist, with no body content that confirms an MCP server is
running there.

**Acceptance Scenarios**:

1. **Given** a running server with `MCP_PATH_SECRET` set,
   **When** an MCP client connects to `/<secret>/mcp` on the loopback URL,
   **Then** the handshake succeeds and tools become callable.
2. **Given** a running server with `MCP_PATH_SECRET` set,
   **When** a client requests `/mcp`, `/wrong-secret/mcp`, or `/`,
   **Then** the response status is 404 and the body does not disclose that an
   MCP server is mounted elsewhere on this host.
3. **Given** an environment where `MCP_PATH_SECRET` is unset or empty,
   **When** the start command is run,
   **Then** the server refuses to start and emits a clear error message naming
   the missing variable; the process exits with a non-zero status.

---

### User Story 3 - End-to-end smoke test through a public tunnel (Priority: P3)

As the project owner, I want to confirm a real claude.ai custom connector can
reach the locally-running server through a short-lived HTTPS tunnel, so that
I have proof the chosen transport and auth combination works against the
actual Anthropic connector flow before committing to the EC2 deploy.

**Why this priority**: This story exercises the full path — connector → TLS
tunnel → secret path → MCP transport → tool — which catches mismatches between
training-time assumptions and current connector behavior. It is not required
to call User Story 1 done, but it shortens the feedback loop dramatically and
is the cheapest way to satisfy constitution Principle V (verify live docs).

**Independent Test**: Start the server locally per User Story 1, expose it
through any HTTPS tunnel that issues a valid certificate, register the
resulting `https://.../<secret>/mcp` URL as a custom connector in claude.ai,
and invoke each tool from a Claude chat. Each invocation must succeed and
return a compact JSON payload.

**Acceptance Scenarios**:

1. **Given** the server is running locally behind an HTTPS tunnel,
   **When** the tunnel URL with the secret path is registered as a claude.ai
   custom connector,
   **Then** the connector reports a successful health/connection state.
2. **Given** the connector is connected,
   **When** the project owner asks Claude to list recent activities or fetch a
   weekly summary,
   **Then** Claude invokes the corresponding tool and incorporates the
   returned compact JSON into its reply.

---

### Edge Cases

- **MCP SDK transport name drift**: the installed `mcp` package may use a
  different transport identifier than the one currently in code. The server
  must fail fast at startup with an actionable error rather than crashing on
  first request.
- **Short or weak path secret**: a path secret that is too short undermines
  the auth gate. The server should enforce a minimum length (e.g., 24
  characters) and reject startup otherwise.
- **Expired Strava refresh token**: if the seed refresh token in `.env` is
  revoked, tool calls should surface a clear error mentioning re-running the
  one-time OAuth step, not a generic 500.
- **Strava token rotation**: when Strava returns a rotated refresh token, the
  server must persist the new value; failure to persist causes the next
  startup to fail authentication.
- **Loopback vs all-interfaces binding**: defaulting to bind on all interfaces
  in local mode would expose the server on the LAN. The default must be
  loopback only; binding to `0.0.0.0` requires an explicit env-var opt-in
  intended for the EC2 path.
- **Request to a path that prefixes the secret** (e.g., `/<secret>` without
  `/mcp`): must 404 cleanly, not leak that the secret is recognised.
- **Anthropic connector OAuth attempt**: if the connector ever attempts an
  OAuth handshake against a path-secret URL, the server should return a
  static 404 on those routes rather than partially handshaking.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Server MUST start with a single documented command run from the
  project root and report a "ready" state via stdout or structured log.
- **FR-002**: Server MUST expose the three existing MCP tools
  (`list_recent_activities`, `get_weekly_summary`, `get_activity_detail`) over
  the current MCP streamable-HTTP transport supported by the installed SDK.
- **FR-003**: Before code is finalised, the implementer MUST verify the MCP
  Python SDK transport API and the Anthropic custom-connector auth options
  against current official documentation and cite the consulted doc URLs in
  the implementation plan or pull-request description.
- **FR-004**: Server MUST mount the MCP application only under a URL segment
  derived from the `MCP_PATH_SECRET` environment variable. Requests to any
  other path MUST return a 404 with a body that does not reveal an MCP server
  is mounted elsewhere.
- **FR-005**: Server MUST refuse to start when `MCP_PATH_SECRET` is unset,
  empty, or shorter than a minimum length (24 characters); the process MUST
  exit non-zero with a clear error naming the violated constraint.
- **FR-006**: Server MUST default to binding the loopback interface
  (`127.0.0.1`) on a configurable port (default `8080`). Binding to any
  non-loopback interface MUST require an explicit opt-in environment variable.
- **FR-007**: Each tool response MUST remain compact — no raw per-second
  stream arrays — as already enforced by the metrics computation modules; the
  server MUST NOT introduce any code path that returns raw stream data to the
  client.
- **FR-008**: A repeatable local smoke procedure MUST exist (script or
  documented sequence) that invokes all three tools against the running server
  and asserts each response parses as JSON with the expected top-level fields.
- **FR-009**: Server MUST exercise Strava refresh-token rotation through the
  existing client module; rotated tokens MUST be persisted so the next start
  succeeds without manual intervention.
- **FR-010**: The local-run command, required environment variables, and the
  connector URL format MUST be discoverable from the repository (e.g., a
  README or quickstart section co-located with the spec).
- **FR-011**: Startup MUST validate that the installed MCP SDK version
  supports the transport identifier used in code and emit an actionable error
  if not (e.g., "transport 'streamable-http' not supported by mcp X.Y — see
  <doc URL>").
- **FR-012**: When a Strava call fails due to an invalid or expired refresh
  token, the failing tool MUST return an error string that names the
  underlying cause and points to the one-time OAuth re-seeding step.

### Key Entities

- **MCP Tool**: One of the three callable endpoints exposed by the server;
  each has a name, parameter shape, and a compact JSON response contract.
- **Path Secret**: A high-entropy string carried in the connector URL that
  gates access to the MCP mount point; functions as a bearer credential over
  TLS.
- **Strava Credentials**: The client id, client secret, and current refresh
  token used by the Strava client module; the refresh token rotates over time
  and must be persisted across server restarts.
- **Activity Cache Record**: A row in SQLite representing one Strava activity
  with its compact summary fields; the canonical source for
  `list_recent_activities` and `get_weekly_summary`.
- **Activity Metrics Record**: A cached, per-activity computed payload
  (splits, half-by-half HR/pace, decoupling, drift, time-in-zone) returned by
  `get_activity_detail`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A contributor with Strava credentials in hand can clone the
  repository, follow the documented local-run instructions, and successfully
  invoke all three tools in **under 15 minutes** end-to-end.
- **SC-002**: Each tool response for a typical 1-hour run fits within
  **4 KB** of JSON, confirming the compact-response contract holds for the
  shape that will be consumed in chat.
- **SC-003**: **100%** of requests that omit or mis-state the path secret
  receive a not-found response, and **0** responses leak information that
  reveals where the MCP mount lives.
- **SC-004**: Cold server startup completes in **under 5 seconds** from the
  start command to the ready signal on a developer laptop.
- **SC-005**: The smoke procedure exercises all three tools and completes in
  **under 30 seconds** against a populated cache.
- **SC-006**: Startup with a missing, empty, or too-short path secret fails
  **100%** of the time with an exit code of 1 and a single-line error message
  that names the violated constraint.
- **SC-007**: A maintainer reviewing the implementation can find the cited
  current-doc URLs for both the MCP transport choice and the connector auth
  choice in the plan or PR description **without leaving the repository**.

## Assumptions

- The user has Claude Max and access to claude.ai custom connectors; this
  spec does not need to verify Max subscription state.
- The user already holds Strava API app credentials and has completed the
  one-time OAuth with `activity:read_all` scope; seeding `.env` from a prior
  refresh token is in scope; first-time OAuth bootstrapping is out of scope.
- The existing modules `src/strava.py`, `src/cache.py`, and `src/metrics.py`
  are stable and reused as-is per constitution Principle VI; this feature
  touches only `src/server.py` and supporting run/smoke documentation.
- The path-secret auth scheme is the chosen approach for v1; an OAuth-based
  alternative is acknowledged as a possible future upgrade and is out of
  scope for this feature.
- Local run is performed on macOS or Linux with Python 3.11+; Windows is out
  of scope.
- An HTTPS tunnel suitable for the optional User Story 3 (cloudflared, ngrok,
  or equivalent) is available to the project owner; this feature does not
  prescribe a specific tunnel tool.
- The EC2 deployment path (`deploy/` nginx vhost, systemd unit, certbot
  setup) is out of scope for this feature and will be exercised in a later
  feature once the local run is proven.
