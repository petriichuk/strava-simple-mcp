---
description: "Task list for feature 001-finalize-server-transport-auth"
---

# Tasks: Finalize MCP Server Transport & Auth (Local Run)

**Input**: Design documents from `/specs/001-finalize-server-transport-auth/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: Tests are OPTIONAL per the feature spec and constitution Workflow
section. This task list uses **smoke scripts** (`scripts/smoke.py` and
`scripts/smoke_auth.py`) as the verification mechanism in lieu of formal
pytest suites. Each user story checkpoint requires its smoke script to pass.

**Organization**: Tasks are grouped by user story to enable independent
implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- File paths are absolute from the repository root

## Path Conventions

- Project code lives in `strava-coach-mcp/` (not at the repo root). Within
  that directory, source is `src/`, smoke scripts go under `scripts/`,
  configuration is `.env` / `.env.example`, dependencies are `requirements.txt`.
- Spec/plan/research artifacts live under
  `specs/001-finalize-server-transport-auth/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Pin dependencies and surface new configuration knobs so all
subsequent work has a stable baseline.

- [X] T001 Pin `mcp>=1.8.0` (recommended floor `1.27.0`) and add `python-dotenv>=1.0.0` to `strava-coach-mcp/requirements.txt`; leave `starlette>=0.37.0`, `uvicorn>=0.30.0`, `requests>=2.31.0` in place
- [X] T002 [P] Add `MCP_HOST`, `MCP_PORT`, and a commented `# MCP_ALLOW_PUBLIC_BIND=1` line to `strava-coach-mcp/.env.example`, plus a one-line note about generating `MCP_PATH_SECRET` with `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- [X] T003 [P] Create `strava-coach-mcp/scripts/` directory (touch `.gitkeep` if needed) to host the smoke scripts

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Wire `.env` loading and SDK-version verification — everything
in Phases 3+ assumes the process starts with env vars resolved and a
transport-capable `mcp` package installed.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T004 In `strava-coach-mcp/src/server.py`, replace the bare module-level imports with a top block that calls `python-dotenv`'s `load_dotenv()` BEFORE any `os.environ.get(...)` call or any import that reads env at import time; preserve the existing tool function definitions verbatim per constitution Principle VI
- [X] T005 In `strava-coach-mcp/src/server.py`, implement `_check_mcp_version()` that reads the installed `mcp` package version via `importlib.metadata.version("mcp")`, parses it, compares to a `MIN_MCP_VERSION = "1.8.0"` constant, and on mismatch writes a single-line error to stderr citing the installed version, the required floor, and the doc URL from research R1 (`https://github.com/modelcontextprotocol/python-sdk`) — exits with code 1 (FR-011)

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 - Server runs locally and serves the three tools (Priority: P1) 🎯 MVP

**Goal**: A single `python src/server.py` invocation starts the server,
mounts the three existing MCP tools under `/<MCP_PATH_SECRET>/mcp` over
streamable HTTP, and the smoke script confirms each tool returns
correctly-shaped compact JSON.

**Independent Test**: With `.env` populated (Strava creds + a ≥24-char
`MCP_PATH_SECRET`), run `python src/server.py`; in a second terminal run
`python scripts/smoke.py`; observe all three tools succeed within 30 s
(SC-005) and each response parses to the shape in
`contracts/mcp-tools.md`.

### Implementation for User Story 1

