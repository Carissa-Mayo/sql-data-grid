# Weather API and SQL Queries
## A small-scale project using Python, SQLite and API requests

This project demonstrates a complete, small-scale data workflow for ingesting hourly weather data from the Open-Meteo API and storing it in a relation SQL database. While this example has a small sample size, this schema can be used for large scale grid datasets.

This analysis pulls temperature, wind speed, and solar radiation for several Colorado Front Range cities and performs SQL queries of resource profiles relevant to renewable energy generation and grid planning.

# Data

Variables used:
* wind_speed_10m
* shortwave_radiation

Locations Queried:
* Golden, CO
* Denver, CO
* Boulder, CO

Timeframe: 2024-01-01 to 2025-01-01

# Results

Golden, CO receives the most solar radiation and wind speed on average. However, when looking at 
