# Implementation Plan: Finalize MCP Server Transport & Auth (Local Run)

**Branch**: `001-finalize-server-transport-auth` | **Date**: 2026-05-31 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-finalize-server-transport-auth/spec.md`

## Summary

Finish the transport-and-auth wiring at the bottom of `strava-coach-mcp/src/server.py`
so the existing three MCP tools (`list_recent_activities`, `get_weekly_summary`,
`get_activity_detail`) are reachable over MCP streamable-HTTP, gated by a
path-secret mounted into a Starlette parent app, and runnable from a single
`python src/server.py` invocation on macOS or Linux. Approach is drawn from
research R1–R8 in [research.md](./research.md): pin `mcp>=1.8.0`, pass
`transport="streamable-http"`, mount via `StreamableHTTPSessionManager` +
parent-app lifespan (NOT bare `Mount(..., app=streamable_http_app())`) to avoid
the known lifespan bug, and validate startup invariants (secret length,
loopback default, SDK version) before binding the port. Path-secret stays as
the v1 auth scheme; OAuth 2.1 + PKCE is the next-feature follow-up (user
decision on 2026-05-31).

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: `mcp>=1.8.0` (recommended floor `1.27.0`), `starlette>=0.37.0`, `uvicorn>=0.30.0`, `requests>=2.31.0`, `python-dotenv` (for `.env` loading)
**Storage**: SQLite via `src/cache.py` (single file `coach.db`, schema unchanged this feature)
**Testing**: Lightweight Python smoke script (`scripts/smoke.py`) that drives the three tools against a running local server; pytest is OPTIONAL per spec and constitution Workflow section
**Target Platform**: macOS / Linux developer laptop for User Stories 1–2; cloudflared/ngrok HTTPS tunnel for User Story 3; EC2 (Linux) is out of scope for this feature
**Project Type**: Single-process Python web service (remote MCP server)
**Performance Goals**: Cold start < 5 s (SC-004); smoke procedure across all three tools < 30 s (SC-005); each tool response ≤ 4 KB for a typical 1-hour run (SC-002)
**Constraints**: Loopback default bind (`127.0.0.1:8080`); refuse to start without a ≥ 24-char path secret; never return raw per-second stream arrays; never log the path secret or Strava tokens
**Scale/Scope**: Single user, single concurrent connector. No load goals. Touch surface: `src/server.py` (rewrite the transport/auth tail), `scripts/smoke.py` (new), `requirements.txt` (pin floor on `mcp`), this feature's quickstart.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Reviewed against `.specify/memory/constitution.md` v1.0.0:

| Principle                                          | Status | Notes |
| -------------------------------------------------- | ------ | ----- |
| I. Plumbing Over Intelligence (NON-NEGOTIABLE)     | ✅ Pass | No Anthropic API calls introduced. Server only fetches from Strava and returns compact JSON to the connector. |
| II. Compact Tool Responses                          | ✅ Pass | Tool contracts in `contracts/mcp-tools.md` reaffirm no raw streams; budgets capped at 4 KB / 5 KB / 12 KB depending on tool. |
| III. Cache, Not Memory                              | ✅ Pass | No new tables. `activities`, `activity_metrics`, `tokens`, `sync_state` schemas unchanged. No plan/goal storage added. |
| IV. Authenticated Endpoints Only                    | ✅ Pass | Path-secret enforced at startup (≥ 24 chars) AND at mount path. Loopback default further reduces local-mode attack surface. OAuth 2.1 + PKCE acknowledged as the official follow-up per research R5. |
| V. Verify Live Docs for Volatile Surfaces           | ✅ Pass | Research R1 (MCP SDK transport) and R5 (connector auth) cite current doc URLs (2026-05-31). The PR description MUST repeat those URLs to satisfy SC-007. |
| VI. Reuse Stable Modules                            | ✅ Pass | `src/strava.py`, `src/cache.py`, `src/metrics.py` unchanged. Only `src/server.py`'s transport tail is rewritten; the `@mcp.tool()` function bodies are preserved. |

**Security & Deployment Constraints**: All satisfied:
- HTTPS termination policy (nginx + certbot) is unchanged — this feature
  doesn't deploy; local mode is loopback HTTP, tunnel mode delegates TLS to
  cloudflared/ngrok.
- `.env` remains the only secret store; nothing committed.
- Strava scope stays at `activity:read_all`.
- `deploy/` is not touched.
- Refresh-token rotation is honoured via the existing `StravaClient` —
  exercised by FR-009 + smoke procedure.

**Development Workflow**: Feature follows the Spec Kit phases. Smoke check
(constitution Workflow item 3) is provided by `scripts/smoke.py`.

**Verdict**: PASS — no violations. Complexity Tracking section below is
empty.

### Re-evaluation after Phase 1 design

Re-checked after writing data-model.md, contracts/, and quickstart.md. No
principle is at risk:
- The mount-and-auth contract enforces 404 indistinguishability (Principle
  IV defence-in-depth).
- The MCP-tools contract documents the compact-response budgets explicitly
  (Principle II enforced at contract level, not just code level).
- Reuse of E3/E4/E5/E6 with no schema changes (Principle III, VI both held).

**Post-design verdict**: PASS.

## Project Structure

### Documentation (this feature)

```text
specs/001-finalize-server-transport-auth/
├── spec.md
├── plan.md                       # This file
├── research.md                   # Phase 0 — MCP SDK + connector auth research
├── data-model.md                 # Phase 1 — 6 logical entities (no schema changes)
├── contracts/
│   ├── mcp-tools.md              # Phase 1 — I/O shapes for the three tools + error envelope
│   └── mount-and-auth.md         # Phase 1 — URL surface, startup contract, log redaction
├── quickstart.md                 # Phase 1 — install → run → smoke → tunnel walkthrough
├── checklists/
│   └── requirements.md           # From /speckit-specify
└── tasks.md                      # Generated by /speckit-tasks (next command)
```

### Source Code (repository root)

```text
strava-coach-mcp/
├── src/
│   ├── server.py                 # MODIFIED — transport + auth tail rewritten;
│   │                             #            tool functions unchanged
│   ├── strava.py                 # UNCHANGED (constitution VI)
│   ├── cache.py                  # UNCHANGED
│   └── metrics.py                # UNCHANGED
├── scripts/
│   └── smoke.py                  # NEW — drives the three tools against a running local server
├── deploy/                       # UNTOUCHED this feature (nginx/systemd/certbot live here for the EC2 feature)
├── .env.example                  # MODIFIED — add MCP_HOST, MCP_PORT, MCP_ALLOW_PUBLIC_BIND notes
├── requirements.txt              # MODIFIED — floor mcp>=1.8.0, add python-dotenv if not already implied
└── SPEC.md                       # UNCHANGED (kept as the original handoff doc)
```

**Structure Decision**: Single-project (Python service) layout. The existing
`strava-coach-mcp/` directory is the project root for code; the repo root
holds the spec-kit machinery and the `specs/` tree. No `tests/` directory is
required for this feature — smoke is a script invoked from quickstart.md
step 5.

## Complexity Tracking

> No constitution violations — table intentionally empty.
