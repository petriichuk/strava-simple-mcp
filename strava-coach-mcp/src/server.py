"""Strava Coach MCP server (scaffold).

Defines the tools. The TRANSPORT and AUTH at the bottom are the parts to verify
against current MCP SDK + Anthropic custom-connector docs (see SPEC.md) before
deploying — they're the most likely things to have changed.

Run locally for a smoke test:  python src/server.py
"""
from __future__ import annotations

import os
import time
import json

from mcp.server.fastmcp import FastMCP

import cache
import metrics
from strava import StravaClient

cache.init_db()
strava = StravaClient()
mcp = FastMCP("strava-coach")


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


# --------------------------------------------------------------------------- #
# Tools                                                                       #
# --------------------------------------------------------------------------- #

@mcp.tool()
def list_recent_activities(limit: int = 20) -> str:
    """Sync new Strava activities and return compact summaries of the most recent ones."""
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


@mcp.tool()
def get_weekly_summary(weeks: int = 8) -> str:
    """Weekly training rollup: distance, run count, and total time per ISO week."""
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


@mcp.tool()
def get_activity_detail(activity_id: int) -> str:
    """Detailed analysis of one activity: km splits, first/second-half HR & pace,
    HR drift, Pa:HR decoupling, and time-in-zone. Computed once, then cached."""
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
            {"km": s.get("split"), "pace": _fmt_pace(s.get("average_speed")),
             "avg_hr": s.get("average_heartrate"), "elev": s.get("elevation_difference")}
            for s in (detail.get("splits_metric") or [])
        ],
        "stream_metrics": metrics.compute_stream_metrics(streams),
        "time_in_zone": metrics.summarise_zones(zones),
    }
    cache.save_metrics(activity_id, result)
    return json.dumps(result, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Transport + auth  --  TODO: verify against current docs (see SPEC.md)       #
# --------------------------------------------------------------------------- #
# Anthropic connects from its cloud, so this must be public HTTPS. Protect it.
# Primary approach (works with the connector URL field): mount under a secret
# path. The secret lives in MCP_PATH_SECRET and is part of the connector URL.
#
# Pseudo-wiring (confirm exact SDK API — names may have changed):
#
#   from starlette.applications import Starlette
#   from starlette.routing import Mount
#   secret = os.environ["MCP_PATH_SECRET"]
#   app = Starlette(routes=[Mount(f"/{secret}", app=mcp.streamable_http_app())])
#   # serve with: uvicorn server:app --host 0.0.0.0 --port 8080
#   # nginx terminates TLS and proxies https://yourdomain/<secret>/mcp -> :8080
#
# Then in claude.ai: Settings -> Connectors -> Add custom connector ->
#   https://yourdomain/<secret>/mcp
#
# For local testing only:
if __name__ == "__main__":
    # Confirm the current transport keyword in your installed mcp version.
    mcp.run(transport="streamable-http")
