"""Compute compact metrics from Strava streams.

Pure Python (no numpy) for portability. The whole point: turn thousands of
per-second samples into a handful of numbers Claude can reason over.

Key outputs:
  - first/second half avg HR and avg pace (your "HR on half the distance" ask)
  - Pa:HR decoupling % (aerobic durability — drift of pace-to-HR across the run)
  - HR drift % (simple second-half vs first-half HR change)
  - binned splits (per ~1 km) with pace + HR
  - auto-detected intervals (work/recovery reps from the velocity stream, so an
    interval session shows each rep's pace + HR instead of a smeared average)
  - time-in-zone (from Strava's /zones endpoint when available)
"""
from __future__ import annotations

import re

# Bump when the shape of compute_stream_metrics() changes so the server can
# detect stale cached rows and recompute them (see server.get_activity_detail).
METRICS_VERSION = 2


# Matches "6x400m", "6 x 400", "5×1000m", "10x1min", "8x30s", "4x2'", "3x1:30".
_HINT_RE = re.compile(
    r"(\d{1,2})\s*[x×]\s*(\d+(?::\d+)?(?:\.\d+)?)\s*"
    r"(km|k|mile|min|mi|sec|s|m|'|\"|′|″)?",
    re.IGNORECASE,
)


def _parse_component(tok: str) -> tuple[str, float] | None:
    """Parse one distance/duration token -> ('dist', metres) | ('dur', seconds).

    Bare numbers: >= 100 read as metres, otherwise as minutes. "mm:ss" reads as
    a duration."""
    m = re.fullmatch(
        r"(\d+(?::\d+)?(?:\.\d+)?)\s*(km|k|mile|min|mi|sec|s|m|'|\"|′|″)?",
        tok.strip().lower(),
    )
    if not m:
        return None
    raw, unit = m.group(1), (m.group(2) or "")
    if ":" in raw:
        mm, ss = raw.split(":", 1)
        return ("dur", int(mm) * 60 + int(ss))
    val = float(raw)
    if unit in ("km", "k"):
        return ("dist", val * 1000.0)
    if unit in ("mi", "mile"):
        return ("dist", val * 1609.34)
    if unit == "m":
        return ("dist", val)
    if unit in ("min", "'", "′"):
        return ("dur", val * 60.0)
    if unit in ("s", "sec", '"', "″"):
        return ("dur", val)
    return ("dist", val) if val >= 100 else ("dur", val * 60.0)


def _parse_compound(t: str) -> dict | None:
    """Grouped notation like "4:30x(300+200)x14": an optional target pace, a
    parenthesised set of sub-reps, and a repeat count — in either order. `t` has
    already had × and * normalised to x."""
    g = re.search(r"\(([^)]+)\)", t)
    if not g:
        return None
    parts = [p for p in (_parse_component(x) for x in re.split(r"[+,/]", g.group(1))) if p]
    if not parts:
        return None
    before, after = t[: g.start()], t[g.end():]

    # repeat count: a standalone integer joined to the group by 'x' on either
    # side. The before-side lookbehind excludes digits/':'/'.' so the "30" in a
    # "4:30x(..." pace is not mistaken for a count.
    cnt = None
    mc = re.search(r"(?:^|[^\d:.])(\d{1,2})\s*x\s*$", before)
    if mc:
        cnt = int(mc.group(1))
    elif (mc := re.search(r"^\s*x\s*(\d{1,2})", after)):
        cnt = int(mc.group(1))

    # target pace: an mm:ss anywhere outside the group (sub-rep durations live
    # inside the parens and are parsed above).
    pace = None
    if (mp := re.search(r"(\d+):(\d{2})(?!\d)", before + " " + after)):
        pace = int(mp.group(1)) + int(mp.group(2)) / 60.0

    if cnt is None and pace is None and len(parts) < 2:
        return None  # a lone "(value)" isn't a workout structure

    reps = cnt or 1
    dists = [round(v, 1) for k, v in parts if k == "dist"]
    durs = [round(v, 1) for k, v in parts if k == "dur"]
    out: dict = {"reps": reps}
    if len(parts) == 1:
        out["rep_distance_m" if dists else "rep_duration_s"] = (dists or durs)[0]
        out["work_reps"] = reps
    else:
        if dists:
            out["rep_distances_m"] = dists
        if durs:
            out["rep_durations_s"] = durs
        out["sets"] = reps
        out["work_reps"] = reps * len(parts)  # total fast bouts across all sets
    if pace:
        out["target_pace_min_km"] = round(pace, 3)
    out["raw"] = t.strip()
    return out


