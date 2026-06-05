#!/usr/bin/env python3
"""Diagnose Strava auth + cached token state.

Reads `.env`, then:
 1. Confirms the three required Strava env vars are present.
 2. Inspects `coach.db` for any cached `tokens` row (a stale row can
    override the env value).
 3. Calls Strava's `/oauth/token` directly with `grant_type=refresh_token`
    and the credentials in `.env` to see what Strava itself says.

Prints actionable next steps. Never prints token values.

Usage:
    cd strava-simple-mcp
    python scripts/diag_strava.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

load_dotenv(_PROJECT_ROOT / ".env")

_TOKEN_URL = "https://www.strava.com/oauth/token"
_REQUIRED = ("STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN")


def _mask(value: str | None, keep: int = 4) -> str:
    if not value:
        return "<missing>"
    if len(value) <= keep * 2:
        return "***"
    return f"{value[:keep]}...{value[-keep:]} (len={len(value)})"


def step1_env() -> bool:
    print("== 1. Environment ==")
    ok = True
    for key in _REQUIRED:
        val = os.environ.get(key)
        status = "ok " if val else "MISSING"
        print(f"  {status}  {key} = {_mask(val)}")
        if not val:
            ok = False
    return ok


def step2_cache() -> None:
    print()
    print("== 2. SQLite token cache ==")
    db_path = _PROJECT_ROOT / os.environ.get("COACH_DB_PATH", "coach.db")
    if not db_path.exists():
        print(f"  {db_path.name} does not exist yet (no cached tokens — fine)")
        return
    try:
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT * FROM tokens WHERE id = 1").fetchone()
        c.close()
    except sqlite3.OperationalError as exc:
        print(f"  could not read tokens table: {exc}")
        return
    if not row:
        print("  no cached tokens row — server will use .env value on next call (good)")
        return
    expires_at = row["expires_at"] or 0
    print(f"  CACHED tokens row exists in {db_path.name}:")
    print(f"    refresh_token: {_mask(row['refresh_token'])}")
    print(f"    access_token:  {_mask(row['access_token'])}")
    print(f"    expires_at:    {expires_at}")
    env_refresh = os.environ.get("STRAVA_REFRESH_TOKEN", "")
    if env_refresh and row["refresh_token"] != env_refresh:
        print(
            "  NOTE: cached refresh_token differs from .env — the server uses the\n"
            "        cached value (it may be rotated). If that cached value is\n"
            "        invalid, the diagnostic below will catch it."
        )


def step3_refresh() -> int:
    print()
    print("== 3. Live Strava /oauth/token check ==")

    # Prefer the cached refresh token if present (that's what the running
    # server actually uses), fall back to env.
    refresh_token = os.environ.get("STRAVA_REFRESH_TOKEN", "")
    db_path = _PROJECT_ROOT / os.environ.get("COACH_DB_PATH", "coach.db")
    if db_path.exists():
        try:
            c = sqlite3.connect(str(db_path))
            c.row_factory = sqlite3.Row
            row = c.execute("SELECT refresh_token FROM tokens WHERE id = 1").fetchone()
            c.close()
            if row and row["refresh_token"]:
                refresh_token = row["refresh_token"]
                print("  (using cached refresh_token from coach.db)")
        except sqlite3.OperationalError:
            pass

    if not refresh_token:
        print("  no refresh_token available — fix .env first")
        return 1

    try:
        r = requests.post(
            _TOKEN_URL,
            data={
                "client_id": os.environ.get("STRAVA_CLIENT_ID", ""),
                "client_secret": os.environ.get("STRAVA_CLIENT_SECRET", ""),
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"  network error reaching Strava: {exc!r}")
        return 2

    print(f"  Strava status: {r.status_code}")
    print()
    if r.status_code == 200:
        data = r.json()
        keys = sorted(data.keys())
        print("  SUCCESS — refresh works. Returned keys:", keys)
        if "refresh_token" in data and data["refresh_token"] != refresh_token:
            print("  Strava ROTATED your refresh token. Expected — that's how Strava")
            print("  works. The server persists rotations to coach.db automatically.")
        print()
        print("  Diagnosis: Strava is happy. If chat still reports auth failure,")
        print("  look for a stale row in coach.db (step 2) or a server still using")
        print("  an old token in memory — restart with `pkill -f src/server.py;")
        print("  python src/server.py`.")
        return 0

    body = r.text[:300]
    print(f"  body: {body}")
    print()
    if r.status_code == 401:
        print("  Diagnosis: 401 means the refresh_token + client_secret pair is")
        print("  invalid. Most common cause: client_secret was rotated AFTER the")
        print("  refresh_token was generated.")
        print()
        print("  Fix:")
        print("    1. Confirm STRAVA_CLIENT_SECRET in .env matches the current")
        print("       value at https://www.strava.com/settings/api.")
        print("    2. Re-do the one-time OAuth bootstrap to mint a fresh")
        print("       refresh_token under the CURRENT secret:")
        print("       a. Browser-authorize with scope=activity:read_all.")
        print("       b. Exchange the redirect's `code` via POST to /oauth/token")
        print("          with grant_type=authorization_code.")
        print("       c. Paste the returned refresh_token into .env.")
        print("    3. Wipe any stale cached row:")
        print("       sqlite3 coach.db 'DELETE FROM tokens;'")
        print("    4. Restart the server.")
        return 1
    if r.status_code == 400:
        print("  Diagnosis: 400 typically means client_id / client_secret are")
        print("  malformed or unknown to Strava. Check both against the values at")
        print("  https://www.strava.com/settings/api.")
        return 1
    print("  Unexpected status. Strava is responding but neither success nor a")
    print("  known auth-failure shape. Treat as transient and retry, or check")
    print("  https://status.strava.com.")
    return 1


def main() -> int:
    ok = step1_env()
    step2_cache()
    if not ok:
        print()
        print("Cannot continue — populate the missing env vars in .env first.")
        return 1
    return step3_refresh()


if __name__ == "__main__":
    sys.exit(main())
