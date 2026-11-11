"""SQLite schema and queries (stdlib sqlite3, no ORM)."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from vetday.config import DB_PATH
from vetday.models import Offer

SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    id TEXT PRIMARY KEY,
    brand_key TEXT NOT NULL,
    category TEXT NOT NULL,
    needs_verification INTEGER NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS refreshes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    mode TEXT NOT NULL,
    model TEXT,
    total_offers INTEGER
);
CREATE TABLE IF NOT EXISTS source_runs (
    refresh_id INTEGER NOT NULL REFERENCES refreshes(id),
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    raw_count INTEGER NOT NULL,
    message TEXT
);
CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS geo_cache (
    brand_key TEXT NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    radius_mi INTEGER NOT NULL,
    provider TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (brand_key, lat, lng, radius_mi, provider)
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def replace_offers(conn: sqlite3.Connection, offers: list[Offer]) -> None:
    with conn:
        conn.execute("DELETE FROM offers")
        conn.executemany(
            "INSERT INTO offers (id, brand_key, category, needs_verification, data) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (o.id, o.brand_key, o.category, int(o.needs_verification), o.model_dump_json())
                for o in offers
            ],
        )


def load_offers(conn: sqlite3.Connection) -> list[Offer]:
    rows = conn.execute("SELECT data FROM offers ORDER BY brand_key").fetchall()
    return [Offer.model_validate_json(r["data"]) for r in rows]


def start_refresh(conn: sqlite3.Connection, mode: str, model: str | None) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO refreshes (started_at, mode, model) VALUES (?, ?, ?)",
            (now_iso(), mode, model),
        )
    return int(cur.lastrowid)


def record_source_run(
    conn: sqlite3.Connection, refresh_id: int, source: str, status: str, count: int, msg: str = ""
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO source_runs VALUES (?, ?, ?, ?, ?)",
            (refresh_id, source, status, count, msg),
        )


def finish_refresh(conn: sqlite3.Connection, refresh_id: int, total: int) -> None:
    with conn:
        conn.execute(
            "UPDATE refreshes SET finished_at = ?, total_offers = ? WHERE id = ?",
            (now_iso(), total, refresh_id),
        )


def last_refresh(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT * FROM refreshes WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    runs = conn.execute(
        "SELECT source, status, raw_count, message FROM source_runs WHERE refresh_id = ?",
        (row["id"],),
    ).fetchall()
    return {**dict(row), "sources": [dict(r) for r in runs]}


def cache_get(conn: sqlite3.Connection, key: str) -> dict | None:
    row = conn.execute("SELECT data FROM llm_cache WHERE key = ?", (key,)).fetchone()
    return json.loads(row["data"]) if row else None


def cache_put(conn: sqlite3.Connection, key: str, model: str, data: dict) -> None:
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO llm_cache VALUES (?, ?, ?, ?)",
            (key, model, json.dumps(data), now_iso()),
        )
