"""Strava Coach MCP server.

Streamable-HTTP transport mounted at /<MCP_PATH_SECRET>/mcp. No LLM calls
and no plan-memory storage (constitution principles I + III). Tools return
compact JSON only; raw streams are reduced server-side (principle II).

Run locally:  python src/server.py
"""
from __future__ import annotations

import importlib.metadata as _md
import json
import os
import sys
import time

# ---- Phase 2 / T004: load .env BEFORE any os.environ.get below -----------
from dotenv import load_dotenv

load_dotenv()


# ---- Phase 2 / T005: MCP SDK version gate --------------------------------

MIN_MCP_VERSION = (1, 8, 0)
_MCP_DOC_URL = "https://github.com/modelcontextprotocol/python-sdk"


def _parse_version(s: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in s.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts[:3]) or (0,)


def _check_mcp_version() -> None:
    try:
        installed = _md.version("mcp")
    except _md.PackageNotFoundError:
        print(
            "ERROR: mcp package not installed. Run: pip install -r requirements.txt",
            file=sys.stderr,
        )
        sys.exit(1)
    if _parse_version(installed) < MIN_MCP_VERSION:
        need = ".".join(map(str, MIN_MCP_VERSION))
        print(
            f"ERROR: mcp {installed} does not support streamable-HTTP transport; "
            f"need >= {need}. See {_MCP_DOC_URL}",
            file=sys.stderr,
        )
        sys.exit(1)


# ---- Phase 4 / T010: path-secret validator -------------------------------

_PATH_SECRET_MIN_LEN = 24


def _check_path_secret(value: str | None) -> str:
    if not value or len(value) < _PATH_SECRET_MIN_LEN:
        print(
            f"ERROR: MCP_PATH_SECRET must be set and >= {_PATH_SECRET_MIN_LEN} chars",
            file=sys.stderr,
        )
        sys.exit(1)
    return value


# ---- Phase 4 / T011: loopback-bind validator -----------------------------

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _check_bind_host(host: str) -> None:
    if host in _LOOPBACK_HOSTS:
        return
    if os.environ.get("MCP_ALLOW_PUBLIC_BIND") == "1":
        return
    print(
        f"ERROR: refusing to bind {host}; set MCP_ALLOW_PUBLIC_BIND=1 to opt in",
        file=sys.stderr,
    )
    sys.exit(1)


def _configure_allowed_hosts(mcp_instance) -> None:
    """Extend the SDK's DNS-rebinding-protection allow-list.

    The MCP SDK ships with allowed_hosts = ['127.0.0.1:*', 'localhost:*',
    '[::1]:*'] and 421s any request whose Host header isn't on that list.
    That breaks tunnel-based testing (cloudflared / ngrok) and any EC2 host.

    Read MCP_ALLOWED_HOSTS (comma-separated). Special value `*` disables the
    check entirely (safe here because the path-secret is the actual auth
    gate — see constitution Principle IV; Host validation is defense in
    depth, not the primary control).
    """
    raw = os.environ.get("MCP_ALLOWED_HOSTS", "").strip()
    if not raw:
        return  # keep SDK defaults (loopback only)
    extras = [s.strip() for s in raw.split(",") if s.strip()]
    sec = mcp_instance.settings.transport_security
    if "*" in extras:
        sec.enable_dns_rebinding_protection = False
        return
    existing = list(sec.allowed_hosts)
    for host in extras:
        if ":" in host:
            existing.append(host)
        else:
            existing.extend([host, f"{host}:*"])
    sec.allowed_hosts = existing


# Run the version gate before importing mcp so a bad version yields a clean
# error rather than an ImportError mid-stack.
_check_mcp_version()


# ---- Heavy imports (only after version gate) -----------------------------

import requests  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

import cache  # noqa: E402
import metrics  # noqa: E402
from strava import StravaClient  # noqa: E402


# ---- Module-level state (Strava client, SQLite cache) --------------------

cache.init_db()
strava = StravaClient()
mcp = FastMCP("strava-custom")


# ---- Helpers (preserved from the original scaffold) ----------------------

def _sync_new() -> int:
    """Pull only activities newer than last sync; cache compact summaries."""
    last = cache.get_last_synced()
    rows = strava.activities(after_epoch=last)
    if rows:
        cache.upsert_activities(rows)
    cache.set_last_synced(int(time.time()))
    return len(rows)


def _fmt_pace(speed_ms):
    if not speed_ms:
        return None
    secs = 1000.0 / speed_ms
    return f"{int(secs // 60)}:{int(secs % 60):02d}/km"


# ---- Phase 4 / T014: error envelope --------------------------------------

