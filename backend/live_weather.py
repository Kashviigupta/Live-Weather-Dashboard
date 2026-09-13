"""
live_weather.py
---------------
Live weather ingestion for the dashboard.

Default provider is Open-Meteo (no API key required, free for non-commercial
use).  If an OpenWeatherMap key is present in the environment
(OPENWEATHER_API_KEY) that provider is used instead for the current conditions.

Every response is normalised to one shape so the frontend never has to care
which provider answered.
"""

from __future__ import annotations

import os
import time

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OWM_URL = "https://api.openweathermap.org/data/2.5/weather"

CACHE_TTL_SECONDS = 60
_cache: dict = {}

WMO_CODES = {
    0: ("Clear sky", "clear"), 1: ("Mainly clear", "clear"), 2: ("Partly cloudy", "partly"),
    3: ("Overcast", "cloudy"), 45: ("Fog", "fog"), 48: ("Depositing rime fog", "fog"),
    51: ("Light drizzle", "drizzle"), 53: ("Moderate drizzle", "drizzle"),
    55: ("Dense drizzle", "drizzle"), 61: ("Slight rain", "rain"),
    63: ("Moderate rain", "rain"), 65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"), 67: ("Heavy freezing rain", "rain"),
    71: ("Slight snow", "snow"), 73: ("Moderate snow", "snow"), 75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"), 80: ("Rain showers", "rain"),
    81: ("Moderate rain showers", "rain"), 82: ("Violent rain showers", "rain"),
    85: ("Snow showers", "snow"), 86: ("Heavy snow showers", "snow"),
    95: ("Thunderstorm", "storm"), 96: ("Thunderstorm with hail", "storm"),
    99: ("Thunderstorm with heavy hail", "storm"),
}

COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _cached(key: str, producer, ttl: int = CACHE_TTL_SECONDS):
    hit = _cache.get(key)
    now = time.time()
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = producer()
    _cache[key] = (now, value)
    return value


def compass_point(degrees: float) -> str:
    return COMPASS[int((degrees % 360) / 22.5 + 0.5) % 16]


def dew_point(temp_c: float, rh_pct: float) -> float:
    """Magnus-Tetens approximation - used for the dew point vector tile."""
    a, b = 17.27, 237.7
    rh = max(min(rh_pct, 100.0), 1.0)
    alpha = (a * temp_c) / (b + temp_c) + __import__("math").log(rh / 100.0)
    return round((b * alpha) / (a - alpha), 1)


