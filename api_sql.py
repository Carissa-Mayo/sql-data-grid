import sqlite3
import requests

DB_PATH = "weather_grid.sqlite"
API_URL = "https://archive-api.open-meteo.com/v1/archive"

# List of cities to fetch API data for
LOCATIONS = [
    {"name": "Golden, CO",  "lat": 39.755,   "lon": -105.221},
    {"name": "Denver, CO",  "lat": 39.7392,  "lon": -104.9903},
    {"name": "Boulder, CO", "lat": 40.01499, "lon": -105.2705},
]

# open/create db table
def create_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Locations table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS locations (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        name      TEXT NOT NULL,
        latitude  REAL NOT NULL,
        longitude REAL NOT NULL,
        timezone  TEXT NOT NULL
    );
    """)

    # Hourly weather table
    cur.execute("""
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
    """)

    conn.commit()
    return conn


def insert_location(conn, name, lat, lon, timezone):
    cur = conn.cursor()
    # Check if the location already exists
    cur.execute("""
        SELECT id FROM locations
        WHERE name = ? AND latitude = ? AND longitude = ?
    """, (name, lat, lon))
    row = cur.fetchone()
    if row:
        return row[0]

    # Insert new location
    cur.execute("""
        INSERT INTO locations (name, latitude, longitude, timezone)
        VALUES (?, ?, ?, ?)
    """, (name, lat, lon, timezone))
    conn.commit()
    return cur.lastrowid

# Call the Open-Meteo API and return the parsed JSON, getting data from one year
def fetch_hourly_data(lat, lon):
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,wind_speed_10m,shortwave_radiation",
        "start_date": "2024-01-01",
        "end_date": "2025-01-01",
        "timezone": "UTC"
    }
    resp = requests.get(API_URL, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()

# Load hourly weather data from API JSON into the database
def load_hourly(conn, location_id, api_data):
    cur = conn.cursor()

    hourly = api_data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    winds = hourly.get("wind_speed_10m", [])
    solar = hourly.get("shortwave_radiation", [])

    # Sanity check: use the shortest shared length
    n = min(len(times), len(temps), len(winds), len(solar))

    for i in range(n):
        ts = times[i]
        t = temps[i]
        w = winds[i]
        s = solar[i]

        # Insert, ignore if duplicate (UNIQUE constraint)
        cur.execute("""
            INSERT OR IGNORE INTO weather_hourly (
                location_id, timestamp_utc, temperature_c, wind_speed_ms, solar_rad_wm2
            ) VALUES (?, ?, ?, ?, ?)
        """, (location_id, ts, t, w, s))

    conn.commit()


def main():
    conn = create_db()

    for loc in LOCATIONS:
        print(f"Fetching data for {loc['name']}...")
        api_data = fetch_hourly_data(loc["lat"], loc["lon"])

        # timezone from API metadata
        timezone = api_data.get("timezone", "UTC")

        # Insert or retrieve location row
        location_id = insert_location(
            conn,
            name=loc["name"],
            lat=loc["lat"],
            lon=loc["lon"],
            timezone=timezone,
        )

        # Load hourly weather data
        load_hourly(conn, location_id, api_data)

    conn.close()
    print("Done. Data loaded into", DB_PATH)


if __name__ == "__main__":
    main()
