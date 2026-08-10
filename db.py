"""SQLite persistence for the city tracker.

Everything lives in a single file under ./data, so backing up the tracker is
just copying that file. Connections are opened per call, which is the safe
pattern under Streamlit's rerun-per-interaction model.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from continents import continent_for


def _resolve_data_dir() -> Path:
    """Locate the folder holding the database.

    A checkout keeps its `./data` next to the code. The packaged Windows build
    installs the code somewhere a reinstall will overwrite, so its launcher
    points `CITY_TRACKER_DATA` at the user's own AppData instead — travel
    history then outlives both upgrades and uninstalls.
    """
    override = os.environ.get("CITY_TRACKER_DATA")
    if override:
        return Path(override)

    alongside_code = Path(__file__).parent / "data"
    if alongside_code.exists():
        return alongside_code

    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "CityTracker" / "data" if base else alongside_code


DATA_DIR = _resolve_data_dir()
DB_PATH = DATA_DIR / "city_tracker.db"

STATUSES = ("visited", "wishlist")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS places (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    display_name  TEXT    NOT NULL DEFAULT '',
    category      TEXT    NOT NULL DEFAULT '',
    feature_type  TEXT    NOT NULL DEFAULT '',
    city          TEXT    NOT NULL DEFAULT '',
    state         TEXT    NOT NULL DEFAULT '',
    country       TEXT    NOT NULL DEFAULT '',
    country_code  TEXT    NOT NULL DEFAULT '',
    continent     TEXT    NOT NULL DEFAULT 'Unknown',
    lat           REAL    NOT NULL,
    lon           REAL    NOT NULL,
    osm_type      TEXT,
    osm_id        INTEGER,
    status        TEXT    NOT NULL DEFAULT 'visited',
    visited_on    TEXT,
    rating        INTEGER,
    notes         TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);

-- One row per real-world OSM feature; manual entries (no osm_id) are exempt.
CREATE UNIQUE INDEX IF NOT EXISTS idx_places_osm
    ON places (osm_type, osm_id)
    WHERE osm_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_places_status ON places (status);
CREATE INDEX IF NOT EXISTS idx_places_country ON places (country_code);
"""

EDITABLE_FIELDS = ("name", "status", "visited_on", "rating", "notes")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(_SCHEMA)


def add_place(
    *,
    name: str,
    lat: float,
    lon: float,
    display_name: str = "",
    category: str = "",
    feature_type: str = "",
    city: str = "",
    state: str = "",
    country: str = "",
    country_code: str = "",
    osm_type: str | None = None,
    osm_id: int | None = None,
    status: str = "visited",
    visited_on: str | None = None,
    rating: int | None = None,
    notes: str = "",
) -> tuple[int | None, bool]:
    """Insert a place.

    Returns (row id, created). `created` is False when the OSM feature is
    already tracked, in which case the existing row id comes back untouched.
    """
    stamp = _now()
    with connect() as conn:
        if osm_id is not None:
            existing = conn.execute(
                "SELECT id FROM places WHERE osm_type = ? AND osm_id = ?",
                (osm_type, osm_id),
            ).fetchone()
            if existing:
                return existing["id"], False

        cursor = conn.execute(
            """
            INSERT INTO places (
                name, display_name, category, feature_type, city, state,
                country, country_code, continent, lat, lon, osm_type, osm_id,
                status, visited_on, rating, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                display_name,
                category,
                feature_type,
                city,
                state,
                country,
                country_code.upper(),
                continent_for(country_code),
                float(lat),
                float(lon),
                osm_type,
                osm_id,
                status if status in STATUSES else "visited",
                visited_on,
                rating,
                notes,
                stamp,
                stamp,
            ),
        )
        return cursor.lastrowid, True


def update_place(place_id: int, **fields: Any) -> None:
    """Update the user-editable columns of one row."""
    updates = {key: value for key, value in fields.items() if key in EDITABLE_FIELDS}
    if not updates:
        return

    assignments = ", ".join(f"{key} = ?" for key in updates)
    with connect() as conn:
        conn.execute(
            f"UPDATE places SET {assignments}, updated_at = ? WHERE id = ?",
            (*updates.values(), _now(), place_id),
        )


def delete_places(place_ids: list[int]) -> int:
    if not place_ids:
        return 0
    placeholders = ", ".join("?" for _ in place_ids)
    with connect() as conn:
        cursor = conn.execute(
            f"DELETE FROM places WHERE id IN ({placeholders})", place_ids
        )
        return cursor.rowcount


def load_places() -> pd.DataFrame:
    """Return every tracked place, newest first, as a DataFrame."""
    with connect() as conn:
        frame = pd.read_sql_query(
            "SELECT * FROM places ORDER BY COALESCE(visited_on, created_at) DESC, id DESC",
            conn,
        )

    if frame.empty:
        # Give downstream code a stable set of columns to work with.
        return pd.DataFrame(
            columns=[
                "id", "name", "display_name", "category", "feature_type", "city",
                "state", "country", "country_code", "continent", "lat", "lon",
                "osm_type", "osm_id", "status", "visited_on", "rating", "notes",
                "created_at", "updated_at",
            ]
        )

    frame["visited_on"] = pd.to_datetime(frame["visited_on"], errors="coerce")
    return frame
