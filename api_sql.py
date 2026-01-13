import argparse
import datetime as dt
import sqlite3
from typing import Dict

import requests

DEFAULT_DB_PATH = "weather_grid.sqlite"
API_URL = "https://archive-api.open-meteo.com/v1/archive"

DEFAULT_LOCATIONS = [
    {"name": "Golden, CO",  "lat": 39.755,   "lon": -105.221},
    {"name": "Denver, CO",  "lat": 39.7392,  "lon": -104.9903},
    {"name": "Boulder, CO", "lat": 40.01499, "lon": -105.2705},
]


def create_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS locations (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        name      TEXT NOT NULL,
        latitude  REAL NOT NULL,
        longitude REAL NOT NULL,
        timezone  TEXT NOT NULL
    );
    """)

    cur.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS uq_locations_name_lat_lon
    ON locations(name, latitude, longitude);
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS weather_hourly (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        location_id     INTEGER NOT NULL,
        timestamp_utc   TEXT NOT NULL,   -- stored as ISO8601 UTC with trailing 'Z'
        temperature_c   REAL,
        wind_speed_ms   REAL,
        solar_rad_wm2   REAL,
        FOREIGN KEY (location_id) REFERENCES locations(id),
        UNIQUE (location_id, timestamp_utc)
    );
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_weather_timestamp ON weather_hourly(timestamp_utc);")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_utc         TEXT NOT NULL,
        start_date      TEXT NOT NULL,
        end_date        TEXT NOT NULL,
        wind_speed_unit TEXT NOT NULL,
        notes           TEXT
    );
    """)

    conn.commit()


def insert_location(conn: sqlite3.Connection, name: str, lat: float, lon: float, timezone: str) -> int:
    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM locations
        WHERE name = ? AND latitude = ? AND longitude = ?
    """, (name, lat, lon))
    row = cur.fetchone()
    if row:
        return int(row[0])

    cur.execute("""
        INSERT INTO locations (name, latitude, longitude, timezone)
        VALUES (?, ?, ?, ?)
    """, (name, lat, lon, timezone))
    conn.commit()
    return int(cur.lastrowid)


def fetch_hourly_data(lat: float, lon: float, start_date: str, end_date: str, wind_speed_unit: str) -> Dict:
    # Open-Meteo defaults wind_speed_unit to km/h unless specified.
    # We request m/s so wind_speed_ms in the DB is actually m/s.
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,wind_speed_10m,shortwave_radiation",
        "start_date": start_date,
        "end_date": end_date,                # inclusive
        "timezone": "UTC",
        "wind_speed_unit": wind_speed_unit,  # "ms"
        "timeformat": "iso8601",
    }
    resp = requests.get(API_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _ensure_utc_z(ts: str) -> str:
    return ts if ts.endswith("Z") else f"{ts}Z"


def load_hourly(conn: sqlite3.Connection, location_id: int, api_data: Dict) -> int:
    cur = conn.cursor()

    hourly = api_data.get("hourly", {}) or {}
    times = hourly.get("time", []) or []
    temps = hourly.get("temperature_2m", []) or []
    winds = hourly.get("wind_speed_10m", []) or []
    solar = hourly.get("shortwave_radiation", []) or []

    n = min(len(times), len(temps), len(winds), len(solar))
    rows = []
    for i in range(n):
        rows.append((
            location_id,
            _ensure_utc_z(times[i]),
            temps[i],
            winds[i],
            solar[i],
        ))

    cur.executemany("""
        INSERT INTO weather_hourly (location_id, timestamp_utc, temperature_c, wind_speed_ms, solar_rad_wm2)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(location_id, timestamp_utc) DO UPDATE SET
            temperature_c = excluded.temperature_c,
            wind_speed_ms = excluded.wind_speed_ms,
            solar_rad_wm2 = excluded.solar_rad_wm2;
    """, rows)

    conn.commit()
    return n


def record_run(conn: sqlite3.Connection, start_date: str, end_date: str, wind_speed_unit: str, notes: str = "") -> None:
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO pipeline_runs (run_utc, start_date, end_date, wind_speed_unit, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z", start_date, end_date, wind_speed_unit, notes))
    conn.commit()


def validate(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("""
        SELECT l.name, COUNT(*) AS n_rows,
               MIN(w.timestamp_utc) AS min_ts,
               MAX(w.timestamp_utc) AS max_ts,
               AVG(w.wind_speed_ms) AS avg_wind_ms,
               MAX(w.wind_speed_ms) AS max_wind_ms
        FROM weather_hourly w
        JOIN locations l ON l.id = w.location_id
        GROUP BY l.name
        ORDER BY l.name;
    """)
    rows = cur.fetchall()

    print("\nValidation summary:")
    for name, n_rows, min_ts, max_ts, avg_w, max_w in rows:
        print(f"  {name}: n={n_rows}, {min_ts} → {max_ts}, avg_wind={avg_w:.2f} m/s, max_wind={max_w:.2f} m/s")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Load hourly Open-Meteo data into SQLite with basic validation.")
    p.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite DB file.")
    p.add_argument("--start-date", default="2024-01-01", help="Start date (YYYY-MM-DD).")
    # If you want calendar year 2024 only, end_date must be 2024-12-31 (inclusive).
    p.add_argument("--end-date", default="2024-12-31", help="End date inclusive (YYYY-MM-DD).")
    p.add_argument("--wind-unit", default="ms", choices=["ms", "kmh", "mph", "kn"], help="Wind speed unit requested from API.")
    p.add_argument("--rebuild", action="store_true", help="Drop and recreate tables (DESTROYS existing data).")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    conn = sqlite3.connect(args.db)

    if args.rebuild:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS weather_hourly;")
        cur.execute("DROP TABLE IF EXISTS locations;")
        cur.execute("DROP TABLE IF EXISTS pipeline_runs;")
        conn.commit()

    create_db(conn)

    total = 0
    for loc in DEFAULT_LOCATIONS:
        print(f"Fetching data for {loc['name']} ({args.start_date} → {args.end_date}, wind_unit={args.wind_unit})")
        api_data = fetch_hourly_data(loc["lat"], loc["lon"], args.start_date, args.end_date, args.wind_unit)
        timezone = api_data.get("timezone", "UTC")

        location_id = insert_location(conn, loc["name"], loc["lat"], loc["lon"], timezone)
        total += load_hourly(conn, location_id, api_data)

    record_run(conn, args.start_date, args.end_date, args.wind_unit)
    validate(conn)

    conn.close()
    print(f"\nDone. Loaded/updated ~{total} hourly rows into {args.db}")


if __name__ == "__main__":
    main()
