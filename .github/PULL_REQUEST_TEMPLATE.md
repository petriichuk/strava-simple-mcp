<!--
Thank you for the PR! Please fill in each section so the reviewer can
understand the change quickly. Keep it short — bullets are fine.
-->

## What

<!-- One paragraph: what the PR changes. Not "why" yet. -->

## Why

<!-- Motivation. Link to an issue if there is one. -->

## Tested how

<!-- One or more of:
- Ran `python scripts/smoke.py --measure-startup` against a live server.
- Ran `python scripts/smoke_auth.py`.
- Ran `python scripts/diag_strava.py`.
- Added a new check in scripts/<file>.py.
- Manual claude.ai connector test through a tunnel.
-->

## Constitution check

<!-- The project [constitution](../.specify/memory/constitution.md) is
non-negotiable. Confirm or explain. -->

- [ ] No LLM calls added on the server (Principle I).
- [ ] No raw per-second stream arrays returned to the client (Principle II).
- [ ] No plan / goal / training-adjustment storage added to SQLite (Principle III).
- [ ] Path-secret or other auth gate is preserved on any new endpoint (Principle IV).
- [ ] If modifying `strava.py` / `cache.py` / `metrics.py`: this fixes a defect or accommodates a Strava API change (Principle VI). Briefly explain below.

## Breaking?

<!-- Yes / no. If yes, describe the migration path. -->

## Anything else reviewers should know
