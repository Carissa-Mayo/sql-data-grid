import argparse
import datetime as dt
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import requests

API_URL = "https://archive-api.open-meteo.com/v1/archive"

DEFAULT_LOCATIONS = [
    {"name": "Golden, CO",  "lat": 39.755,   "lon": -105.221},
    {"name": "Denver, CO",  "lat": 39.7392,  "lon": -104.9903},
    {"name": "Boulder, CO", "lat": 40.01499, "lon": -105.2705},
]

DEFAULT_DB_PATH = "artifacts/weather_grid.sqlite"
DEFAULT_ARTIFACTS_DIR = "artifacts"
DEFAULT_WIND_UNIT = "ms"  # IMPORTANT: makes wind_speed_ms truthful.


@dataclass
class ValidationResult:
    ok: bool
    messages: List[str]


def utc_today() -> dt.date:
    return dt.datetime.utcnow().date()


def iso_utc_now() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def ensure_utc_z(ts: str) -> str:
    # Open-Meteo returns ISO8601; ensure we store explicit UTC indicator.
    return ts if ts.endswith("Z") else f"{ts}Z"


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
        timestamp_utc   TEXT NOT NULL,   -- ISO8601 UTC, e.g. 2024-01-01T00:00Z
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
        mode            TEXT NOT NULL,
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
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,wind_speed_10m,shortwave_radiation",
        "start_date": start_date,
        "end_date": end_date,                # inclusive in Open-Meteo
        "timezone": "UTC",
        "wind_speed_unit": wind_speed_unit,  # "ms" recommended
        "timeformat": "iso8601",
    }
    resp = requests.get(API_URL, params=params, timeout=45)
    resp.raise_for_status()
    return resp.json()


def upsert_hourly(conn: sqlite3.Connection, location_id: int, api_data: Dict) -> int:
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
            ensure_utc_z(times[i]),
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


def record_run(conn: sqlite3.Connection, mode: str, start_date: str, end_date: str, wind_speed_unit: str, notes: str = "") -> None:
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO pipeline_runs (run_utc, mode, start_date, end_date, wind_speed_unit, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (iso_utc_now(), mode, start_date, end_date, wind_speed_unit, notes))
    conn.commit()


def summarize(conn: sqlite3.Connection) -> Dict:
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM weather_hourly;")
    total_rows = int(cur.fetchone()[0])

    cur.execute("SELECT MIN(timestamp_utc), MAX(timestamp_utc) FROM weather_hourly;")
    min_ts, max_ts = cur.fetchone()

    cur.execute("""
        SELECT l.name,
               COUNT(*) AS n,
               MIN(w.timestamp_utc) AS min_ts,
               MAX(w.timestamp_utc) AS max_ts,
               AVG(w.wind_speed_ms) AS avg_wind_ms,
               MAX(w.wind_speed_ms) AS max_wind_ms,
               AVG(w.solar_rad_wm2) AS avg_solar_wm2,
               MAX(w.solar_rad_wm2) AS max_solar_wm2
        FROM weather_hourly w
        JOIN locations l ON l.id = w.location_id
        GROUP BY l.name
        ORDER BY l.name;
    """)
    per_location = []
    for row in cur.fetchall():
        name, n, lmin, lmax, avg_w, max_w, avg_s, max_s = row
        per_location.append({
            "location": name,
            "n_rows": int(n),
            "min_timestamp_utc": lmin,
            "max_timestamp_utc": lmax,
            "avg_wind_speed_ms": float(avg_w) if avg_w is not None else None,
            "max_wind_speed_ms": float(max_w) if max_w is not None else None,
            "avg_solar_rad_wm2": float(avg_s) if avg_s is not None else None,
            "max_solar_rad_wm2": float(max_s) if max_s is not None else None,
        })

    return {
        "total_rows": total_rows,
        "min_timestamp_utc": min_ts,
        "max_timestamp_utc": max_ts,
        "per_location": per_location,
    }


def validate(conn: sqlite3.Connection, expected_start: str, expected_end: str) -> ValidationResult:
    """
    Pipeline-quality gates. If these fail, the pipeline should fail.
    This is intentionally simple and explainable.
    """
    cur = conn.cursor()
    msgs: List[str] = []

    # Basic non-negativity checks
    cur.execute("SELECT COUNT(*) FROM weather_hourly WHERE wind_speed_ms < 0;")
    bad_wind = int(cur.fetchone()[0])
    if bad_wind > 0:
        msgs.append(f"Found {bad_wind} rows with wind_speed_ms < 0.")

    cur.execute("SELECT COUNT(*) FROM weather_hourly WHERE solar_rad_wm2 < 0;")
    bad_solar = int(cur.fetchone()[0])
    if bad_solar > 0:
        msgs.append(f"Found {bad_solar} rows with solar_rad_wm2 < 0.")

    # Missingness check (should be near-zero for these API fields)
    cur.execute("SELECT COUNT(*) FROM weather_hourly WHERE wind_speed_ms IS NULL OR solar_rad_wm2 IS NULL;")
    null_critical = int(cur.fetchone()[0])
    if null_critical > 0:
        msgs.append(f"Found {null_critical} rows with NULL wind_speed_ms or solar_rad_wm2.")

    # Freshness check: ensure we loaded at least up to expected_end day (inclusive)
    # Compare dates only (YYYY-MM-DD).
    cur.execute("SELECT MAX(timestamp_utc) FROM weather_hourly;")
    max_ts = cur.fetchone()[0]
    if not max_ts:
        msgs.append("No data in weather_hourly.")
    else:
        max_date = max_ts[:10]
        if max_date < expected_end:
            msgs.append(f"Freshness check failed: max_date={max_date} < expected_end={expected_end}.")

    ok = (len(msgs) == 0)
    if ok:
        msgs.append("All validation checks passed.")
    return ValidationResult(ok=ok, messages=msgs)


