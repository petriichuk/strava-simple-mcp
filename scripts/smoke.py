"""Smoke test for the Strava Coach MCP server.

Drives the three tools against a locally-running server and asserts each
response matches the contracts/mcp-tools.md shape. Optionally measures
cold-start time (SC-004) when invoked with --measure-startup.

Usage:
    python scripts/smoke.py                   # tools-only smoke
    python scripts/smoke.py --measure-startup # also spawn a fresh server
                                              # and assert ready < 5s

Exit code 0 = all checks pass; 1 = any failure.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# Make the smoke script runnable from anywhere — resolve the project root
# so we can locate src/server.py without depending on cwd.
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_PROJECT_ROOT / ".env")

# We import the mcp client lazily inside main(), after the version gate has
# implicitly passed (the user wouldn't reach this script otherwise).


# ---- Contract assertions -------------------------------------------------

_MAX_TOP_LEVEL_ARRAY = 200  # FR-007 / U1: structural proxy for "no raw streams"


def _walk_arrays(obj, path="$"):
    """Yield (path, length) for every list found anywhere in obj."""
    if isinstance(obj, list):
        yield path, len(obj)
        for i, item in enumerate(obj):
            yield from _walk_arrays(item, f"{path}[{i}]")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_arrays(v, f"{path}.{k}")


def _assert_no_raw_streams(name: str, parsed) -> None:
    for path, length in _walk_arrays(parsed):
        if length > _MAX_TOP_LEVEL_ARRAY:
            raise AssertionError(
                f"{name}: array at {path} has {length} elements (>{_MAX_TOP_LEVEL_ARRAY}); "
                "looks like a raw stream — violates FR-007"
            )


def _assert_list_recent_shape(parsed) -> None:
    if "error" in (parsed if isinstance(parsed, dict) else {}):
        raise AssertionError(f"list_recent_activities returned error envelope: {parsed}")
    if not isinstance(parsed, list):
        raise AssertionError(f"list_recent_activities expected list, got {type(parsed).__name__}")
    if not parsed:
        return  # empty is fine for a fresh cache
    row = parsed[0]
    required = {"id", "date", "type", "distance_km", "duration_min", "avg_pace", "avg_hr"}
    missing = required - set(row.keys())
    if missing:
        raise AssertionError(f"list_recent_activities row missing keys: {missing}")


def _assert_weekly_shape(parsed) -> None:
    if isinstance(parsed, dict) and "error" in parsed:
        raise AssertionError(f"get_weekly_summary returned error envelope: {parsed}")
    if not isinstance(parsed, list):
        raise AssertionError(f"get_weekly_summary expected list, got {type(parsed).__name__}")
    if not parsed:
        return
    required = {"week", "runs", "km", "hours"}
    missing = required - set(parsed[0].keys())
    if missing:
        raise AssertionError(f"get_weekly_summary row missing keys: {missing}")


def _assert_detail_shape(parsed) -> None:
    if isinstance(parsed, dict) and "error" in parsed:
        raise AssertionError(f"get_activity_detail returned error envelope: {parsed}")
    if not isinstance(parsed, dict):
        raise AssertionError(f"get_activity_detail expected dict, got {type(parsed).__name__}")
    required = {"id", "date", "distance_km", "official_splits_metric",
                "stream_metrics", "time_in_zone"}
    missing = required - set(parsed.keys())
    if missing:
        raise AssertionError(f"get_activity_detail missing keys: {missing}")


# ---- MCP client driver ---------------------------------------------------

async def _call_tools(url: str) -> int:
    """Connect to the running server, invoke 3 tools, assert each shape.
    Returns the count of (always 3) tools exercised on success."""
    from mcp import ClientSession  # type: ignore
    from mcp.client.streamable_http import streamablehttp_client  # type: ignore

    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1/3 -- list_recent_activities
            t0 = time.perf_counter()
            res = await session.call_tool("list_recent_activities", {"limit": 5})
            payload = _extract_text(res)
            parsed = json.loads(payload)
            _assert_list_recent_shape(parsed)
            _assert_no_raw_streams("list_recent_activities", parsed)
            print(
                f"[1/3] list_recent_activities(limit=5)  ok  "
                f"{len(parsed) if isinstance(parsed, list) else 0} rows, "
                f"{len(payload)} bytes, {(time.perf_counter()-t0)*1000:.0f}ms"
            )

            # Pick an id from the list to drive detail (if available).
            sample_id = parsed[0]["id"] if isinstance(parsed, list) and parsed else None

            # 2/3 -- get_weekly_summary
            t0 = time.perf_counter()
            res = await session.call_tool("get_weekly_summary", {"weeks": 4})
            payload = _extract_text(res)
            parsed = json.loads(payload)
            _assert_weekly_shape(parsed)
            _assert_no_raw_streams("get_weekly_summary", parsed)
            print(
                f"[2/3] get_weekly_summary(weeks=4)      ok  "
                f"{len(parsed) if isinstance(parsed, list) else 0} rows, "
                f"{len(payload)} bytes, {(time.perf_counter()-t0)*1000:.0f}ms"
            )

            # 3/3 -- get_activity_detail (skipped if cache empty)
            if sample_id is None:
                print(
                    "[3/3] get_activity_detail              skip (no activities cached "
                    "yet; rerun after at least one Strava sync)"
                )
                return 2
            t0 = time.perf_counter()
            res = await session.call_tool("get_activity_detail", {"activity_id": sample_id})
            payload = _extract_text(res)
            parsed = json.loads(payload)
            _assert_detail_shape(parsed)
            _assert_no_raw_streams("get_activity_detail", parsed)
            print(
                f"[3/3] get_activity_detail({sample_id})  ok  "
                f"{len(payload)} bytes, {(time.perf_counter()-t0)*1000:.0f}ms"
            )
            return 3


def _extract_text(call_result) -> str:
    """Extract the JSON string from an MCP tool-call result."""
    # Tools return a single TextContent block whose `.text` is the JSON payload.
    content = getattr(call_result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            return text
    raise AssertionError(f"no text content in tool result: {call_result!r}")


# ---- Cold-start measurement (SC-004) -------------------------------------

_READY_TIMEOUT_S = 5.0


def _measure_cold_start() -> float:
    """Spawn a fresh server subprocess, time process-spawn -> READY: log line.

    Returns elapsed seconds. Raises AssertionError if no READY: line appears
    within _READY_TIMEOUT_S.

    Assumes the parent process has the same .env populated, so the child
    inherits MCP_PATH_SECRET etc.
    """
    server_py = _PROJECT_ROOT / "src" / "server.py"
    env = os.environ.copy()
    # Use a different port to avoid collision with the user's running server.
    env["MCP_PORT"] = env.get("MCP_PORT_SMOKE", "8089")

    start = time.perf_counter()
    proc = subprocess.Popen(
        [sys.executable, str(server_py)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
        bufsize=1,
    )
    try:
        while True:
            elapsed = time.perf_counter() - start
            if elapsed > _READY_TIMEOUT_S:
                raise AssertionError(
                    f"cold-start exceeded {_READY_TIMEOUT_S}s without READY: line "
                    "(SC-004 violation)"
                )
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                # process exited before READY
                if proc.poll() is not None:
                    raise AssertionError(
                        f"server exited during cold-start (rc={proc.returncode}) "
                        "before emitting READY:"
                    )
                continue
            if line.startswith("READY:"):
                return time.perf_counter() - start
    finally:
        proc.send_signal(signal.SIGTERM)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=3)
        if proc.poll() is None:
            proc.kill()


# ---- Main ----------------------------------------------------------------

def _build_url() -> str:
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = os.environ.get("MCP_PORT", "8080")
    secret = os.environ.get("MCP_PATH_SECRET")
    if not secret:
        print("ERROR: MCP_PATH_SECRET missing from environment / .env", file=sys.stderr)
        sys.exit(1)
    return f"http://{host}:{port}/{secret}/mcp"


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test the Strava Coach MCP server.")
    parser.add_argument(
        "--measure-startup",
        action="store_true",
        help="also spawn a fresh server subprocess and assert cold-start < 5s (SC-004)",
    )
    args = parser.parse_args()

    print(f"smoke target: {_build_url().replace(os.environ.get('MCP_PATH_SECRET', ''), '<secret>')}")

    overall_start = time.perf_counter()

    if args.measure_startup:
        elapsed = _measure_cold_start()
        if elapsed > 5.0:
            print(f"[startup] FAIL cold-start {elapsed:.2f}s (SC-004 budget 5s)")
            return 1
        print(f"[startup] ok    cold-start {elapsed:.2f}s (SC-004 budget 5s)")

    try:
        exercised = asyncio.run(_call_tools(_build_url()))
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: unexpected error: {exc!r}", file=sys.stderr)
        return 1

    total = time.perf_counter() - overall_start
    if total > 30.0:
        print(f"WARN: total wall time {total:.1f}s exceeds 30s budget (SC-005)")
    print(f"OK: {exercised}/3 tools exercised in {total:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
