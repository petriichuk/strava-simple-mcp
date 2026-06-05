# Security policy

## Supported versions

This is a single-user personal-deployment project; there is no formal
released-version support window. The `main` branch is the supported version.
Security-affecting fixes land on `main`; if you're running from a fork, pull
from `main` to receive them.

## Reporting a vulnerability

If you find a security issue — anything that could let an attacker read or
modify another user's data, escape the path-secret auth gate, or compromise
a deployed instance — please **do not** open a public issue. Instead, file
a private [security advisory](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) via the GitHub
Security tab on this repository, or email the project owner (see
[CONTRIBUTING.md](CONTRIBUTING.md) for contact).

Please include:

- A clear description of the issue and impact.
- Steps to reproduce, or a proof-of-concept.
- The commit / version you reproduced it on.

We'll respond within 7 days with an assessment and a planned timeline. Fixes
typically land on `main` within 14 days for high-impact issues.

## Threat model and explicit limitations

This server is built around a few load-bearing assumptions. Understanding them
is part of operating it safely.

1. **The path secret is the auth gate.** Anyone who can read the connector
   URL — request logs, browser history, screen-shares — can access your
   Strava data through the server. Specifically:
   - The URL ends up in any HTTP intermediary's access logs by default.
     Configure nginx / cloudflared / your reverse proxy to redact the path
     segment before logging.
   - Don't paste the connector URL into chat transcripts, gists, or shared
     docs. Treat it like a password.
   - Rotate the secret if it leaks. Re-register the connector URL in
     claude.ai afterwards.

2. **The path-secret approach is not Anthropic's blessed flow.** Claude.ai
   officially supports authless or OAuth 2.1 + PKCE. Path-secret is the
   de-facto community fallback. OAuth 2.1 is on the roadmap; until it lands,
   this server is appropriate for single-user personal deployments, not for
   serving multiple users.

3. **`STRAVA_CLIENT_SECRET` and `STRAVA_REFRESH_TOKEN` are sensitive.**
   They grant read access to your Strava history with `activity:read_all`
   scope. The server reads them from `.env` and persists rotated refresh
   tokens to `coach.db`. Neither file should ever be committed; both are in
   `.gitignore`. If a credential leaks:
   - Rotate `STRAVA_CLIENT_SECRET` at https://www.strava.com/settings/api
     ("Revoke and create new"). This invalidates all refresh tokens issued
     under the old secret.
   - Re-run the OAuth bootstrap to mint a fresh refresh token, paste into
     `.env`, then `sqlite3 coach.db 'DELETE FROM tokens;'` and restart the
     server.

4. **The server is loopback-only by default.** It refuses to bind a
   non-loopback interface unless `MCP_ALLOW_PUBLIC_BIND=1` is explicitly set.
   Combined with TLS termination at nginx, this makes accidental public
   exposure significantly harder.

5. **`MCP_ALLOWED_HOSTS=*` disables the SDK's DNS-rebinding protection.**
   This is intentional and acceptable when the path-secret is the actual auth
   control, but for production deployments behind a known domain, prefer
   `MCP_ALLOWED_HOSTS=your-domain.com` over `*`.

## Out of scope

Reports about:

- Strava's own infrastructure
- Anthropic's claude.ai connector flow (please report those to Anthropic)
- The `mcp` Python SDK (please report those upstream at
  https://github.com/modelcontextprotocol/python-sdk)

are out of scope for this repository's security policy, though we'll happily
help triage if you're unsure where to file.
