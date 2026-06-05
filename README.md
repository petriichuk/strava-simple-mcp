# strava-custom-mcp

A remote [MCP](https://modelcontextprotocol.io) server that gives [Claude](https://claude.ai)
live, computed access to your Strava training data — without spending an API cent.

Designed for endurance / marathon-prep workflows. The server pulls activities
from Strava, computes the metrics that matter (HR drift, Pa:HR decoupling,
first/second-half splits, time-in-zone), caches them in SQLite, and exposes
three MCP tools. All coaching intelligence — your plan, goals, weekly
adjustments — lives in your Claude Project + memory. The server is plumbing
only; it never calls an LLM.

## Why

If you have Claude Max and a server you can reach (laptop + tunnel for dev, a
small VPS for production), this gives Claude the data it needs to reason about
your training without the per-token cost of running an agent yourself. Your
chat becomes the coach; this server is the data layer.

## Architecture

```
   Claude (Max chat, Project + memory)
                 │
                 │  custom connector  (HTTPS, streamable HTTP)
                 ▼
        strava-custom-mcp server
                 │
                 ├──► Strava API     (read activities/streams/zones)
                 └──► SQLite cache   (activity + computed-metric cache)
```

Constraints by design:
- No LLM calls from the server (zero API cost).
- Tools return compact JSON only — raw per-second streams (thousands of
  points) are reduced server-side to summaries before they touch the wire.
- SQLite holds activity-derived data. Plan / goals / typed adjustments live
  in Claude Project memory, never here.

## Tools

| Tool                                 | Purpose                                                                                          |
| ------------------------------------ | ------------------------------------------------------------------------------------------------ |
| `list_recent_activities(limit=20)`   | Recent activity summaries (date, type, distance, duration, avg pace, avg HR).                    |
| `get_weekly_summary(weeks=8)`        | ISO-week rollups: runs, km, hours per week.                                                      |
| `get_activity_detail(activity_id)`   | Per-activity: official splits, first/second-half HR & pace, HR drift, Pa:HR decoupling, time-in-zone. Computed once and cached. |

Responses are compact (typical 1-hour run ≤ 4 KB). See
[`specs/001-finalize-server-transport-auth/contracts/mcp-tools.md`](specs/001-finalize-server-transport-auth/contracts/mcp-tools.md)
for the exact shapes.

## Requirements

- macOS or Linux (Windows is out of scope for v1).
- Python 3.11+.
- A Strava API app (free) — https://www.strava.com/settings/api.
- For end-to-end testing with claude.ai: a tunneling tool — **ngrok**
  (recommended), cloudflared, or a real domain.

## Quickstart (local, ~5 minutes)

```bash
git clone https://github.com/<you>/strava-custom-mcp.git
cd strava-custom-mcp

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 1. Fill in STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET from
#    https://www.strava.com/settings/api
# 2. Run the one-time OAuth bootstrap to seed STRAVA_REFRESH_TOKEN
#    (see "Bootstrapping the Strava refresh token" below).
# 3. Generate MCP_PATH_SECRET:
python -c "import secrets; print(secrets.token_urlsafe(32))"
# Paste the result into .env as MCP_PATH_SECRET.

python src/server.py
# Expect a single line:
#   READY: strava-custom @ 127.0.0.1:8080/<MCP_PATH_SECRET:abcd***wxyz>/mcp
```

Verify everything works in a second terminal:

```bash
python scripts/smoke.py --measure-startup       # exercises the 3 tools
python scripts/smoke_auth.py                    # checks 404 + bad-startup
python scripts/diag_strava.py                   # diagnoses Strava auth state
```

## Connecting from claude.ai

> Claude.ai custom connectors require a publicly-reachable HTTPS URL with a
> publicly-trusted TLS cert. Loopback addresses don't work. Use a tunnel for
> development and a real domain for production.

1. Expose the local server over HTTPS. **ngrok** is the recommended choice
   — its URLs are more stable than cloudflared's randomly-generated
   `trycloudflare.com` hostnames, which rotate on every restart.

   ```bash
   ngrok http 8080
   # (or: cloudflared tunnel --url http://127.0.0.1:8080)
   ```

   Copy the `https://<host>.ngrok-free.app` URL it prints (or the
   `https://<host>.trycloudflare.com` URL from cloudflared).

2. In `.env`, set `MCP_ALLOWED_HOSTS=*` (or the specific tunnel host) so the
   MCP SDK's DNS-rebinding protection accepts requests from the tunnel.
   **Restart the server** after this change.

3. In claude.ai → Settings → Connectors → Add custom connector. Paste:
   ```
   https://<host>.ngrok-free.app/<MCP_PATH_SECRET>/mcp
   ```
   Leave the OAuth fields empty. **Make sure the URL ends in `/mcp`** — a
   typo like `/mvp` returns 404 and Claude reports a generic "session
   terminated" error.

4. In your Project's instructions, tell Claude what you're training for and
   when to reach for these tools. Example:
   ```
   I'm training for a marathon (target date: YYYY-MM-DD, goal: H:MM).
   Use the strava-custom connector for activity data:
     - list_recent_activities for the last N sessions
     - get_weekly_summary for week-over-week volume
     - get_activity_detail for HR drift / decoupling / splits on a specific session
   My plan and goals live in this Project's memory.
   ```

Flip each tool's permission to "Always allow" so Claude doesn't pause for
approval on every call.

## Bootstrapping the Strava refresh token

One-time setup to seed `STRAVA_REFRESH_TOKEN` in `.env`.

1. In your Strava API settings (https://www.strava.com/settings/api), set
   **Authorization Callback Domain** to `localhost`.

2. In a browser, paste (substituting your client_id):
   ```
   https://www.strava.com/oauth/authorize?client_id=<CLIENT_ID>&response_type=code&redirect_uri=http://localhost/exchange_token&approval_prompt=force&scope=activity:read_all
   ```

3. On Strava's authorize page, ensure **"View data about your activities
   (including private activities)"** is checked, then click Authorize. The
   browser redirects to `http://localhost/exchange_token?code=<CODE>...` —
   that page won't load (nothing is listening), but the URL bar holds the
   `code` you need.

4. Exchange the code for tokens (uses your current `.env` values):
   ```bash
   curl -X POST https://www.strava.com/oauth/token \
     -d client_id=<CLIENT_ID> \
     -d client_secret=<CLIENT_SECRET> \
     -d code=<CODE-FROM-STEP-3> \
     -d grant_type=authorization_code
   ```

5. Copy `refresh_token` from the JSON response into `.env` as
   `STRAVA_REFRESH_TOKEN`. Verify the response includes
   `"scope":"read,activity:read_all"`.

The server persists rotated refresh tokens to SQLite automatically going
forward, so this only needs to happen once (or after a password change /
deauthorization).

## Configuration

| Variable                | Required | Default       | Notes |
| ----------------------- | -------- | ------------- | ----- |
| `STRAVA_CLIENT_ID`      | yes      | —             | From your Strava API app.                                                  |
| `STRAVA_CLIENT_SECRET`  | yes      | —             | From your Strava API app. Never commit.                                    |
| `STRAVA_REFRESH_TOKEN`  | yes      | —             | Seed value from one-time OAuth; rotates and is persisted to `coach.db`.    |
| `MCP_PATH_SECRET`       | yes      | —             | ≥24 chars. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. The server refuses to start otherwise. |
| `COACH_DB_PATH`         | no       | `coach.db`    | SQLite file location.                                                      |
| `MCP_HOST`              | no       | `127.0.0.1`   | Set to `0.0.0.0` for non-loopback bind (also requires opt-in below).      |
| `MCP_PORT`              | no       | `8080`        |                                                                            |
| `MCP_ALLOW_PUBLIC_BIND` | no       | unset         | Set to `1` to allow binding non-loopback hosts. Refuses otherwise.         |
| `MCP_ALLOWED_HOSTS`     | no       | loopback only | The MCP SDK's DNS-rebinding allow-list. `*` to disable; or a comma-separated list of hostnames (with or without ports). Needed for tunnel / domain use. |

## Auth model

v1 uses a **path secret** — a high-entropy random string that lives in the URL
path: `https://<host>/<MCP_PATH_SECRET>/mcp`. Any other path returns a clean
404 with no MCP-revealing body. This is the community-fallback approach when
the claude.ai custom-connector UI doesn't expose a header field.

This works but is **not Anthropic's blessed path**. The official supported
flows are (a) authless or (b) OAuth 2.1 + PKCE. OAuth is the planned
follow-up — see [TODO / roadmap](#todo--roadmap) below. Treat the path
secret as a bearer credential:

- Generate with `secrets.token_urlsafe(32)` or stronger.
- Never log it. The server's middleware logs only method + status + duration.
- Never paste it into chat transcripts or shared docs.
- Rotate by generating a new value, restarting the server, and re-registering
  the connector URL in claude.ai.

For loopback-only development, the path secret + the SDK's DNS-rebinding
protection give defense in depth. For any internet-facing deployment, treat
the URL as the secret.

## Deploying to a VPS / EC2

A minimal deploy scaffold lives in
[`ec2-deploy/`](ec2-deploy/):

- `nginx.conf` — TLS termination + reverse proxy to loopback.
- `strava-mcp.service` — systemd unit.
- `README.md` — step-by-step (apt install, certbot, systemd).

The main repo is documented and tested for the **local + tunnel** workflow.
The EC2 scaffold has been used but isn't part of the smoke-tested critical
path. PRs improving it are welcome.

## Repository layout

```
src/
├── server.py                # MCP server (transport, auth, tools)
├── strava.py                # Strava API client (token rotation, paginated reads)
├── cache.py                 # SQLite schema + helpers
└── metrics.py               # Pure-Python stream math (no numpy)

scripts/
├── smoke.py                 # End-to-end tool smoke
├── smoke_auth.py            # Path-secret + bad-startup smoke
└── diag_strava.py           # Strava credential diagnostic

ec2-deploy/                  # nginx + systemd + deploy README
specs/                       # Spec Kit feature directories (design artifacts)
.specify/                    # Spec Kit machinery
.env.example
requirements.txt
SPEC.md                      # Original design brief
```

The `specs/` and `.specify/` directories preserve the spec-driven design
process and are kept in the repo for transparency — see the
[constitution](.specify/memory/constitution.md) and the
[001 spec](specs/001-finalize-server-transport-auth/spec.md) if you want to
see how the project is structured.

## Limitations & known gotchas

- **trycloudflare URLs rotate** on every `cloudflared tunnel --url` restart.
  ngrok free-tier URLs are more stable but still change between sessions —
  for a permanent URL, use ngrok with a reserved subdomain (paid) or a
  named cloudflared tunnel bound to a real domain.
- **Claude.ai connector caching**: re-registering the connector with a new
  URL sometimes requires disconnect → reconnect rather than edit-in-place.
- **Strava rate limits**: 100 reqs / 15 min, 1000 / day. Cold-start sync
  pulls up to 200 activities (4 pages × 50). Heavy use of
  `get_activity_detail` against many distinct activities can chew through
  the 15-min bucket.
- **Strava scope**: tokens must have `activity:read_all`. A token granted
  with only `read` scope returns 401 on `/athlete/activities` even though
  `/athlete` succeeds. The bootstrap step above prevents this.
- **Path secret in the URL leaks into request logs.** Configure any reverse
  proxy (nginx, cloudflared) to redact the secret segment from access logs.
- **Two "Strava" connectors in claude.ai**: claude.ai ships a first-party
  Strava connector. If both are enabled, Claude may pick the first-party
  one. Disconnect the first-party connector or name yours distinctly.

## TODO / roadmap

- **OAuth 2.1 + PKCE** for claude.ai connector auth (replaces path-secret).
- **`compare_periods(start_a, end_a, start_b, end_b)`** — diff two training
  blocks.
- **Wearable HRV ingestion** for sharper fatigue signals.
- **EC2 deploy hardening** — log redaction, secret rotation procedure,
  named-tunnel example.

## Status

Personal-use project. Built and used by one person. The local + tunnel +
claude.ai flow is exercised regularly. Issues and PRs welcome.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

The project is developed with [Spec Kit](https://github.com/github/spec-kit).
The relevant slash commands (`/speckit-specify`, `/speckit-plan`,
`/speckit-tasks`, `/speckit-implement`) live in `.claude/skills/` if you use
Claude Code. None of that is required for routine contributions.

## Security

For anything that looks like a vulnerability, see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE).

## Acknowledgements

- [Model Context Protocol](https://modelcontextprotocol.io) and the
  [`mcp` Python SDK](https://github.com/modelcontextprotocol/python-sdk).
- [Strava developers](https://developers.strava.com/) for the API.
- The spec-driven scaffolding for this project comes from
  [GitHub Spec Kit](https://github.com/github/spec-kit).
