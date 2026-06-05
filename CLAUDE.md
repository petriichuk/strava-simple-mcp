# strava-simple-mcp Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-05-31

## Active Technologies
- Python 3.11+ (001-finalize-server-transport-auth)
- `mcp>=1.8.0` (recommended floor `1.27.0`), `starlette>=0.37.0`, `uvicorn>=0.30.0`, `requests>=2.31.0`, `python-dotenv` (001-finalize-server-transport-auth)
- SQLite via `src/cache.py` — single file `coach.db`, schema unchanged this feature (001-finalize-server-transport-auth)

## Project Structure

```text
src/
├── server.py        # MCP server (transport + auth + 3 tools)
├── strava.py        # Strava API client (stable, reuse-as-is)
├── cache.py         # SQLite schema + helpers (stable, reuse-as-is)
└── metrics.py       # Stream math (stable, reuse-as-is)
scripts/             # Smoke / utility scripts
ec2-deploy/          # nginx vhost + systemd unit (EC2 deploy)
.env.example
requirements.txt
specs/               # Spec-kit feature directories
.specify/            # Spec-kit machinery (memory, templates, scripts)
SPEC.md              # Original handoff doc; kept verbatim
```

## Commands

```bash
# Local server (from repo root)
python src/server.py

# Smoke check (from repo root, with server running)
python scripts/smoke.py

# Spec-kit phases (from repo root)
/speckit-specify "..."   # spec
/speckit-plan            # plan + research + contracts
/speckit-tasks           # ordered tasks
/speckit-implement       # execute tasks
```

## Code Style

Follow standard Python conventions. Constitution principles (see `.specify/memory/constitution.md`):
- **No LLM calls** from this server (Principle I).
- **Compact responses only** — never return raw per-second streams (Principle II).
- **Cache, not memory** — SQLite holds Strava-derived data; plans/goals live in the Claude Project (Principle III).
- **Auth required** — path-secret v1 (≥ 24 chars), OAuth 2.1 + PKCE as follow-up (Principle IV).
- **Verify live docs** for MCP SDK transport + Anthropic connector flow; cite URLs in PRs (Principle V).
- **Reuse stable modules** — `strava.py`, `cache.py`, `metrics.py` are stable (Principle VI).

## Recent Changes
- 001-finalize-server-transport-auth: Added Python 3.11+ MCP streamable-HTTP transport, path-secret mount, single-command local run

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