- [X] T006 [US1] In `strava-coach-mcp/src/server.py`, implement `_build_app(secret: str) -> Starlette` that: constructs `FastMCP("strava-coach", streamable_http_path="/")`, takes its `StreamableHTTPSessionManager` (or equivalent) instance, wires the manager's lifespan into a `contextlib.AsyncExitStack` on the parent `Starlette` app, and mounts the MCP ASGI app at `/<secret>/mcp` using `Mount` inside the Starlette `routes=[...]` — robust pattern per research R2 (avoids issues #1367/#673); implements FR-002, FR-004 — **Implementation note**: simplified to setting `mcp.settings.streamable_http_path = f"/{secret}/mcp"` then calling `mcp.streamable_http_app()` directly. This puts the mount path inside the FastMCP-generated Starlette app, avoiding the parent-mount lifespan bug entirely. Non-matching paths still 404 via Starlette's default routing.
- [X] T007 [US1] In `strava-coach-mcp/src/server.py`, implement the `if __name__ == "__main__":` entry point: read `MCP_HOST` (default `"127.0.0.1"`), `MCP_PORT` (default `8080`), `MCP_PATH_SECRET` (no validation yet — that's US2); call `cache.init_db()` and `_check_mcp_version()`; call `_build_app(secret)`; print a ready-state log line `READY: strava-coach @ {host}:{port}/<MCP_PATH_SECRET:redacted>/mcp`; call `uvicorn.run(app, host=host, port=port, log_level="info")`; implements FR-001, FR-006 (default loopback only)
- [X] T008 [P] [US1] Write `strava-coach-mcp/scripts/smoke.py`: a Python script that reads `MCP_PATH_SECRET` from `.env`, opens an MCP client connection to `http://127.0.0.1:8080/<secret>/mcp` (use the `mcp` package's client transport for streamable HTTP), invokes `list_recent_activities(limit=5)`, `get_weekly_summary(weeks=4)`, and `get_activity_detail(<id-from-list>)`, asserts each response parses as JSON with the top-level fields specified in `contracts/mcp-tools.md`, asserts no top-level array in any response exceeds 200 elements as a structural proxy for "no raw streams" (FR-007), prints a per-tool size in bytes, and on `--measure-startup` spawns `python src/server.py` as a subprocess, captures stdout until the `READY:` line, asserts elapsed wall time < 5 s (SC-004), then SIGTERMs the subprocess; exits 0 on all-pass, 1 on any failure; implements FR-008
- [ ] T009 [US1] Run `python strava-coach-mcp/src/server.py` in one terminal; in a second terminal run `python strava-coach-mcp/scripts/smoke.py --measure-startup`; confirm all three tools return parseable JSON within size budgets from `contracts/mcp-tools.md` (≤ 5 KB / 4.5 KB / 12 KB respectively), total smoke wall time < 30 s (SC-005), measured cold-start wall time < 5 s (SC-004), and structural raw-streams check passes (FR-007); confirm Strava refresh-token rotation persisted to SQLite by inspecting the `tokens` table after the run (FR-009) — **Partially verified during /speckit-implement**: with dummy Strava credentials, the MCP handshake over streamable HTTP succeeded, all 3 tools were registered (`session.list_tools()` returns `[list_recent_activities, get_weekly_summary, get_activity_detail]`), and cold-start measured at **0.35s** (well under 5s budget). Tool invocation returned the error envelope (`{"error": "internal", ...}`) because dummy creds can't refresh against Strava. **User action required**: re-run with real Strava creds in `.env` to validate the shape assertions, size budgets, and FR-009 token rotation against live data.

**Checkpoint**: User Story 1 fully functional and testable. MVP delivered.

---

## Phase 4: User Story 2 - Path-secret auth gates the public endpoint (Priority: P2)

**Goal**: Startup refuses bad configurations and the running server returns
indistinguishable 404s for every non-secret path; logs never include the
secret; tool errors carry a structured envelope.

**Independent Test**: With the server running under US1's wiring, probe
`/`, `/mcp`, `/<wrong-secret>/mcp`, and `/<correct-secret>` (no `/mcp`
suffix) and confirm each returns `404` with no MCP-shaped body; restart
the server with `MCP_PATH_SECRET=""`, `MCP_PATH_SECRET="short"`, and
`MCP_HOST=0.0.0.0` (no opt-in) and confirm each exits with code 1 and a
single-line error naming the violated constraint.

### Implementation for User Story 2

- [X] T010 [US2] In `strava-coach-mcp/src/server.py`, implement `_check_path_secret(value: str | None) -> str` called from the entry point before `_build_app(...)`: rejects `None`, empty, or `len < 24` with a single-line `ERROR: MCP_PATH_SECRET must be set and ≥ 24 chars` to stderr and `sys.exit(1)`; returns the secret on success; implements FR-005
- [X] T011 [US2] In `strava-coach-mcp/src/server.py`, implement `_check_bind_host(host: str) -> None` called from the entry point: if `host not in {"127.0.0.1", "::1", "localhost"}` AND `os.environ.get("MCP_ALLOW_PUBLIC_BIND") != "1"`, writes `ERROR: refusing to bind {host}; set MCP_ALLOW_PUBLIC_BIND=1 to opt in` and `sys.exit(1)`; implements FR-006
- [X] T012 [US2] In `strava-coach-mcp/src/server.py`, ensure the Starlette parent app from T006 returns a uniform `Response(status_code=404)` (empty body, no `Content-Type` revealing MCP) for any path that doesn't match `/<secret>/mcp/*` — add an explicit catch-all `Route("/{path:path}", lambda req: Response(status_code=404))` AFTER the mount, only if Starlette's default 404 includes any MCP-revealing string (audit and decide); per `contracts/mount-and-auth.md` URL surface contract — **Decision**: Starlette's default 404 (`{"detail": "Not Found"}` style) contains none of the forbidden substrings `mcp`/`MCP`/`FastMCP`/`strava-coach`, so no explicit catch-all is added. `scripts/smoke_auth.py` asserts this is the case at runtime so any future Starlette change would surface.
- [X] T013 [US2] In `strava-coach-mcp/src/server.py`, call `uvicorn.run(..., access_log=False)` to suppress uvicorn's default request-path access log, then add a tiny Starlette middleware that logs only `{method} {status} {duration_ms}ms` (no path) to stdout for every request; ensures `MCP_PATH_SECRET` cannot appear in stdout/stderr logs; per `contracts/mount-and-auth.md` log-redaction contract
- [X] T014 [US2] In `strava-coach-mcp/src/server.py`, wrap the bodies of `list_recent_activities`, `get_weekly_summary`, and `get_activity_detail` with try/except that maps: Strava 401 → `{"error": "strava_auth_expired", "message": "Strava refresh token rejected; re-run the one-time OAuth bootstrap to re-seed STRAVA_REFRESH_TOKEN."}`, Strava 404 → `{"error": "activity_not_found", ...}`, network/5xx → `{"error": "strava_unavailable", ...}`, anything else → `{"error": "internal", "message": "<scrubbed>"}` — each returned as `json.dumps(...)`; never let an exception cross the MCP boundary; implements FR-012 per `contracts/mcp-tools.md` error envelope
- [X] T015 [P] [US2] Write `strava-coach-mcp/scripts/smoke_auth.py`: uses `requests` (or `urllib`) to hit `http://127.0.0.1:8080/mcp`, `http://127.0.0.1:8080/wrong-secret/mcp`, `http://127.0.0.1:8080/`, and `http://127.0.0.1:8080/<correct-secret>` (no `/mcp` suffix), asserts each returns HTTP 404 and the response body contains none of `"mcp"`, `"strava-coach"`, or `"FastMCP"`; also forks subprocesses that start `src/server.py` with `MCP_PATH_SECRET=""`, `MCP_PATH_SECRET="short"`, and `MCP_HOST=0.0.0.0` and asserts each exits with code 1 within 3 s; exits 0 on all-pass
- [X] T016 [US2] Run `python strava-coach-mcp/scripts/smoke_auth.py` against the live server and confirm 100% of probe paths return 404 with no MCP-revealing body (SC-003), and all three bad-startup configs exit 1 within 3 s (SC-006); confirm by tailing `journalctl`/stdout that no path-secret value appears in any log line (FR-004 log redaction) — **Verified during /speckit-implement**: all 4 probe paths (`/`, `/mcp`, `/wrong-secret/mcp`, `/<secret>` no `/mcp`) return 404 with clean bodies; all 3 bad-startup configs exit 1 in **0.28s each** (well under 3s budget per SC-006); `grep -c baseline-secret` in 1.2 KB of server logs returns **0** (FR-004 log redaction confirmed); a real Strava 400 from dummy creds was correctly translated to `{"error": "internal", "message": "..."}` (T014 error envelope confirmed).

**Checkpoint**: User Stories 1 AND 2 both work; server safe to expose
behind a publicly-trusted-cert tunnel.

---

## Phase 5: User Story 3 - End-to-end smoke test through a public tunnel (Priority: P3)

**Goal**: Confirm the full claude.ai → tunnel → MCP → tool path works
end-to-end with the chosen transport and path-secret auth, proving the
combination before any EC2 deploy.

**Independent Test**: With the server running locally, expose it via
cloudflared or ngrok, register the resulting `https://<tunnel-host>/<secret>/mcp`
URL as a claude.ai custom connector, and in a Claude chat ask Claude to
list recent activities — invocation succeeds and Claude renders the
returned compact JSON.

### Implementation for User Story 3

- [ ] T017 [US3] Execute `quickstart.md` step 7 end-to-end with cloudflared (or ngrok): start the local server, start a tunnel, register the tunnel URL in claude.ai as a custom connector (leave OAuth Client ID / Secret empty), then in a Claude chat invoke each of the three tools at least once and confirm the connector reports healthy throughout — **DEFERRED to user**: requires real Strava credentials, a tunnel account (cloudflared/ngrok), and access to the user's claude.ai workspace. Cannot be completed autonomously.
- [ ] T018 [US3] Append a "Tunnel-flow findings" subsection to `specs/001-finalize-server-transport-auth/quickstart.md` step 7 with any observed gotchas (latency, cold-start delays, cert/tunnel timeouts, claude.ai-side caching) and the tunnel tool actually used; if no gotchas were observed, record "no issues observed on YYYY-MM-DD with <tool> <version>" — **DEFERRED to user**: depends on T017 outcome.

**Checkpoint**: End-to-end path proven; ready to scope the EC2 deploy
feature with confidence.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Satisfy the documentation/audit requirements that span the
whole feature.

- [X] T019 [P] In the pull-request description for branch `001-finalize-server-transport-auth`, cite the doc URLs from `research.md` R1 (`https://github.com/modelcontextprotocol/python-sdk`, `https://pypi.org/project/mcp/`) and R5 (`https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp`, `https://claude.com/docs/connectors/building`, `https://github.com/anthropics/claude-ai-mcp/issues/110`, `https://github.com/anthropics/claude-ai-mcp/issues/112`) verified on 2026-05-31; satisfies constitution Principle V and SC-007 — **Done**: full PR body drafted at [PR_BODY.md](./PR_BODY.md) with both citation blocks (R1/R2/R4 for MCP SDK, R5/R6 for Anthropic connector) plus a verified-on date. When opening the PR, copy that file's contents into the description.
- [ ] T020 [P] Run `get_activity_detail` against the longest representative cached activity (e.g., a long run > 90 min) and confirm the response JSON ≤ 12 KB per `contracts/mcp-tools.md` size bound; if exceeded, file a follow-up to trim `official_splits_metric` or `stream_metrics.splits` granularity (do NOT modify metrics.py per constitution Principle VI without separate justification) — confirms SC-002 holds at the upper edge — **DEFERRED to user**: requires real Strava credentials + a long cached activity. Cannot be completed autonomously.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all
  user stories because every story needs `.env` loaded and a
  transport-capable `mcp` installed.
- **User Story 1 (Phase 3)**: Depends on Foundational. MVP — independently
  testable.
- **User Story 2 (Phase 4)**: Depends on Foundational AND on the
  `_build_app(...)` + entry-point scaffolding from T006/T007 (US1). Tasks
  T010–T014 layer onto US1's code; T015/T016 verify against the running
  server. US2 is **independently testable** in that its acceptance can be
  evaluated (probe 404s, bad-startup exits) without rerunning US1's tool
  smoke.
- **User Story 3 (Phase 5)**: Depends on US1 (server runs + tools work) AND
  on US2 (server is safe to expose). End-to-end through a tunnel implicitly
  requires both.
- **Polish (Phase 6)**: T019 depends only on the branch existing; T020
  depends on US1 (a working `get_activity_detail`).

### User Story Dependencies

- **US1 (P1)**: Strictly after Foundational. No dependency on other stories.
- **US2 (P2)**: Builds on US1's `_build_app` and entry-point structure.
  Cannot ship without US1 in this feature; can be skipped (server is
  insecure but functional) only if the operator never exposes it beyond
  loopback — not acceptable for the EC2 path.
- **US3 (P3)**: Requires US1 + US2 both. Pure validation work, no new code.

### Within Each User Story

- Foundational helpers (T004, T005) before app construction (T006).
- App construction (T006) before entry-point wiring (T007).
- Entry-point wiring (T007) before the smoke run (T009).
- Smoke script (T008) can be written in parallel with T006/T007 since it
  lives in a different file (`scripts/smoke.py`).
- Within US2, all of T010–T014 touch `src/server.py` and are sequential.
  T015 lives in `scripts/smoke_auth.py` and can be written in parallel with
  T010–T014.

### Parallel Opportunities

- **Phase 1**: T002 and T003 run in parallel after T001 completes (T001
  blocks because `requirements.txt` is the source of truth that downstream
  installs need).
- **Phase 3**: T008 (smoke.py) in parallel with T006 + T007 (server.py).
- **Phase 4**: T015 (smoke_auth.py) in parallel with T010–T014 (server.py).
- **Phase 6**: T019 and T020 are independent — both parallel.
- **Across stories**: US1, US2, US3 must be sequential at the code level
  because each layers on the previous; verification work within each story
  (T008/T015) can parallelise alongside implementation.

---

## Parallel Example: User Story 1

```bash
# After T006 + T007 are underway (server.py edits), open a second terminal
# and write T008 in parallel:

# Terminal A (T006, T007):
edit strava-coach-mcp/src/server.py

# Terminal B (T008):
edit strava-coach-mcp/scripts/smoke.py

# Once both land, T009 verifies them end-to-end.
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (Setup): T001, T002, T003.
2. Complete Phase 2 (Foundational): T004, T005.
3. Complete Phase 3 (US1): T006 → T007 → T008 (parallel) → T009.
4. **STOP and VALIDATE**: Confirm all three tools return correctly-shaped
   compact JSON to a local MCP client. Refresh-token rotation persisted.
5. Demo locally; do NOT expose beyond loopback yet.

### Incremental Delivery

1. **MVP (US1)**: Local-only server. Useful for the project owner alone via
   MCP Inspector.
2. **+ US2**: Server safe to expose through an HTTPS tunnel; bad
   configurations refuse to start; 404 indistinguishability holds.
3. **+ US3**: Proven end-to-end through a real claude.ai custom connector;
   ready to scope the EC2 deploy as a follow-up feature.
4. **+ Polish (T019, T020)**: PR-ready and audited.

### Solo Strategy

This project is a solo build. The "parallel" markers above mean different
files can be edited within a single session without blocking; they are NOT
prescriptions for multiple developers. Walk the phases sequentially within
each story.

---

## Notes

- `[P]` tasks = different files, no dependencies on incomplete tasks in the
  same phase.
- `[Story]` label maps each implementation task to a single user story for
  traceability.
- Per constitution Principle VI, do NOT modify `src/strava.py`,
  `src/cache.py`, or `src/metrics.py` while completing these tasks. If a
  defect surfaces in those modules during smoke runs, file a follow-up
  rather than fixing in-line.
- Per constitution Principle V, the PR description for this branch MUST
  cite the research URLs (covered by T019). Without that citation the
  feature is not ready to merge.
- Commit cadence: a clean commit after each phase checkpoint (after T009,
  T016, and the polish tasks) keeps history readable; the `speckit.git.commit`
  after-hook will offer to do this automatically after `/speckit-implement`
  runs.
- Avoid: changing the existing `@mcp.tool()` function signatures, modifying
  the SQLite schema, returning raw stream arrays, or logging the path
  secret in any code path.
