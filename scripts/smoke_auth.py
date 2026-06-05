"""Auth-gate smoke test for the Strava Coach MCP server.

Verifies the path-secret auth contract from `contracts/mount-and-auth.md`:

1. 404 indistinguishability — wrong / missing / partial paths return 404
   with no MCP-revealing body.
2. Bad-startup configs (missing / short secret, non-loopback bind without
   opt-in) exit with code 1 within a short timeout.

Run against a running server (the user's server, default localhost:8080).
For (2), this script spawns its own subprocesses with controlled env.

Exit code 0 = all checks pass; 1 = any failure.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_SERVER_PY = _PROJECT_ROOT / "src" / "server.py"

load_dotenv(_PROJECT_ROOT / ".env")


# ---- 1. Probe the live server for 404 indistinguishability ---------------

_FORBIDDEN_BODY_SUBSTRINGS = ("mcp", "MCP", "FastMCP", "strava-custom")


def _probe_404(label: str, url: str) -> bool:
    try:
        resp = requests.get(url, timeout=3, allow_redirects=False)
    except requests.RequestException as exc:
        print(f"[probe] FAIL {label}: request error {exc!r}")
        return False
    if resp.status_code != 404:
        print(f"[probe] FAIL {label}: expected 404, got {resp.status_code}")
        return False
    body = resp.text or ""
    leaked = [s for s in _FORBIDDEN_BODY_SUBSTRINGS if s in body]
    if leaked:
        print(f"[probe] FAIL {label}: 404 body leaks {leaked!r} (truncated: {body[:120]!r})")
        return False
    print(f"[probe] ok   {label} -> 404, body clean")
    return True


def probe_paths() -> bool:
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = os.environ.get("MCP_PORT", "8080")
    secret = os.environ.get("MCP_PATH_SECRET", "")
    base = f"http://{host}:{port}"
    if not secret:
        print("WARN: MCP_PATH_SECRET missing; skipping correct-path control probe")

    cases = [
        ("/",                     f"{base}/"),
        ("/mcp",                  f"{base}/mcp"),
        ("/wrong-secret/mcp",     f"{base}/wrong-secret-of-sufficient-length-here/mcp"),
    ]
    if secret:
        # Secret prefix without /mcp suffix — must also 404.
        cases.append((f"/<secret>", f"{base}/{secret}"))

    return all(_probe_404(label, url) for label, url in cases)


# ---- 2. Bad-startup subprocess tests -------------------------------------

_BAD_STARTUP_TIMEOUT_S = 3.0


def _run_bad_startup(label: str, env_overrides: dict[str, str]) -> bool:
    env = os.environ.copy()
    # Use a never-collide port so we don't fight the user's server.
    env["MCP_PORT"] = "8091"
    env.update(env_overrides)

    start = time.perf_counter()
    proc = subprocess.Popen(
        [sys.executable, str(_SERVER_PY)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
    )
    try:
        try:
            stdout, _ = proc.communicate(timeout=_BAD_STARTUP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=2)
            print(
                f"[startup] FAIL {label}: did not exit within "
                f"{_BAD_STARTUP_TIMEOUT_S}s (still running)"
            )
            return False
        elapsed = time.perf_counter() - start
        if proc.returncode != 1:
            print(
                f"[startup] FAIL {label}: expected exit code 1, got "
                f"{proc.returncode} (in {elapsed:.2f}s); stdout: {stdout[:200]!r}"
            )
            return False
        if "ERROR:" not in stdout:
            print(
                f"[startup] FAIL {label}: no 'ERROR:' line in stdout; got {stdout[:200]!r}"
            )
            return False
        print(f"[startup] ok   {label}: exit 1 in {elapsed:.2f}s")
        return True
    finally:
        if proc.poll() is None:
            proc.kill()


def bad_startup_cases() -> bool:
    # Inherit Strava creds so the validators are the *only* thing failing.
    # Each override mutates exactly one variable to isolate the failure mode.
    return all([
        _run_bad_startup(
            "missing MCP_PATH_SECRET",
            {"MCP_PATH_SECRET": ""},
        ),
        _run_bad_startup(
            "short MCP_PATH_SECRET",
            {"MCP_PATH_SECRET": "short-secret"},
        ),
        _run_bad_startup(
            "non-loopback bind without opt-in",
            {"MCP_HOST": "0.0.0.0", "MCP_ALLOW_PUBLIC_BIND": ""},
        ),
    ])


# ---- Main ----------------------------------------------------------------

def main() -> int:
    print("=== probe live server for 404 indistinguishability ===")
    probes_ok = probe_paths()
    print()
    print("=== fork bad-startup configs and assert exit code 1 ===")
    startup_ok = bad_startup_cases()
    print()
    if probes_ok and startup_ok:
        print("OK: auth smoke passed")
        return 0
    print("FAIL: auth smoke failed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
