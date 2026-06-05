# Contract: MCP Tool I/O Shapes

**Feature**: `001-finalize-server-transport-auth`
**Date**: 2026-05-31
**Scope**: The compact JSON response shape each tool MUST produce. All shapes
are derived from the existing `src/server.py` scaffold and the helpers in
`src/cache.py` / `src/metrics.py`. This contract codifies them so future
changes are intentional, and so the smoke procedure (quickstart.md) can
assert shape.

Each tool returns a JSON **string** at the MCP layer (the existing scaffold
uses `json.dumps(...)`). Shapes below describe the *parsed* JSON. All
floating-point values are rounded server-side; clients SHOULD NOT
re-round.

---

## `list_recent_activities(limit: int = 20)`

**Input**:
```json
{ "limit": 5 }
```
- `limit` — integer, ≥ 1, ≤ 100. Defaults to 20 if omitted.

**Output** (array; 0 ≤ length ≤ `limit`):
```json
[
  {
    "id": 12345678901,
    "date": "2026-05-30",
    "type": "Run",
    "distance_km": 12.43,
    "duration_min": 58.2,
    "avg_pace": "4:41/km",
    "avg_hr": 154.3
  }
]
```

**Field contracts**:
- `id` — integer, Strava activity id.
- `date` — ISO date `YYYY-MM-DD`, may be empty string `""` for activities
  with no recorded `start_date_local`.
- `type` — string, raw Strava type ("Run", "Ride", "Swim", "Walk", etc.).
- `distance_km` — number, rounded to 2 decimals.
- `duration_min` — number, rounded to 1 decimal.
- `avg_pace` — string `"M:SS/km"` or `null` for activities without speed
  (e.g., manual entries, weight workouts).
- `avg_hr` — number or `null` if no HR recorded.

**Side effects**: triggers `_sync_new()` — fetches activities newer than the
cached `last_synced_epoch` and upserts them.

**Size bound**: ≤ 250 bytes per row × `limit`. For `limit=20`, ≤ 5 KB.

---

## `get_weekly_summary(weeks: int = 8)`

**Input**:
```json
{ "weeks": 8 }
```
- `weeks` — integer, ≥ 1, ≤ 52. Defaults to 8.

**Output** (array; 0 ≤ length ≤ `weeks`, ordered most recent first):
```json
[
  { "week": "2026-W22", "runs": 5, "km": 47.6, "hours": 4.2 }
]
```

**Field contracts**:
- `week` — string `"YYYY-Wnn"` (ISO week, zero-padded).
- `runs` — integer count of activities (any type) that fell into that ISO
  week.
- `km` — number, total distance in km, rounded to 1 decimal by SQL.
- `hours` — number, total moving time in hours, rounded to 1 decimal.

**Side effects**: triggers `_sync_new()`.

**Size bound**: ≤ 80 bytes per row × `weeks`. For `weeks=52`, ≤ 4.5 KB.

---

## `get_activity_detail(activity_id: int)`

**Input**:
```json
{ "activity_id": 12345678901 }
```
- `activity_id` — integer, Strava activity id. MUST exist on Strava (the
  cache is not authoritative; an unknown id triggers a Strava 404).

**Output** (object):
```json
{
  "id": 12345678901,
  "name": "Long run",
  "date": "2026-05-30",
  "distance_km": 21.10,

  "official_splits_metric": [
    { "km": 1, "pace": "4:38/km", "avg_hr": 148.0, "elev": 3.2 }
  ],

  "stream_metrics": {
    "total_distance_km": 21.10,
    "first_half":  { "avg_hr": 152.1, "avg_pace_min_km": 4.65 },
    "second_half": { "avg_hr": 161.4, "avg_pace_min_km": 4.78 },
    "hr_drift_pct": 6.1,
    "decoupling_pct": 8.4,
    "splits": [
      { "km": 1.0, "avg_hr": 148.2, "avg_pace_min_km": 4.62 }
    ]
  },

  "time_in_zone": {
    "heartrate": [
      { "min": 0,   "max": 130, "time_s": 120 },
      { "min": 130, "max": 145, "time_s": 600 }
    ]
  }
}
```

**Field contracts**:
- `official_splits_metric[].pace` — string or `null`; `null` when
  `average_speed` was missing.
- `stream_metrics` — exactly the dict returned by
  `metrics.compute_stream_metrics(...)`. If streams are insufficient, this
  field becomes `{"note": "insufficient stream data"}` rather than missing.
- `stream_metrics.splits[].avg_pace_min_km` — number in minutes/km (decimal),
  not the `"M:SS/km"` string. (This is internal stream binning; the human
  string lives in `official_splits_metric`.)
- `time_in_zone` — dict keyed by Strava zone type (`"heartrate"`, `"pace"`,
  `"power"`) or `null` when `/zones` returned nothing.

**Side effects**: on cache miss, calls Strava activity detail + streams +
zones endpoints, computes metrics, writes a new **Activity Metrics Record**
(E5). On cache hit, returns the cached payload directly.

**Size bound**: typical 1-hour run ≤ 4 KB (per SC-002). A 4-hour marathon
with all splits + zones ≤ 12 KB.

---

## Error envelope (all tools)

When a tool fails because of an external condition (expired Strava token,
network error, unknown activity), the tool MUST return a JSON-encoded string
of the form:

```json
{ "error": "<short_code>", "message": "<one-line human description>" }
```

Recognised `error` codes:
- `strava_auth_expired` — refresh token rejected by Strava. Message MUST
  reference re-seeding `STRAVA_REFRESH_TOKEN` (FR-012).
- `strava_unavailable` — network or 5xx from Strava.
- `activity_not_found` — Strava returned 404 for `activity_id`.
- `internal` — any other unexpected failure; message SHOULD NOT include
  secrets or stack traces.

Tools MUST NOT raise unhandled exceptions across the MCP boundary — those
would translate to opaque MCP errors that the chat surface cannot
contextualise.
