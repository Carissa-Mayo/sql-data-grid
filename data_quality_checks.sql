-- Data quality / governance checks (run manually or embed in validation)
-- Freshness: latest timestamp loaded
SELECT MAX(timestamp_utc) AS max_timestamp_utc FROM weather_hourly;

-- Missing critical fields
SELECT COUNT(*) AS null_critical
FROM weather_hourly
WHERE wind_speed_ms IS NULL OR solar_rad_wm2 IS NULL;

-- Range checks
SELECT COUNT(*) AS negative_wind FROM weather_hourly WHERE wind_speed_ms < 0;
SELECT COUNT(*) AS negative_solar FROM weather_hourly WHERE solar_rad_wm2 < 0;

-- Outlier inspection (tune threshold as needed)
SELECT l.name, w.timestamp_utc, w.wind_speed_ms
FROM weather_hourly w
JOIN locations l ON l.id = w.location_id
WHERE w.wind_speed_ms > 40
ORDER BY w.wind_speed_ms DESC
LIMIT 20;