def _parse_simple(t: str) -> dict | None:
    """Flat notation: "6x400m", "10x1min", "8x30s", "3x1:30". `t` is normalised."""
    m = _HINT_RE.search(t)
    if not m:
        return None
    reps = int(m.group(1))
    if reps < 2 or reps > 60:
        return None
    comp = _parse_component(m.group(2) + (m.group(3) or ""))
    if not comp:
        return None
    out: dict = {"reps": reps, "work_reps": reps}
    out["rep_distance_m" if comp[0] == "dist" else "rep_duration_s"] = round(comp[1], 1)
    return out


def parse_workout_hint(text: str | None) -> dict | None:
    """Extract a planned interval structure from free text (activity name or
    description). Handles grouped notations ("4:30x(300+200)x14", "*"/"×"/"x"
    separators) and flat ones ("6x400m", "3x1:30"). Returns a dict with at least
    "reps" (and "work_reps", plus optional rep distances/durations and target
    pace) or None. Used only to *corroborate* stream-detected intervals — the
    athlete's note may be shorthand or aspirational, never the sole source."""
    if not text:
        return None
    t = text.replace("×", "x").replace("*", "x")
    return _parse_compound(t) or _parse_simple(t)


def _pace_min_per_km(speed_ms: float) -> float | None:
    if not speed_ms or speed_ms <= 0:
        return None
    return round((1000.0 / speed_ms) / 60.0, 3)  # minutes per km