def _error_envelope(exc: Exception) -> dict:
    """Map Strava / network failures to the contracts/mcp-tools.md error shape."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(exc, requests.HTTPError) and status == 401:
        return {
            "error": "strava_auth_expired",
            "message": (
                "Strava refresh token rejected. Re-run the one-time OAuth "
                "bootstrap to re-seed STRAVA_REFRESH_TOKEN in .env."
            ),
        }
    if isinstance(exc, requests.HTTPError) and status == 404:
        return {
            "error": "activity_not_found",
            "message": "Strava returned 404 for this activity_id.",
        }
    if isinstance(exc, requests.HTTPError) and status and 500 <= status < 600:
        return {
            "error": "strava_unavailable",
            "message": f"Strava {status}; please retry.",
        }
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return {
            "error": "strava_unavailable",
            "message": "Network failure reaching Strava; please retry.",
        }
    return {"error": "internal", "message": "internal error; see server logs"}


# ---- Phase 3 / T006: MCP tools ------------------------------------------
#
# Function bodies preserved from the scaffold (constitution principle VI:
# reuse stable modules). The only addition is a try/except wrapper that
# translates exceptions into the named error envelope per FR-012.

@mcp.tool()
def list_recent_activities(limit: int = 20) -> str:
    """Sync new Strava activities; return compact summaries of the most recent ones."""
    try:
        _sync_new()
        out = []
        for a in cache.recent_activities(limit):
            out.append({
                "id": a["id"],
                "date": (a["start_date"] or "")[:10],
                "type": a["type"],
                "distance_km": round((a["distance_m"] or 0) / 1000.0, 2),
                "duration_min": round((a["moving_time_s"] or 0) / 60.0, 1),
                "avg_pace": _fmt_pace(a["avg_speed_ms"]),
                "avg_hr": a["avg_hr"],
            })
        return json.dumps(out, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 — MCP boundary translation
        return json.dumps(_error_envelope(exc), ensure_ascii=False)


@mcp.tool()
def get_weekly_summary(weeks: int = 8) -> str:
    """Weekly training rollup: distance, run count, and total time per ISO week."""
    try:
        _sync_new()
        out = []
        for w in cache.weekly_rollup(weeks):
            out.append({
                "week": f"{w['iso_year']}-W{w['iso_week']:02d}",
                "runs": w["runs"],
                "km": w["km"],
                "hours": round((w["time_s"] or 0) / 3600.0, 1),
            })
        return json.dumps(out, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return json.dumps(_error_envelope(exc), ensure_ascii=False)


@mcp.tool()
def get_activity_detail(activity_id: int) -> str:
    """Detailed analysis of one activity: km splits, first/second-half HR & pace,
    HR drift, Pa:HR decoupling, and time-in-zone. Computed once, then cached."""
    try:
        cached = cache.get_metrics(activity_id)
        if cached:
            return json.dumps(cached, ensure_ascii=False)

        detail = strava.activity_detail(activity_id)
        streams = strava.activity_streams(activity_id)
        try:
            zones = strava.activity_zones(activity_id)
        except Exception:
            zones = []

        result = {
            "id": activity_id,
            "name": detail.get("name"),
            "date": (detail.get("start_date_local") or "")[:10],
            "distance_km": round((detail.get("distance") or 0) / 1000.0, 2),
            "official_splits_metric": [
                {
                    "km": s.get("split"),
                    "pace": _fmt_pace(s.get("average_speed")),
                    "avg_hr": s.get("average_heartrate"),
                    "elev": s.get("elevation_difference"),
                }
                for s in (detail.get("splits_metric") or [])
            ],
            "stream_metrics": metrics.compute_stream_metrics(streams),
            "time_in_zone": metrics.summarise_zones(zones),
        }
        cache.save_metrics(activity_id, result)
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return json.dumps(_error_envelope(exc), ensure_ascii=False)


# ---- Phase 4 / T013: log redaction middleware ----------------------------
#
# uvicorn's default access logger renders the full request path, which would
# leak MCP_PATH_SECRET into stdout / journald. We disable that logger
# (access_log=False below) and instead emit a single-line shape-only log:
#   {METHOD} {STATUS} {duration_ms}ms
# No path. No referer. No headers.

class _NoPathLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 1)
        print(f"{request.method} {response.status_code} {elapsed_ms}ms", flush=True)
        return response


# ---- Phase 3 / T007: entry point ----------------------------------------

def _redact_secret(secret: str) -> str:
    """Show only the first/last 4 chars of the path secret in logs."""
    if len(secret) <= 8:
        return "***"
    return f"{secret[:4]}***{secret[-4:]}"


def main() -> None:
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port_raw = os.environ.get("MCP_PORT", "8080")
    secret = _check_path_secret(os.environ.get("MCP_PATH_SECRET"))
    _check_bind_host(host)

    try:
        port = int(port_raw)
    except ValueError:
        print(f"ERROR: MCP_PORT must be an integer, got {port_raw!r}", file=sys.stderr)
        sys.exit(1)

    # Mount the streamable-HTTP endpoint under the secret prefix.
    # Anything that doesn't match /<secret>/mcp will hit Starlette's default
    # 404, which returns a generic body that does not reveal an MCP server
    # (audited at T012; no explicit catch-all needed).
    mcp.settings.streamable_http_path = f"/{secret}/mcp"

    # Open the SDK's DNS-rebinding protection list to whatever public host
    # we're being served behind (tunnel hostname, EC2 domain). See
    # _configure_allowed_hosts docstring.
    _configure_allowed_hosts(mcp)

    asgi_app = mcp.streamable_http_app()
    asgi_app.add_middleware(_NoPathLogMiddleware)

    print(
        f"READY: strava-custom @ {host}:{port}/<MCP_PATH_SECRET:{_redact_secret(secret)}>/mcp",
        flush=True,
    )

    # uvicorn handles the streamable_http_app's lifespan automatically when
    # invoked this way (no FastAPI/Starlette parent-mount lifespan bug —
    # see research R2).
    import uvicorn

    uvicorn.run(
        asgi_app,
        host=host,
        port=port,
        access_log=False,  # T013: kill default path-logging access log
        log_level="warning",
    )


if __name__ == "__main__":
    main()