def _open_meteo(lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ",".join([
            "temperature_2m", "relative_humidity_2m", "apparent_temperature",
            "is_day", "precipitation", "weather_code", "cloud_cover",
            "pressure_msl", "surface_pressure", "wind_speed_10m",
            "wind_direction_10m", "wind_gusts_10m",
        ]),
        "hourly": ",".join([
            "temperature_2m", "relative_humidity_2m", "dew_point_2m",
            "precipitation_probability", "precipitation", "pressure_msl",
            "wind_speed_10m", "visibility",
        ]),
        "daily": ",".join([
            "temperature_2m_max", "temperature_2m_min", "precipitation_sum",
            "precipitation_probability_max", "wind_speed_10m_max",
            "uv_index_max", "sunrise", "sunset", "daylight_duration",
        ]),
        "timezone": "auto",
        "forecast_days": 7,
        "past_days": 2,
        "wind_speed_unit": "kmh",
    }
    r = requests.get(FORECAST_URL, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _air_quality(lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "pm10,pm2_5,european_aqi,us_aqi,uv_index",
        "timezone": "auto",
    }
    try:
        r = requests.get(AIR_QUALITY_URL, params=params, timeout=15)
        r.raise_for_status()
        return r.json().get("current", {})
    except Exception:
        return {}


def _openweather(lat: float, lon: float, key: str) -> dict:
    params = {"lat": lat, "lon": lon, "appid": key, "units": "metric"}
    r = requests.get(OWM_URL, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_live(lat: float, lon: float, station: str = "") -> dict:
    """Current conditions + short-term hourly/daily outlook, normalised."""

    def build():
        data = _open_meteo(lat, lon)
        cur = data.get("current", {})
        hourly = data.get("hourly", {})
        daily = data.get("daily", {})
        aq = _air_quality(lat, lon)

        code = int(cur.get("weather_code") or 0)
        desc, icon = WMO_CODES.get(code, ("Unknown", "clear"))

        temp = cur.get("temperature_2m")
        rh = cur.get("relative_humidity_2m")
        wind_dir = cur.get("wind_direction_10m") or 0

        # pressure trend over the last three hours of the hourly series
        press_series = [p for p in (hourly.get("pressure_msl") or []) if p is not None]
        now_index = _now_index(hourly.get("time", []), data.get("current", {}).get("time"))
        trend = None
        if press_series and now_index is not None and now_index >= 3:
            trend = round(press_series[now_index] - press_series[now_index - 3], 1)

        # next-24h precipitation probability peak
        probs = hourly.get("precipitation_probability") or []
        times = hourly.get("time") or []
        peak_prob, peak_time = None, None
        if probs and now_index is not None:
            window = [(p, t) for p, t in zip(probs[now_index:now_index + 24],
                                             times[now_index:now_index + 24]) if p is not None]
            if window:
                peak_prob, peak_time = max(window, key=lambda pair: pair[0])

        vis = hourly.get("visibility") or []
        visibility_km = round(vis[now_index] / 1000, 1) if (vis and now_index is not None
                                                            and vis[now_index] is not None) else None

        # override current conditions with OpenWeatherMap when a key is set
        provider = "Open-Meteo"
        owm_key = os.environ.get("OPENWEATHER_API_KEY")
        if owm_key:
            try:
                owm = _openweather(lat, lon, owm_key)
                temp = owm["main"]["temp"]
                rh = owm["main"]["humidity"]
                desc = owm["weather"][0]["description"].title()
                wind_dir = owm.get("wind", {}).get("deg", wind_dir)
                provider = "OpenWeatherMap"
            except Exception:
                provider = "Open-Meteo (OWM fallback)"

        hourly_window = slice(max((now_index or 0) - 12, 0), (now_index or 0) + 13)

        return {
            "station": station,
            "provider": provider,
            "observed_at": cur.get("time"),
            "timezone": data.get("timezone"),
            "latitude": lat,
            "longitude": lon,
            "elevation_m": data.get("elevation"),
            "temperature_c": temp,
            "apparent_c": cur.get("apparent_temperature"),
            "humidity_pct": rh,
            "dew_point_c": dew_point(temp, rh) if temp is not None and rh is not None else None,
            "pressure_hpa": cur.get("pressure_msl"),
            "pressure_trend_3h": trend,
            "wind_speed_kmph": cur.get("wind_speed_10m"),
            "wind_gust_kmph": cur.get("wind_gusts_10m"),
            "wind_direction_deg": wind_dir,
            "wind_compass": compass_point(wind_dir),
            "cloud_cover_pct": cur.get("cloud_cover"),
            "precipitation_mm": cur.get("precipitation"),
            "precip_probability_peak_pct": peak_prob,
            "precip_probability_peak_time": peak_time,
            "visibility_km": visibility_km,
            "is_day": bool(cur.get("is_day", 1)),
            "condition": desc,
            "icon": icon,
            "weather_code": code,
            "air_quality": {
                "pm2_5": aq.get("pm2_5"),
                "pm10": aq.get("pm10"),
                "european_aqi": aq.get("european_aqi"),
                "us_aqi": aq.get("us_aqi"),
                "uv_index": aq.get("uv_index"),
            },
            "today": {
                "tmax_c": _first(daily.get("temperature_2m_max"), now_day_index(daily)),
                "tmin_c": _first(daily.get("temperature_2m_min"), now_day_index(daily)),
                "precip_sum_mm": _first(daily.get("precipitation_sum"), now_day_index(daily)),
                "uv_index_max": _first(daily.get("uv_index_max"), now_day_index(daily)),
                "sunrise": _first(daily.get("sunrise"), now_day_index(daily)),
                "sunset": _first(daily.get("sunset"), now_day_index(daily)),
                "daylight_seconds": _first(daily.get("daylight_duration"), now_day_index(daily)),
            },
            "hourly": {
                "time": (hourly.get("time") or [])[hourly_window],
                "temperature": (hourly.get("temperature_2m") or [])[hourly_window],
                "dew_point": (hourly.get("dew_point_2m") or [])[hourly_window],
                "humidity": (hourly.get("relative_humidity_2m") or [])[hourly_window],
                "precip_probability": (hourly.get("precipitation_probability") or [])[hourly_window],
                "now_offset": min(12, now_index or 0),
            },
            "daily": {
                "time": daily.get("time", []),
                "tmax": daily.get("temperature_2m_max", []),
                "tmin": daily.get("temperature_2m_min", []),
                "precip": daily.get("precipitation_sum", []),
                "precip_probability": daily.get("precipitation_probability_max", []),
                "wind_max": daily.get("wind_speed_10m_max", []),
            },
        }

    return _cached(f"live:{lat}:{lon}", build)


def _now_index(times, current_time):
    if not times:
        return None
    if current_time and current_time[:13] in [t[:13] for t in times]:
        return [t[:13] for t in times].index(current_time[:13])
    return len(times) // 2


def now_day_index(daily: dict) -> int:
    """Index of today inside the daily arrays (past_days=2 shifts it)."""
    times = daily.get("time") or []
    if not times:
        return 0
    import datetime as _dt
    today = _dt.date.today().isoformat()
    return times.index(today) if today in times else min(2, len(times) - 1)


def _first(seq, index=0):
    if not seq:
        return None
    if index < len(seq):
        return seq[index]
    return seq[0]
