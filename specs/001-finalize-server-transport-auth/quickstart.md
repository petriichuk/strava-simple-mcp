# Quickstart: Run the Strava Coach MCP Server Locally

**Feature**: `001-finalize-server-transport-auth`
**Audience**: anyone — primarily the project owner — who needs to bring the
server up on a laptop and confirm it serves the three MCP tools end-to-end.
**Target time**: under 15 minutes from clone to a working tool call
(SC-001).

---

## Prerequisites

- macOS or Linux (Windows is out of scope for v1).
- Python 3.11+ on `PATH`.
- A Strava API app (https://www.strava.com/settings/api). You need its
  **Client ID** and **Client Secret**.
- A Strava **refresh token** obtained by completing the one-time OAuth flow
  with scope `activity:read_all`. (Detailed OAuth bootstrap is out of scope
  for this feature; reuse any existing snippet you trust, or follow
  https://developers.strava.com/docs/authentication/.)
- For User Story 3 only: **cloudflared** or **ngrok** installed and
  logged in to your account, ready to expose a tunnel.

---

## 1 — Install

```bash
cd strava-coach-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Confirm the `mcp` package version is ≥ 1.8.0:

```bash
python -c "import mcp, importlib.metadata as m; print(m.version('mcp'))"
```

---

## 2 — Configure `.env`

Copy the example and fill in the four required values:

```bash
cp .env.example .env
```

Edit `.env`:

```dotenv
STRAVA_CLIENT_ID=<your client id>
STRAVA_CLIENT_SECRET=<your client secret>
STRAVA_REFRESH_TOKEN=<your seed refresh token>
MCP_PATH_SECRET=<see step 3>
COACH_DB_PATH=coach.db
```

Optional advanced settings (defaults shown):

```dotenv
MCP_HOST=127.0.0.1
MCP_PORT=8080
# MCP_ALLOW_PUBLIC_BIND=1   # required only when MCP_HOST is non-loopback
```

---

## 3 — Generate a path secret

The path secret must be at least 24 random characters. Generate one:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Paste the result into `MCP_PATH_SECRET` in `.env`. Never commit `.env`.

---

## 4 — Start the server

From the `strava-coach-mcp/` directory:

```bash
python src/server.py
```

You should see, within ~5 seconds, a single line like:

```
READY: strava-coach @ 127.0.0.1:8080/<MCP_PATH_SECRET:redacted>/mcp
```

If you see an `ERROR:` line instead, the most common causes are:
- `MCP_PATH_SECRET must be set and ≥ 24 chars` — re-run step 3.
- `transport 'streamable-http' not supported by mcp X.Y` — upgrade with
  `pip install -U 'mcp>=1.8.0'`.
- `STRAVA_REFRESH_TOKEN` missing or unparsable — re-run the OAuth bootstrap.

---

## 5 — Smoke test (User Story 1)

Open a second terminal. With the server still running, run the smoke script
that ships with this feature:

```bash
python scripts/smoke.py
```

This invokes all three tools against the local server and asserts each
response parses as JSON with the expected top-level fields. Total wall time
should be under 30 seconds (SC-005). Output:

```
[1/3] list_recent_activities(limit=5)  ✓  5 rows, 1.2 KB
[2/3] get_weekly_summary(weeks=4)      ✓  4 rows, 0.4 KB
[3/3] get_activity_detail(<id>)        ✓  miss → computed, 3.7 KB
All checks passed.
```

If you'd rather use **MCP Inspector** (https://github.com/modelcontextprotocol/inspector)
interactively, point it at `http://127.0.0.1:8080/<your-secret>/mcp`
(streamable-HTTP transport).

---

## 6 — Auth probe (User Story 2)

While the server is still running, confirm the path-secret gate from a third
terminal:

```bash
# Correct path → handshake works (smoke.py already proved this).
# Wrong / missing path → must 404 with no MCP-shaped body.

curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/mcp
# expect: 404

curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/wrong-secret/mcp
# expect: 404

curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/
# expect: 404
```

Also re-start the server with `MCP_PATH_SECRET=""` to confirm step (5) of
the startup contract: the process must exit immediately with code 1 and the
named error.

```bash
MCP_PATH_SECRET="" python src/server.py
echo "exit=$?"
# expect: ERROR: MCP_PATH_SECRET must be set and ≥ 24 chars
# expect: exit=1
```

---

## 7 — Optional: end-to-end through a tunnel (User Story 3)

This step exercises the full claude.ai → tunnel → MCP → tool path. Skip if
you only need the local smoke.

1. With the server running on `127.0.0.1:8080`, in a separate terminal:

   ```bash
   cloudflared tunnel --url http://127.0.0.1:8080
   # or:
   ngrok http 8080
   ```

   Copy the public HTTPS URL the tunnel prints, e.g. `https://abc-123.trycloudflare.com`.

2. In claude.ai:
   - Open **Settings → Connectors**.
   - Click **Add custom connector**.
   - URL: `https://abc-123.trycloudflare.com/<your-secret>/mcp`
   - Leave OAuth Client ID / Secret empty (we're using path-secret).
   - Save.

3. In a Claude chat, ask: *"Use the strava-coach connector to list my last
   five activities."* Claude should call `list_recent_activities` and
   summarise the returned JSON.

If the connector reports a health failure, the three most likely causes are:
- The tunnel went down (re-run cloudflared/ngrok).
- The URL is missing `/mcp` after the secret.
- The cert chain is not publicly-trusted (cloudflared and ngrok handle this
  automatically; bespoke proxies may not).

---

## What to file as the PR

When this feature is implemented, the PR description MUST cite the two
research URLs from `research.md` (R1 and R5) and link to this quickstart.
That satisfies constitution Principle V (verify live docs) and SC-007 (a
maintainer can audit the verification without leaving the repo).
