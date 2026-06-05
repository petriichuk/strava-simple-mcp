# Contributing

Thanks for taking the time to look at this project. This is a small,
single-author personal-use codebase that has been opened up because the
plumbing might be useful to other people running the same Claude Max +
Strava workflow.

## How to contribute

- **Issues** — bug reports and feature ideas welcome. See the issue templates
  for what's useful to include. Please don't open issues for general MCP /
  Claude / Strava questions; those belong upstream.
- **Pull requests** — small, focused PRs are easiest to review. Include the
  motivation in the description (not just "what" but "why"); see the PR
  template.
- **Security issues** — see [SECURITY.md](SECURITY.md); please don't open a
  public issue.

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# In one terminal:
python src/server.py

# In another:
python scripts/smoke.py --measure-startup     # exercises the 3 tools
python scripts/smoke_auth.py                  # checks the auth gate
python scripts/diag_strava.py                 # diagnoses Strava auth state
```

`scripts/smoke.py` requires real Strava credentials in `.env`. The path-secret
and bad-startup checks in `scripts/smoke_auth.py` work with dummy creds.

## Project structure

The codebase lives in `src/`:

- `server.py` — MCP server: transport, auth, error envelope, the three tool
  definitions. **Most contributions land here.**
- `strava.py` — Strava API client. Stable; modifications must fix a defect
  or accommodate a Strava API change.
- `cache.py` — SQLite schema + helpers. Schema changes require careful
  thought; see the [constitution](.specify/memory/constitution.md)
  Principle III ("Cache, Not Memory").
- `metrics.py` — Pure-Python stream math (no numpy). Stable; PRs touching
  this should include reasoning about correctness with real cached fixtures.

## Conventions

- **Compact tool responses (constitution Principle II).** Tools must never
  return raw per-second stream arrays — reduce server-side. `scripts/smoke.py`
  enforces this with a structural check.
- **No LLM calls (constitution Principle I).** The server must not import
  any LLM SDK. All intelligence lives in chat.
- **No plan memory in SQLite (constitution Principle III).** Schema additions
  for goals / plans / typed-adjustments are out of scope.
- **No secrets in logs.** The log-redaction middleware (`_NoPathLogMiddleware`
  in `server.py`) emits method/status/duration only. PRs adding logging must
  preserve this.
- **No comments that just restate the code.** Comments are for surprising
  invariants, hidden constraints, or links to upstream docs. Naming should
  do the rest.

## Spec-driven workflow

The project was built with [Spec Kit](https://github.com/github/spec-kit).
Design artifacts live in `specs/`. New significant features should add a
spec there following the existing pattern (`spec.md` → `plan.md` →
`tasks.md`). Small fixes don't need a spec.

If you use Claude Code, the slash commands in `.claude/skills/` automate the
workflow. Otherwise, the templates in `.specify/templates/` are what you'd
copy from manually.

## Code style

- Python 3.11+.
- No formal style check enforced beyond `python -m py_compile` in CI. PRs
  using `ruff` or `black` formatting are welcome but not required.
- Type hints encouraged but not enforced.

## Testing

This project uses smoke scripts rather than a unit test suite. New behavior
should add a check to one of:

- `scripts/smoke.py` — for end-to-end tool behavior.
- `scripts/smoke_auth.py` — for auth-gate / startup-validation behavior.
- `scripts/diag_strava.py` — for Strava-credential diagnostic logic.

PRs that introduce a unit-test suite (e.g., pytest under `tests/`) are
welcome but should preserve the smoke scripts as the integration check.

## Contact

For non-security questions, the issue tracker is the right place. For
security-sensitive contact, see [SECURITY.md](SECURITY.md).
