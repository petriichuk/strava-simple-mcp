# Changelog

All notable changes to this project will be documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-04

Initial open-source release.

### Added

- MCP streamable-HTTP server (`src/server.py`) with three tools:
  `list_recent_activities`, `get_weekly_summary`, `get_activity_detail`.
- Path-secret auth gate at `/<MCP_PATH_SECRET>/mcp`, with non-secret paths
  returning indistinguishable 404s.
- Startup validators: refuse to start without a ≥24-char `MCP_PATH_SECRET`;
  refuse non-loopback bind unless `MCP_ALLOW_PUBLIC_BIND=1`; refuse if the
  installed `mcp` SDK version is below the streamable-HTTP minimum.
- Log-redaction middleware: never logs the request path (keeps
  `MCP_PATH_SECRET` out of stdout / journald).
- Error envelope translating Strava 401 / 404 / 5xx / network failures into
  named codes (`strava_auth_expired`, `activity_not_found`,
  `strava_unavailable`, `internal`).
- `MCP_ALLOWED_HOSTS` env var to extend the MCP SDK's DNS-rebinding-protection
  allow-list (supports `*`, single hostnames, and comma-separated lists).
- Smoke scripts: `scripts/smoke.py` (tool shape + cold-start timing),
  `scripts/smoke_auth.py` (404 indistinguishability + bad-startup forks),
  `scripts/diag_strava.py` (Strava credential + cache state diagnostic).
- EC2 deploy scaffold: `ec2-deploy/` with nginx vhost +
  systemd unit + step-by-step README.
- Spec Kit design artifacts under `specs/001-finalize-server-transport-auth/`
  and the project [constitution](.specify/memory/constitution.md).

### Fixed

- Strava activities sync defect: the previous logic always passed `after=`
  to Strava's API, which silently switches results to ascending order. On
  cold start this caused the sync to pull the 200 oldest activities (from
  the start of recorded history) and stop. `strava.activities` now omits
  `after` when `after_epoch <= 0`, restoring descending-from-newest behavior
  on cold start.

### Security

- See [SECURITY.md](SECURITY.md) for the threat model and
  vulnerability-reporting process.
