# Strava Coach MCP — build spec (handoff for Claude Code)

## What this is
A **remote (HTTPS) MCP server** that runs on the user's own EC2 box and gives
Claude (in claude.ai / Max) live, computed access to the user's Strava training
data. It is plumbing only — it does **not** call the Anthropic API, so it adds no
API cost. All "intelligence" happens in the user's Max chat; this server just
fetches Strava data, computes useful metrics, caches them in SQLite, and returns
compact summaries.

## Billing / context model (design intent — keep it this way)
- The user has **Claude Max** + an **EC2** already running. No extra API spend.
- The user's **marathon plan, goals, and typed adjustments** live in a Claude
  **Project + memory** — NOT in this server. Do not build plan storage here.
- This server's SQLite is an **activity/metrics cache**, not plan memory.
- Tools must return **compact** results. Raw per-second streams (thousands of
  points) must be computed down to summaries server-side and NEVER returned raw,
  to keep Max chat context (and usage) lean.

## Architecture
```
Claude (Max chat, Project)  --custom connector (HTTPS)-->  this MCP server (EC2)
                                                              |
                                                              +-- Strava API
                                                              +-- SQLite cache
```

## Files in this package
- `src/strava.py`   — Strava API client (token refresh + rotation, activities,
                      detail, streams, zones). **Working, stable. Reuse as-is.**
- `src/cache.py`    — SQLite schema + upsert/query helpers. **Working. Reuse.**
- `src/metrics.py`  — stream math: first/second-half HR & pace, Pa:HR decoupling,
                      HR drift, binned splits, time-in-zone. **Working. Reuse.**
- `src/server.py`   — FastMCP server defining the tools. **Scaffold — finish the
                      transport + auth (see TODO below) against current docs.**
- `.env.example`, `requirements.txt`
- `deploy/`         — nginx vhost, systemd unit, deploy notes for EC2 + certbot.

## TODO for you (Claude Code) — verify against CURRENT docs, don't assume
My training may be stale on these two points, so check live docs before finalising:

1. **Remote MCP transport.** Confirm the current MCP Python SDK API for serving
   over **streamable HTTP** (FastMCP). Verify the method/attribute names
   (`mcp.run(transport=...)` / `mcp.streamable_http_app()` / settings for
   host/port/path). Docs: https://modelcontextprotocol.io and the
   `mcp` PyPI package README.
2. **Custom-connector auth.** Anthropic connects from its cloud, so the endpoint
   must be public HTTPS. Confirm what auth a claude.ai *custom connector* can send
   (OAuth vs. a static token). Docs:
   https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
   - If a custom header isn't configurable in the connector UI, use the
     **secret-in-path** approach already scaffolded (mount the MCP app under
     `/<MCP_PATH_SECRET>/mcp`; the secret lives in the connector URL over TLS).
   - Upgrade to OAuth later if desired. Do NOT ship an unauthenticated public
     endpoint — it would expose the user's Strava data to anyone with the URL.

## Tools to expose (signatures defined in src/server.py)
- `list_recent_activities(limit=20)` — syncs new activities, returns compact
  summaries (date, type, distance_km, duration, avg_pace, avg_hr).
- `get_weekly_summary(weeks=8)` — SQL rollup: km/run-count/time per ISO week.
- `get_activity_detail(activity_id)` — detail + computed stream metrics
  (first/second-half HR & pace, decoupling %, HR drift, km splits, time-in-zone).
  Computed once, then cached in `activity_metrics`.

## Strava setup the user does once
- Create an API app at https://www.strava.com/settings/api (callback `localhost`).
- One-time OAuth with scope **`activity:read_all`** (streams need read_all).
- Put client id/secret + initial refresh token in `.env`.

## Extension ideas (not required for v1)
- `compare_periods(...)` (this block vs last), planned-vs-actual reconciliation,
  route suggestions, wearable HRV ingestion for sharper fatigue signals.
