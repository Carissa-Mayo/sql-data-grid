-- Reference schema for the ETL mini-project.
-- Note: api_sql.py creates tables automatically; this file documents the intended schema.

CREATE TABLE IF NOT EXISTS locations (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  name      TEXT NOT NULL,
  latitude  REAL NOT NULL,
  longitude REAL NOT NULL,
  timezone  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weather_hourly (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  location_id     INTEGER NOT NULL,
  timestamp_utc   TEXT NOT NULL,
  temperature_c   REAL,
  wind_speed_ms   REAL,
  solar_rad_wm2   REAL,
  FOREIGN KEY (location_id) REFERENCES locations(id),
  UNIQUE (location_id, timestamp_utc)
);

CREATE INDEX IF NOT EXISTS idx_weather_timestamp ON weather_hourly(timestamp_utc);

CREATE TABLE IF NOT EXISTS pipeline_runs (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  run_utc         TEXT NOT NULL,
  mode            TEXT NOT NULL,
  start_date      TEXT NOT NULL,
  end_date        TEXT NOT NULL,
  wind_speed_unit TEXT NOT NULL,
  notes           TEXT
);
