"""
fieldgrid.py
------------
Live gridded weather fields for the geospatial field maps.

A regular n x n lattice of points over a bounding box is sampled from the
Open-Meteo forecast API in batches of 90 coordinates per request (the API takes
comma-separated coordinate lists and answers with one entry per point, in
order).  Each point contributes six surface variables:

    temperature   current 2 m air temperature        (C)
    humidity      current 2 m relative humidity      (%)
    rain          previous full day's precipitation  (mm)
    wind          current 10 m wind speed            (km/h)
    gust          current 10 m wind gusts            (km/h)
    visibility    current horizontal visibility      (km)

Rain uses the previous *complete* day rather than the current hour, which is
zero almost everywhere and would draw a flat map.

The browser interpolates the lattice into a continuous surface and contours it;
this module only fetches and caches.  Responses are cached per bounding box for
20 minutes, which is also roughly how often the model fields update.
"""

from __future__ import annotations

import time

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
BATCH = 90
TTL_SECONDS = 20 * 60
MIN_N, MAX_N = 4, 28

#: A full grid is several hundred weighted units; pacing batches and retrying a
#: throttled one keeps a burst from tripping the per-minute limit.
BATCH_GAP_SECONDS = 0.3
MAX_ATTEMPTS = 4

VARIABLES = ("temperature", "humidity", "rain", "wind", "gust", "visibility")

_cache: dict = {}


def _axis(lo: float, hi: float, n: int) -> list:
    return [round(lo + (hi - lo) * k / (n - 1), 4) for k in range(n)]


def _pick(entry: dict, var: str):
    current = entry.get("current") or {}
    if var == "temperature":
        return current.get("temperature_2m")
    if var == "humidity":
        return current.get("relative_humidity_2m")
    if var == "wind":
        return current.get("wind_speed_10m")
    if var == "gust":
        return current.get("wind_gusts_10m")
    if var == "visibility":
        metres = current.get("visibility")
        return None if metres is None else round(metres / 1000, 2)
    if var == "rain":
        sums = (entry.get("daily") or {}).get("precipitation_sum") or []
        return sums[0] if sums else None          # index 0 = the previous day
    return None


def fetch_grid(lat_min: float, lat_max: float, lon_min: float, lon_max: float,
               n: int = 20) -> dict:
    """
    Sample the six fields on an n x n lattice.

    fields[var][i][j] is the value at lats[i], lons[j]; latitude ascends south
    to north and longitude west to east.  Missing values are None.
    """
    n = max(MIN_N, min(int(n), MAX_N))
    lat_min, lat_max = sorted((float(lat_min), float(lat_max)))
    lon_min, lon_max = sorted((float(lon_min), float(lon_max)))

    key = (round(lat_min, 2), round(lat_max, 2), round(lon_min, 2), round(lon_max, 2), n)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL_SECONDS:
        return hit[1]

    lats = _axis(lat_min, lat_max, n)
    lons = _axis(lon_min, lon_max, n)
    points = [(la, lo) for la in lats for lo in lons]

    results: list = []
    for start in range(0, len(points), BATCH):
        if start:
            time.sleep(BATCH_GAP_SECONDS)       # pace batches instead of bursting them
        chunk = points[start:start + BATCH]
        params = {
            "latitude": ",".join(str(p[0]) for p in chunk),
            "longitude": ",".join(str(p[1]) for p in chunk),
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,"
                       "wind_gusts_10m,visibility",
            "daily": "precipitation_sum",
            "past_days": 1,
            "forecast_days": 1,
            "timezone": "UTC",
            "wind_speed_unit": "kmh",
        }
        payload = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                res = requests.get(FORECAST_URL, params=params, timeout=90)
            except requests.RequestException:
                if attempt == MAX_ATTEMPTS:
                    raise
                time.sleep(1.5 * attempt)
                continue
            if (res.status_code == 429 or res.status_code >= 500) and attempt < MAX_ATTEMPTS:
                time.sleep(1.5 * attempt)
                continue
            res.raise_for_status()
            payload = res.json()
            break
        results.extend(payload if isinstance(payload, list) else [payload])

    if len(results) != len(points):
        raise RuntimeError(f"grid came back incomplete: {len(results)} of {len(points)} points")

    fields = {
        var: [[_pick(results[i * n + j], var) for j in range(n)] for i in range(n)]
        for var in VARIABLES
    }

    out = {
        "lat_min": lat_min, "lat_max": lat_max,
        "lon_min": lon_min, "lon_max": lon_max,
        "n": n, "cells": n * n,
        "lats": lats, "lons": lons,
        "observed_at": (results[0].get("current") or {}).get("time") if results else None,
        "fields": fields,
        "provider": "Open-Meteo",
    }
    _cache[key] = (time.time(), out)
    return out
