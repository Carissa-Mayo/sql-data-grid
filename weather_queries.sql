-- 1) Locations and number of observations
SELECT l.name, COUNT(w.timestamp_utc) AS n_obs
FROM locations l
LEFT JOIN weather_hourly w
  ON l.id = w.location_id
GROUP BY l.id
ORDER BY n_obs DESC;

-- 2) Average solar radiation per location (overall)
SELECT l.name, AVG(w.solar_rad_wm2) AS avg_solar_wm2
FROM weather_hourly w
JOIN locations l ON w.location_id = l.id
WHERE w.solar_rad_wm2 IS NOT NULL
GROUP BY l.name
ORDER BY avg_solar_wm2 DESC;

-- 3) Top 10 solar hours across all locations
SELECT l.name, w.timestamp_utc, w.solar_rad_wm2
FROM weather_hourly w
JOIN locations l ON w.location_id = l.id
WHERE w.solar_rad_wm2 IS NOT NULL
ORDER BY w.solar_rad_wm2 DESC
LIMIT 10;

-- 4) Solar diurnal profile (hour of day, UTC)
SELECT l.name,
       CAST(substr(w.timestamp_utc, 12, 2) AS INT) AS hour_utc,
       AVG(w.solar_rad_wm2) AS avg_solar_wm2
FROM weather_hourly w
JOIN locations l ON w.location_id = l.id
WHERE w.solar_rad_wm2 IS NOT NULL
GROUP BY l.name, hour_utc
ORDER BY l.name, hour_utc;

-- 5) Average wind speed per location (overall)
SELECT l.name, AVG(w.wind_speed_ms) AS avg_wind_ms
FROM weather_hourly w
JOIN locations l ON w.location_id = l.id
WHERE w.wind_speed_ms IS NOT NULL
GROUP BY l.name
ORDER BY avg_wind_ms DESC;

-- 6) Top 10 windiest hours across all locations
SELECT l.name, w.timestamp_utc, w.wind_speed_ms
FROM weather_hourly w
JOIN locations l ON w.location_id = l.id
WHERE w.wind_speed_ms IS NOT NULL
ORDER BY w.wind_speed_ms DESC
LIMIT 10;

-- 7) Wind diurnal profile (hour of day, UTC)
SELECT l.name,
       CAST(substr(w.timestamp_utc, 12, 2) AS INT) AS hour_utc,
       AVG(w.wind_speed_ms) AS avg_wind_ms
FROM weather_hourly w
JOIN locations l ON w.location_id = l.id
WHERE w.wind_speed_ms IS NOT NULL
GROUP BY l.name, hour_utc
ORDER BY l.name, hour_utc;

-- 8) Renewable score per location (rank-based, avoids unit-mixing)
WITH agg AS (
  SELECT location_id,
         AVG(solar_rad_wm2) AS solar_avg,
         AVG(wind_speed_ms) AS wind_avg
  FROM weather_hourly
  WHERE solar_rad_wm2 IS NOT NULL AND wind_speed_ms IS NOT NULL
  GROUP BY location_id
),
ranked AS (
  SELECT location_id, solar_avg, wind_avg,
         RANK() OVER (ORDER BY solar_avg) AS solar_rank,
         RANK() OVER (ORDER BY wind_avg)  AS wind_rank
  FROM agg
)
SELECT l.name,
       r.solar_avg AS avg_solar_wm2,
       r.wind_avg  AS avg_wind_ms,
       (r.solar_rank + r.wind_rank) AS renewable_score
FROM ranked r
JOIN locations l ON l.id = r.location_id
ORDER BY renewable_score DESC;
