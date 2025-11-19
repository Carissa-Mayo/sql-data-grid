-- 1. Locations and number of observations
SELECT l.name, COUNT(w.timestamp_utc) as n_obs
FROM locations l
LEFT JOIN weather_hourly w
	ON l.id = w. location_id
GROUP BY l.id;

-- 2. Average solar radiation per location (overall)
SELECT
    l.name,
    AVG(w.solar_rad_wm2) AS avg_solar_wm2
FROM weather_hourly w
JOIN locations l
    ON w.location_id = l.id
WHERE w.solar_rad_wm2 IS NOT NULL
GROUP BY l.name
ORDER BY avg_solar_wm2 DESC;

-- 3. Top 10 solar hours across all locations
SELECT
    l.name,
    w.timestamp_utc,
    w.solar_rad_wm2
FROM weather_hourly w
JOIN locations l
    ON w.location_id = l.id
WHERE w.solar_rad_wm2 IS NOT NULL
ORDER BY w.solar_rad_wm2 DESC
LIMIT 10;

-- 4. Average solar radiation by hour of day (solar diurnal profile)
SELECT
    l.name,
    CAST(substr(w.timestamp_utc, 12, 2) AS INT) AS hour,
    AVG(w.solar_rad_wm2) AS avg_solar_wm2
FROM weather_hourly w
JOIN locations l
    ON w.location_id = l.id
WHERE w.solar_rad_wm2 IS NOT NULL
GROUP BY l.name, hour
ORDER BY l.name, hour;

-- 5. Average wind speed per location (overall)
SELECT
    l.name,
    AVG(w.wind_speed_ms) AS avg_wind_ms
FROM weather_hourly w
JOIN locations l
    ON w.location_id = l.id
WHERE w.wind_speed_ms IS NOT NULL
GROUP BY l.name
ORDER BY avg_wind_ms DESC;

-- 6. Top 10 windiest hours across all locations
SELECT
    l.name,
    w.timestamp_utc,
    w.wind_speed_ms
FROM weather_hourly w
JOIN locations l
    ON w.location_id = l.id
WHERE w.wind_speed_ms IS NOT NULL
ORDER BY w.wind_speed_ms DESC
LIMIT 10;

-- 7. Average wind speed by hour of day (wind diurnal profile)
SELECT
    l.name,
    CAST(substr(w.timestamp_utc, 12, 2) AS INT) AS hour,
    AVG(w.wind_speed_ms) AS avg_wind_ms
FROM weather_hourly w
JOIN locations l
    ON w.location_id = l.id
WHERE w.wind_speed_ms IS NOT NULL
GROUP BY l.name, hour
ORDER BY l.name, hour;

-- 8. Combined renewable index per location (simple solar + wind summary)
-- Here we approximate a "renewable score" by combining normalized solar and wind.
SELECT
    l.name,
    AVG(w.solar_rad_wm2)        AS avg_solar_wm2,
    AVG(w.wind_speed_ms)        AS avg_wind_ms,
    AVG(w.solar_rad_wm2) 
      + 100.0 * AVG(w.wind_speed_ms) AS combined_renewable_index
FROM weather_hourly w
JOIN locations l
    ON w.location_id = l.id
WHERE w.solar_rad_wm2 IS NOT NULL
  AND w.wind_speed_ms IS NOT NULL
GROUP BY l.name
ORDER BY combined_renewable_index DESC;

