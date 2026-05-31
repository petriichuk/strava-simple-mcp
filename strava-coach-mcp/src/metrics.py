"""Compute compact metrics from Strava streams.

Pure Python (no numpy) for portability. The whole point: turn thousands of
per-second samples into a handful of numbers Claude can reason over.

Key outputs:
  - first/second half avg HR and avg pace (your "HR on half the distance" ask)
  - Pa:HR decoupling % (aerobic durability — drift of pace-to-HR across the run)
  - HR drift % (simple second-half vs first-half HR change)
  - binned splits (per ~1 km) with pace + HR
  - time-in-zone (from Strava's /zones endpoint when available)
"""
from __future__ import annotations


def _pace_min_per_km(speed_ms: float) -> float | None:
    if not speed_ms or speed_ms <= 0:
        return None
    return round((1000.0 / speed_ms) / 60.0, 3)  # minutes per km


def _avg(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def compute_stream_metrics(streams: dict, split_m: float = 1000.0) -> dict:
    """`streams` is Strava's key_by_type response: {type: {"data": [...]}, ...}."""
    dist = streams.get("distance", {}).get("data") or []
    hr = streams.get("heartrate", {}).get("data") or []
    vel = streams.get("velocity_smooth", {}).get("data") or []
    n = min(len(dist), len(hr) if hr else len(dist), len(vel) if vel else len(dist))
    if n < 2 or not dist:
        return {"note": "insufficient stream data"}

    total = dist[n - 1]
    half = total / 2.0

    # --- split at half distance ---
    mid = next((i for i in range(n) if dist[i] >= half), n // 2)

    def seg_speed(a: int, b: int) -> float | None:
        # average speed over a segment from distance/time if velocity missing
        if vel:
            return _avg(vel[a:b])
        return None

    first = {
        "avg_hr": _avg(hr[:mid]) if hr else None,
        "avg_pace_min_km": _pace_min_per_km(seg_speed(0, mid)) if vel else None,
    }
    second = {
        "avg_hr": _avg(hr[mid:n]) if hr else None,
        "avg_pace_min_km": _pace_min_per_km(seg_speed(mid, n)) if vel else None,
    }

    # --- HR drift (simple) ---
    hr_drift_pct = None
    if first["avg_hr"] and second["avg_hr"]:
        hr_drift_pct = round((second["avg_hr"] / first["avg_hr"] - 1) * 100, 1)

    # --- Pa:HR decoupling --- ratio of (HR/speed) second half vs first half ---
    decoupling_pct = None
    if hr and vel:
        s1, s2 = seg_speed(0, mid), seg_speed(mid, n)
        h1, h2 = first["avg_hr"], second["avg_hr"]
        if s1 and s2 and h1 and h2:
            r1, r2 = h1 / s1, h2 / s2  # beats per (m/s); higher = more cardiac cost per pace
            decoupling_pct = round((r2 / r1 - 1) * 100, 1)

    # --- binned splits ---
    splits = []
    next_mark = split_m
    seg_start = 0
    for i in range(n):
        if dist[i] >= next_mark or i == n - 1:
            seg = slice(seg_start, i + 1)
            splits.append({
                "km": round(next_mark / 1000.0, 1),
                "avg_hr": _avg(hr[seg]) if hr else None,
                "avg_pace_min_km": _pace_min_per_km(_avg(vel[seg])) if vel else None,
            })
            seg_start = i
            next_mark += split_m

    return {
        "total_distance_km": round(total / 1000.0, 2),
        "first_half": first,
        "second_half": second,
        "hr_drift_pct": hr_drift_pct,
        "decoupling_pct": decoupling_pct,
        "splits": splits,
    }


def summarise_zones(zones: list[dict]) -> dict | None:
    """Strava /zones returns HR and/or power zone buckets with time per zone."""
    if not zones:
        return None
    out = {}
    for z in zones:
        kind = z.get("type", "zone")
        buckets = z.get("distribution_buckets") or []
        out[kind] = [
            {"min": b.get("min"), "max": b.get("max"), "time_s": b.get("time")}
            for b in buckets
        ]
    return out or None
