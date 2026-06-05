<!--
SYNC IMPACT REPORT
==================
Version change: (unfilled template) → 1.0.0
Rationale: First ratification from template; establishes six load-bearing principles
derived from SPEC.md design intent.

Modified principles: N/A (initial ratification)
Added principles:
  I.   Plumbing Over Intelligence (NON-NEGOTIABLE)
  II.  Compact Tool Responses
  III. Cache, Not Memory
  IV.  Authenticated Endpoints Only
  V.   Verify Live Docs for Volatile Surfaces
  VI.  Reuse Stable Modules
Added sections:
  - Security & Deployment Constraints
  - Development Workflow
  - Governance
Removed sections: N/A

Templates audited:
  ✅ .specify/templates/plan-template.md — "Constitution Check" gate defers to
     this file; no text changes needed. Future /speckit.plan runs will evaluate
     principles I–VI at that gate.
  ✅ .specify/templates/spec-template.md — user-story/requirements shape does not
     conflict with any principle.
  ✅ .specify/templates/tasks-template.md — phased task layout compatible; tests
     remain optional, matching the workflow section here.
  ✅ .specify/templates/agent-file-template.md — generic agent-context shape; no
     principle-driven changes.
  ✅ .claude/skills/speckit-*/ command files — defer to .specify content; no
     references to outdated principle names to scrub.
  ✅ SPEC.md — this constitution codifies the design intent already present in
     SPEC.md; no edits required.
  ⚠ README.md / docs/quickstart.md — do not yet exist. When created, they MUST
     reference principles I (no LLM calls), II (compact responses), III (cache
     vs. memory), and IV (auth required).

Deferred TODOs: none.
-->

# Strava Coach MCP Constitution

## Core Principles

### I. Plumbing Over Intelligence (NON-NEGOTIABLE)

This server is data plumbing. It MUST NOT call the Anthropic API or otherwise
invoke any LLM. All coaching intelligence — goal interpretation, plan reasoning,
training advice — lives in the user's Claude Max chat (Project + memory). The
server fetches Strava data, computes derived metrics, caches them, and returns
compact summaries; nothing more.

**Rationale**: Keeps API spend at zero (Claude Max already covers chat usage),
keeps context decisions in one place (the chat surface), and prevents this
codebase from accidentally growing into an opinionated coach that would
duplicate or drift from the user's plan memory.

### II. Compact Tool Responses

Every MCP tool MUST return compact, summarized results suitable for direct
inclusion in chat context. Raw per-second streams (HR, GPS, pace, power) —
typically thousands of points per activity — MUST be reduced server-side to
summaries (splits, first/second halves, averages, time-in-zone, Pa:HR
decoupling, HR drift). The server NEVER returns raw stream arrays to the client.

**Rationale**: Returning raw streams blows up the chat context window and
inflates Max usage; pre-computing and caching makes each tool call cheap and
keeps responses small enough to compose freely in a single turn.

### III. Cache, Not Memory

SQLite is an activity/metrics cache for Strava-derived data. It MUST NOT store
the user's plan, goals, training adjustments, or any coaching memory — those
live in the Claude Project + memory. New tables MUST be derived from or
computed against Strava data. If a feature requires persisting user-authored
plan or goal content here, that is a constitution amendment, not a routine
schema change.

**Rationale**: Bifurcating storage was the explicit design intent; duplicating
plan state into SQLite creates drift between two sources of truth and locks the
user out of editing plan content in the surface where they actually work on it
(the chat).

### IV. Authenticated Endpoints Only

The server MUST NOT be reachable as an unauthenticated public HTTPS endpoint.
Authentication MUST be either (a) OAuth as supported by the Anthropic custom
connector flow, or (b) the scaffolded secret-in-path scheme (TLS-protected URL
containing `MCP_PATH_SECRET`). Listening on a non-loopback interface without
one of these is prohibited.

**Rationale**: An unauthenticated remote MCP exposes the user's complete Strava
history (and any derived training data) to anyone who guesses the URL. This is
unacceptable for a personal training dataset.

### V. Verify Live Docs for Volatile Surfaces