def _avg(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def _seconds_per_km(speed_ms: float) -> float | None:
    if not speed_ms or speed_ms <= 0:
        return None
    return 1000.0 / speed_ms


def _smooth(xs: list, win: int) -> list:
    """Centered moving average; tolerates None gaps."""
    n = len(xs)
    if win <= 1 or n == 0:
        return list(xs)
    half = win // 2
    out = []
    for i in range(n):
        a, b = max(0, i - half), min(n, i + half + 1)
        seg = [x for x in xs[a:b] if x is not None]
        out.append(sum(seg) / len(seg) if seg else None)
    return out


def _otsu_threshold(values: list[float], bins: int = 64) -> float:
    """1-D Otsu threshold — splits a (hopefully bimodal) distribution into two
    classes by minimising intra-class variance. Parameter-free: lets the data
    decide where "work" pace ends and "recovery" pace begins."""
    vmin, vmax = min(values), max(values)
    if vmax <= vmin:
        return vmax
    width = (vmax - vmin) / bins
    hist = [0] * bins
    for v in values:
        idx = int((v - vmin) / width)
        if idx >= bins:
            idx = bins - 1
        hist[idx] += 1
    centers = [vmin + (i + 0.5) * width for i in range(bins)]
    total = len(values)
    sum_total = sum(h * c for h, c in zip(hist, centers))
    sum_b = 0.0
    w_b = 0
    best_between = 0.0
    threshold = (vmin + vmax) / 2.0
    for i in range(bins):
        w_b += hist[i]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += hist[i] * centers[i]
        m_b = sum_b / w_b
        m_f = (sum_total - sum_b) / w_f
        between = w_b * w_f * (m_b - m_f) ** 2
        if between > best_between:
            best_between = between
            threshold = centers[i]
    return threshold


def _merge_short_runs(flags: list[bool], durs: list[float],
                      min_work_s: float, min_rec_s: float) -> list[bool]:
    """Flip segments shorter than their class minimum into the surrounding
    class, so a momentary GPS wobble mid-rep doesn't shatter one rep into three.
    Iterates to a fixed point."""
    flags = list(flags)
    n = len(flags)
    if n == 0:
        return flags
    changed = True
    while changed:
        changed = False
        # collect contiguous runs as (start, end_exclusive, value)
        runs = []
        s = 0
        for i in range(1, n + 1):
            if i == n or flags[i] != flags[s]:
                runs.append((s, i, flags[s]))
                s = i
        for ridx, (a, b, val) in enumerate(runs):
            dur = sum(durs[a:b])
            floor = min_work_s if val else min_rec_s
            if dur < floor and len(runs) > 1:
                # flip this whole run to the opposite class
                for j in range(a, b):
                    flags[j] = not val
                changed = True
                break
    return flags


def detect_intervals(
    streams: dict,
    smooth_win_s: int = 10,
    min_work_s: float = 20.0,
    min_rec_s: float = 10.0,
    min_speed_sep: float = 0.12,
    hint: dict | None = None,
) -> dict:
    """Auto-detect work/recovery intervals from the velocity stream.

    No reliance on lap markers — segments the smoothed speed via an Otsu
    threshold, merges noise, then reports each rep's distance, duration, pace,
    avg/max HR. Returns {"detected": False, ...} for steady runs with no clear
    interval structure (work and recovery pace too close together).

    `hint` (from parse_workout_hint on the activity name/description) is used as
    corroboration: when the athlete explicitly wrote a structure like "6x400m",
    the pace-separation guard is relaxed and the planned reps are echoed back
    alongside the detected count for an at-a-glance match check.
    """
    # An explicit textual workout note is strong evidence this *is* an interval
    # session, so trust the stream more and the steady-pace guard less.
    sep_floor = min(min_speed_sep, 0.06) if (hint and hint.get("reps")) else min_speed_sep
    vel = streams.get("velocity_smooth", {}).get("data") or []
    dist = streams.get("distance", {}).get("data") or []
    hr = streams.get("heartrate", {}).get("data") or []
    tim = streams.get("time", {}).get("data") or []
    n = min(len(vel), len(dist))
    if n < 10 or not vel or not dist:
        return {"detected": False, "note": "insufficient stream data for intervals"}

    # per-sample durations (seconds) from the time stream; fall back to 1 Hz
    def dur_at(i: int) -> float:
        if tim and i > 0 and i < len(tim):
            d = tim[i] - tim[i - 1]
            return d if 0 < d < 60 else 1.0
        return 1.0

    durs = [dur_at(i) for i in range(n)]
    sm = _smooth(vel[:n], smooth_win_s)
    speeds = [s for s in sm if s and s > 0]
    if len(speeds) < 10:
        return {"detected": False, "note": "no movement data for intervals"}

    thr = _otsu_threshold(speeds)
    flags = [(s is not None and s >= thr) for s in sm]
    flags = _merge_short_runs(flags, durs, min_work_s, min_rec_s)

    # build ordered segments
    segments = []
    s = 0
    for i in range(1, n + 1):
        if i == n or flags[i] != flags[s]:
            segments.append((s, i, flags[s]))
            s = i

    def seg_stats(a: int, b: int, kind: str, rep: int | None) -> dict:
        duration = sum(durs[a:b])
        distance = max(0.0, dist[min(b, n) - 1] - dist[a])
        seg_hr = hr[a:b] if hr else []
        avg_hr = _avg(seg_hr)
        max_hr = max((x for x in seg_hr if x is not None), default=None)
        pace_s = (duration / (distance / 1000.0)) if distance > 0 else None
        out = {
            "kind": kind,
            "duration_s": round(duration, 1),
            "distance_m": round(distance, 1),
            "avg_pace_min_km": round(pace_s / 60.0, 3) if pace_s else None,
            "avg_hr": avg_hr,
            "max_hr": max_hr,
        }
        if rep is not None:
            out["rep"] = rep
        return out

    work = [(a, b) for a, b, v in segments if v]
    rec = [(a, b) for a, b, v in segments if not v]
    if len(work) < 2:
        return {"detected": False, "note": "no repeating interval structure found"}

    def avg_speed(pairs: list[tuple[int, int]]) -> float | None:
        td = sum(dist[min(b, n) - 1] - dist[a] for a, b in pairs)
        tt = sum(sum(durs[a:b]) for a, b in pairs)
        return td / tt if tt > 0 else None

    ws, rs = avg_speed(work), avg_speed(rec) if rec else None
    # guard: only call it intervals if work pace is clearly faster than recovery
    if ws and rs and (ws - rs) / ws < sep_floor:
        return {"detected": False, "note": "pace too steady to be intervals"}

    rep_no = 0
    ordered = []
    for a, b, v in segments:
        if v:
            rep_no += 1
            ordered.append(seg_stats(a, b, "work", rep_no))
        else:
            ordered.append(seg_stats(a, b, "recovery", None))

    work_durs = [s["duration_s"] for s in ordered if s["kind"] == "work"]
    work_hrs = [s["avg_hr"] for s in ordered if s["kind"] == "work" and s["avg_hr"]]
    summary = {
        "reps": rep_no,
        "avg_work_pace_min_km": _pace_min_per_km(ws) if ws else None,
        "avg_recovery_pace_min_km": _pace_min_per_km(rs) if rs else None,
        "avg_work_hr": round(sum(work_hrs) / len(work_hrs), 1) if work_hrs else None,
        "avg_work_duration_s": round(sum(work_durs) / len(work_durs), 1) if work_durs else None,
    }
    out = {"detected": True, "summary": summary, "segments": ordered}
    if hint and hint.get("reps"):
        out["planned"] = hint
        expected = hint.get("work_reps") or hint["reps"]
        if expected != rep_no:
            summary["note"] = (
                f"detected {rep_no} work reps; description suggests {expected}"
            )
    return out


def compute_stream_metrics(streams: dict, split_m: float = 1000.0,
                           hint: dict | None = None) -> dict:
    """`streams` is Strava's key_by_type response: {type: {"data": [...]}, ...}.

    `hint` is an optional planned-workout dict (see parse_workout_hint) parsed
    from the activity name/description; it corroborates interval detection."""
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
        "intervals": detect_intervals(streams, hint=hint),
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