def write_artifacts(artifacts_dir: Path, run_meta: Dict, summary: Dict, validation: ValidationResult) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    metrics = {
        "run": run_meta,
        "summary": summary,
        "validation": {
            "ok": validation.ok,
            "messages": validation.messages,
        },
    }

    (artifacts_dir / "run_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    lines = []
    lines.append(f"run_utc: {run_meta['run_utc']}")
    lines.append(f"mode: {run_meta['mode']}")
    lines.append(f"date_window: {run_meta['start_date']} -> {run_meta['end_date']} (inclusive)")
    lines.append(f"wind_speed_unit_requested: {run_meta['wind_speed_unit']}")
    lines.append("")
    lines.append(f"total_rows: {summary['total_rows']}")
    lines.append(f"min_timestamp_utc: {summary['min_timestamp_utc']}")
    lines.append(f"max_timestamp_utc: {summary['max_timestamp_utc']}")
    lines.append("")
    lines.append("per_location:")
    for loc in summary["per_location"]:
        lines.append(
            f"  - {loc['location']}: n={loc['n_rows']}, "
            f"{loc['min_timestamp_utc']} -> {loc['max_timestamp_utc']}, "
            f"avg_wind={loc['avg_wind_speed_ms']:.2f} m/s, "
            f"avg_solar={loc['avg_solar_rad_wm2']:.2f} W/m^2"
        )
    lines.append("")
    lines.append(f"validation_ok: {validation.ok}")
    for m in validation.messages:
        lines.append(f"- {m}")

    (artifacts_dir / "run_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Microsoft-aligned ETL mini-project: Open-Meteo hourly -> SQLite + validation + artifacts"
    )

    p.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite DB file.")
    p.add_argument("--artifacts-dir", default=DEFAULT_ARTIFACTS_DIR, help="Directory to write run artifacts.")
    p.add_argument("--wind-unit", default=DEFAULT_WIND_UNIT, choices=["ms", "kmh", "mph", "kn"],
                   help="Wind speed unit requested from API (use 'ms' to match wind_speed_ms).")

    p.add_argument("--mode", default="daily", choices=["daily", "backfill"],
                   help="daily = yesterday UTC only; backfill = explicit date range.")
    p.add_argument("--start-date", default="2024-01-01", help="Start date for backfill (YYYY-MM-DD).")
    p.add_argument("--end-date", default="2024-12-31", help="End date for backfill, inclusive (YYYY-MM-DD).")
    p.add_argument("--rebuild", action="store_true", help="Drop and recreate tables (DESTROYS existing data).")

    return p.parse_args()


def compute_date_window(args: argparse.Namespace) -> Tuple[str, str]:
    if args.mode == "daily":
        d = utc_today() - dt.timedelta(days=1)
        s = d.isoformat()
        e = d.isoformat()
        return s, e
    return args.start_date, args.end_date


def main() -> None:
    args = parse_args()

    start_date, end_date = compute_date_window(args)
    artifacts_dir = Path(args.artifacts_dir)

    # Ensure parent dirs exist for DB path
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))

    if args.rebuild:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS weather_hourly;")
        cur.execute("DROP TABLE IF EXISTS locations;")
        cur.execute("DROP TABLE IF EXISTS pipeline_runs;")
        conn.commit()

    create_db(conn)

    total_loaded = 0
    for loc in DEFAULT_LOCATIONS:
        api_data = fetch_hourly_data(loc["lat"], loc["lon"], start_date, end_date, args.wind_unit)
        timezone = api_data.get("timezone", "UTC")
        location_id = insert_location(conn, loc["name"], loc["lat"], loc["lon"], timezone)
        total_loaded += upsert_hourly(conn, location_id, api_data)

    record_run(conn, args.mode, start_date, end_date, args.wind_unit)

    run_meta = {
        "run_utc": iso_utc_now(),
        "mode": args.mode,
        "start_date": start_date,
        "end_date": end_date,
        "wind_speed_unit": args.wind_unit,
        "rows_processed_this_run_estimate": total_loaded,
        "db_path": str(db_path),
    }

    summary = summarize(conn)
    validation = validate(conn, expected_start=start_date, expected_end=end_date)
    write_artifacts(artifacts_dir, run_meta, summary, validation)

    conn.close()

    # Print a concise summary to pipeline logs
    print((artifacts_dir / "run_summary.txt").read_text(encoding="utf-8"))

    # Fail the pipeline if validation fails
    if not validation.ok:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