For the MCP Python SDK transport API (FastMCP, `streamable_http_app`,
`run(transport=...)`, host/port/path settings) and for Anthropic custom-connector
authentication, the implementer MUST consult current official documentation
before finalising code. Training-time knowledge of these surfaces is assumed
stale. The doc URL consulted MUST be cited in the corresponding plan or PR
description.

**Rationale**: These two surfaces are the project's only moving targets;
everything else (Strava REST API, SQLite, Python stdlib) is stable. Catching
SDK churn at design time avoids a rewrite at deploy time.

### VI. Reuse Stable Modules

`src/strava.py`, `src/cache.py`, and `src/metrics.py` are stable and MUST be
reused as-is. Modifications are allowed only to fix a defect, add a genuinely
new computed metric, or accommodate a Strava API change. New tools compose
these modules rather than reimplementing Strava fetch, SQLite I/O, or stream
math.

**Rationale**: SPEC.md marks these modules as working and stable; rewrites
without cause introduce regressions in the math that makes the coaching tools
useful and inflate review burden for no functional gain.

## Security & Deployment Constraints

- All remote traffic MUST terminate HTTPS at nginx with a valid (certbot-issued)
  certificate; the FastMCP process binds loopback only.
- `.env` is the sole store of persistent secrets: Strava `CLIENT_ID`,
  `CLIENT_SECRET`, refresh token, and `MCP_PATH_SECRET` (when path-secret auth
  is in use). `.env` MUST NOT be committed; only `.env.example` ships.
- Strava OAuth scope MUST be exactly `activity:read_all`. Write scopes
  (`activity:write`, profile mutation, etc.) are out of scope for v1 and require
  a constitution amendment to introduce.
- The deployable surface (`deploy/` — systemd unit, nginx vhost, deploy notes)
  MUST be reviewed alongside any change to transport, auth, or process lifecycle.
- Refresh-token rotation MUST be honoured: when Strava returns a new refresh
  token, the server persists it; failure to do so is a defect, not a feature.

## Development Workflow

- Feature work follows Spec Kit: `/speckit.specify` → `/speckit.plan` →
  `/speckit.tasks` → `/speckit.implement`, on a feature branch following the
  configured `branch_numbering: sequential` scheme.
- The MVP surface is the three tools defined in `src/server.py`:
  `list_recent_activities`, `get_weekly_summary`, `get_activity_detail`. Adding
  a new tool requires a spec and triggers the Constitution Check in
  `plan-template.md`.
- Every tool MUST have at least one smoke check — a manual or scripted live
  invocation against Strava — confirming the compact-response contract from
  Principle II.
- Tests are OPTIONAL for this project. When added, they live under `tests/`
  and SHOULD use cached real Strava JSON as fixtures rather than mocks, so
  regressions in stream math surface against representative data.
- Commits SHOULD be small and self-contained; the spec-kit auto-commit hooks
  (`speckit.git.commit`) handle routine commits after each phase.

## Governance

This constitution supersedes ad-hoc decisions in commits, PRs, and chat.
Conflicts are resolved by amending the constitution explicitly, not by silent
deviation.

Amendments require:

1. An updated version per semantic versioning (rules below).
2. A sync pass across `.specify/templates/*.md` and any runtime guidance docs
   (`README.md`, `SPEC.md`, `docs/quickstart.md`) that reference the changed
   principles.
3. A dated entry in the Sync Impact Report at the top of this file.

Semantic versioning rules for this document:

- **MAJOR**: Removing or redefining a principle, or reversing a NON-NEGOTIABLE
  design intent (e.g., allowing LLM calls from the server, or storing plan
  memory in SQLite).
- **MINOR**: Adding a new principle, or materially expanding a section's
  guidance.
- **PATCH**: Wording clarifications, typo fixes, non-semantic refinements.

Every `/speckit.plan` run MUST evaluate the Constitution Check gate against
principles I–VI before Phase 0 research begins, and re-check after Phase 1
design. Violations require entries in the plan's Complexity Tracking table
with a justified "Simpler Alternative Rejected Because" reason.

**Version**: 1.0.0 | **Ratified**: 2026-05-31 | **Last Amended**: 2026-05-31
