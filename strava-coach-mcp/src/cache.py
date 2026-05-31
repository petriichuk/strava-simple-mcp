"""SQLite cache for activity summaries, computed metrics, tokens and sync state.

This is a *cache*, not the user's plan memory (that lives in the Claude Project).
One file, no server process. Reusable as-is.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("COACH_DB_PATH", "coach.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    id              INTEGER PRIMARY KEY,
    start_date      TEXT,      -- ISO local
    type            TEXT,
    name            TEXT,
    distance_m      REAL,
    moving_time_s   INTEGER,
    elev_gain_m     REAL,
    avg_speed_ms    REAL,
    avg_hr          REAL,
    max_hr          REAL,
    iso_year        INTEGER,
    iso_week        INTEGER
);
CREATE TABLE IF NOT EXISTS activity_metrics (
    id              INTEGER PRIMARY KEY,   -- FK -> activities.id
    metrics_json    TEXT                   -- computed stream metrics (halves, decoupling, splits, zones)
);
CREATE TABLE IF NOT EXISTS sync_state (
    k TEXT PRIMARY KEY,
    v TEXT
);
CREATE TABLE IF NOT EXISTS tokens (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    access_token    TEXT,
    refresh_token   TEXT,
    expires_at      INTEGER
);
"""


@contextmanager
def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)


# -- tokens -----------------------------------------------------------------
def get_tokens() -> dict | None:
    init_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM tokens WHERE id = 1").fetchone()
        return dict(row) if row else None


def save_tokens(access_token: str, refresh_token: str, expires_at: int) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO tokens (id, access_token, refresh_token, expires_at) "
            "VALUES (1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "access_token=excluded.access_token, refresh_token=excluded.refresh_token, "
            "expires_at=excluded.expires_at",
            (access_token, refresh_token, expires_at),
        )


# -- sync state -------------------------------------------------------------
def get_last_synced() -> int:
    with _conn() as c:
        row = c.execute("SELECT v FROM sync_state WHERE k = 'last_synced_epoch'").fetchone()
        return int(row["v"]) if row else 0


def set_last_synced(epoch: int) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO sync_state (k, v) VALUES ('last_synced_epoch', ?) "
            "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            (str(epoch),),
        )


# -- activities -------------------------------------------------------------
def upsert_activities(rows: list[dict]) -> None:
    import datetime as dt

    with _conn() as c:
        for a in rows:
            iso_year = iso_week = None
            if a.get("start_date_local"):
                d = dt.datetime.fromisoformat(a["start_date_local"].replace("Z", "+00:00"))
                iso_year, iso_week, _ = d.isocalendar()
            c.execute(
                "INSERT INTO activities (id, start_date, type, name, distance_m, "
                "moving_time_s, elev_gain_m, avg_speed_ms, avg_hr, max_hr, iso_year, iso_week) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "start_date=excluded.start_date, type=excluded.type, name=excluded.name, "
                "distance_m=excluded.distance_m, moving_time_s=excluded.moving_time_s, "
                "elev_gain_m=excluded.elev_gain_m, avg_speed_ms=excluded.avg_speed_ms, "
                "avg_hr=excluded.avg_hr, max_hr=excluded.max_hr, "
                "iso_year=excluded.iso_year, iso_week=excluded.iso_week",
                (
                    a.get("id"), a.get("start_date_local"), a.get("type"), a.get("name"),
                    a.get("distance"), a.get("moving_time"), a.get("total_elevation_gain"),
                    a.get("average_speed"), a.get("average_heartrate"), a.get("max_heartrate"),
                    iso_year, iso_week,
                ),
            )


def recent_activities(limit: int = 20) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM activities ORDER BY start_date DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def weekly_rollup(weeks: int = 8) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT iso_year, iso_week, COUNT(*) runs, "
            "ROUND(SUM(distance_m)/1000.0, 1) km, SUM(moving_time_s) time_s "
            "FROM activities WHERE iso_year IS NOT NULL "
            "GROUP BY iso_year, iso_week ORDER BY iso_year DESC, iso_week DESC LIMIT ?",
            (weeks,),
        ).fetchall()
        return [dict(r) for r in rows]


# -- computed metrics cache -------------------------------------------------
def get_metrics(activity_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT metrics_json FROM activity_metrics WHERE id = ?", (activity_id,)
        ).fetchone()
        return json.loads(row["metrics_json"]) if row else None


def save_metrics(activity_id: int, metrics: dict) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO activity_metrics (id, metrics_json) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET metrics_json = excluded.metrics_json",
            (activity_id, json.dumps(metrics)),
        )
