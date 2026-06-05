"""Strava API client.

Handles OAuth token refresh (with refresh-token rotation persisted to SQLite),
and the read endpoints we need: activities list, activity detail, streams, zones.

Stable / reusable as-is. Endpoints documented at
https://developers.strava.com/docs/reference/
"""
from __future__ import annotations

import os
import time
import requests

from cache import get_tokens, save_tokens

API = "https://www.strava.com/api/v3"
TOKEN_URL = "https://www.strava.com/oauth/token"


class StravaClient:
    def __init__(self) -> None:
        self.client_id = os.environ["STRAVA_CLIENT_ID"]
        self.client_secret = os.environ["STRAVA_CLIENT_SECRET"]
        # refresh token: prefer the one persisted in the DB (may have rotated),
        # fall back to the seed value from the environment on first run.
        stored = get_tokens()
        self._refresh_token = (stored or {}).get("refresh_token") or os.environ["STRAVA_REFRESH_TOKEN"]
        self._access_token = (stored or {}).get("access_token")
        self._expires_at = (stored or {}).get("expires_at", 0)

    # -- auth ---------------------------------------------------------------
    def _ensure_token(self) -> str:
        if self._access_token and time.time() < self._expires_at - 60:
            return self._access_token
        r = requests.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            },
            timeout=30,
        )
        r.raise_for_status()
        d = r.json()
        self._access_token = d["access_token"]
        self._expires_at = d["expires_at"]
        # Strava can rotate the refresh token — persist whatever we got back.
        self._refresh_token = d.get("refresh_token", self._refresh_token)
        save_tokens(self._access_token, self._refresh_token, self._expires_at)
        return self._access_token

    def _get(self, path: str, **params):
        r = requests.get(
            f"{API}{path}",
            headers={"Authorization": f"Bearer {self._ensure_token()}"},
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    # -- endpoints ----------------------------------------------------------
    def activities(self, after_epoch: int = 0, per_page: int = 50, max_pages: int = 4) -> list[dict]:
        """Paginated list of activities.

        When `after_epoch > 0`: passes `after=` to Strava, which switches the
        response to ASCENDING order (oldest first) starting just after that
        timestamp — the right shape for an incremental sync.

        When `after_epoch <= 0` (cold start): omits `after` so Strava returns
        in DESCENDING order (newest first) — `max_pages * per_page` newest
        activities. Without this, the cold-start sync would pull the
        oldest 200 activities since the start of time and stop.
        """
        out: list[dict] = []
        for page in range(1, max_pages + 1):
            params: dict = {"per_page": per_page, "page": page}
            if after_epoch > 0:
                params["after"] = after_epoch
            batch = self._get("/athlete/activities", **params)
            if not batch:
                break
            out.extend(batch)
            if len(batch) < per_page:
                break
        return out

    def activity_detail(self, activity_id: int) -> dict:
        return self._get(f"/activities/{activity_id}", include_all_efforts=False)

    def activity_streams(self, activity_id: int) -> dict:
        """Per-sample time series, keyed by type (heartrate, velocity_smooth, distance...)."""
        return self._get(
            f"/activities/{activity_id}/streams",
            keys="time,distance,heartrate,velocity_smooth,altitude,cadence",
            key_by_type="true",
        )

    def activity_zones(self, activity_id: int) -> list[dict]:
        return self._get(f"/activities/{activity_id}/zones")
