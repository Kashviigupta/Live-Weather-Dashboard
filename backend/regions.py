"""
regions.py
----------
Extends the dashboard beyond the 30 AWS stations in Climate_final_k.csv to
every Indian state and union territory.

There is no archive history for those locations in the CSV, so this module
pulls real daily observations for 2019-2024 from the Open-Meteo historical
reanalysis (keyless) and reshapes them into exactly the schema the dataset
uses - same column names, same category bands, same derived fields.  The
Exp 1-5 code in analysis.py then runs on a region frame without knowing or
caring where the rows came from, so regression, correlation, distribution,
aggregation and the heatmap are computed the same way for both sources.

Responses are cached under data/cache/regions/ so a rebuild is offline-fast.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
START_DATE = "2019-01-01"
END_DATE = "2024-12-31"

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "regions"

MONTH_ORDER = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]

# Season mapping read off the dataset: Dec-Feb winter, Mar-May pre-monsoon,
# Jun-Sep monsoon, Oct-Nov post-monsoon.
SEASON_BY_MONTH = {12: "Winter", 1: "Winter", 2: "Winter",
                   3: "Pre-Monsoon/Summer", 4: "Pre-Monsoon/Summer", 5: "Pre-Monsoon/Summer",
                   6: "Monsoon", 7: "Monsoon", 8: "Monsoon", 9: "Monsoon",
                   10: "Post-Monsoon", 11: "Post-Monsoon"}

# Category bands, taken from the dataset's own boundaries so both sources encode
# identically (see Exp-1 ordinal encodings).
TMAX_BANDS = [(25.0, "Cool"), (35.0, "Warm"), (40.0, "Hot"), (np.inf, "Very Hot")]
WIND_BANDS = [(6.0, "Calm"), (12.0, "Light"), (20.0, "Moderate"), (np.inf, "Strong")]
PRESSURE_BANDS = [(1000.0, "Low"), (1013.05, "Normal"), (np.inf, "High")]

# IMD heatwave rule: a departure of +4.5 C or more, once the day is actually hot
# for that terrain.  The CSV carries its own precomputed flags; regions are
# scored with this documented rule instead.
HEATWAVE_MIN_TMAX = {"PLAINS": 40.0, "COASTAL": 37.0, "HILLY": 30.0}

COASTAL_REGIONS = {
    "gujarat", "maharashtra", "goa", "karnataka", "kerala", "tamil-nadu",
    "andhra-pradesh", "odisha", "west-bengal", "puducherry", "lakshadweep",
    "andaman-nicobar-islands", "daman-diu-dadra-nagar-haveli",
}

# state / union territory -> representative point (the capital), with the same
# zone vocabulary the dataset uses, plus North-East for the eight NE states.
REGIONS = [
    # id, display name, zone, latitude, longitude, kind
    ("andhra-pradesh", "Andhra Pradesh", "South", 16.5062, 80.6480, "State"),
    ("arunachal-pradesh", "Arunachal Pradesh", "North-East", 27.0844, 93.6053, "State"),
    ("assam", "Assam", "North-East", 26.1445, 91.7362, "State"),
    ("bihar", "Bihar", "East", 25.5941, 85.1376, "State"),
    ("chhattisgarh", "Chhattisgarh", "Central", 21.2514, 81.6296, "State"),
    ("goa", "Goa", "West", 15.4909, 73.8278, "State"),
    ("gujarat", "Gujarat", "West", 23.2156, 72.6369, "State"),
    ("haryana", "Haryana", "North", 30.7333, 76.7794, "State"),
    ("himachal-pradesh", "Himachal Pradesh", "North", 31.1048, 77.1734, "State"),
    ("jharkhand", "Jharkhand", "East", 23.3441, 85.3096, "State"),
    ("karnataka", "Karnataka", "South", 12.9716, 77.5946, "State"),
    ("kerala", "Kerala", "South", 8.5241, 76.9366, "State"),
    ("madhya-pradesh", "Madhya Pradesh", "Central", 23.2599, 77.4126, "State"),
    ("maharashtra", "Maharashtra", "West", 19.0760, 72.8777, "State"),
    ("manipur", "Manipur", "North-East", 24.8170, 93.9368, "State"),
    ("meghalaya", "Meghalaya", "North-East", 25.5788, 91.8933, "State"),
    ("mizoram", "Mizoram", "North-East", 23.7271, 92.7176, "State"),
    ("nagaland", "Nagaland", "North-East", 25.6751, 94.1086, "State"),
    ("odisha", "Odisha", "East", 20.2961, 85.8245, "State"),
    ("punjab", "Punjab", "North", 30.7333, 76.7794, "State"),
    ("rajasthan", "Rajasthan", "North", 26.9124, 75.7873, "State"),
    ("sikkim", "Sikkim", "North-East", 27.3314, 88.6138, "State"),
    ("tamil-nadu", "Tamil Nadu", "South", 13.0827, 80.2707, "State"),
    ("telangana", "Telangana", "South", 17.3850, 78.4867, "State"),
    ("tripura", "Tripura", "North-East", 23.8315, 91.2868, "State"),
    ("uttar-pradesh", "Uttar Pradesh", "North", 26.8467, 80.9462, "State"),
    ("uttarakhand", "Uttarakhand", "North", 30.3165, 78.0322, "State"),
    ("west-bengal", "West Bengal", "East", 22.5726, 88.3639, "State"),
    ("andaman-nicobar-islands", "Andaman & Nicobar Islands", "South", 11.6234, 92.7265, "UT"),
    ("chandigarh", "Chandigarh", "North", 30.7333, 76.7794, "UT"),
    ("daman-diu-dadra-nagar-haveli", "Dadra & Nagar Haveli and Daman & Diu", "West", 20.3974, 72.8328, "UT"),
    ("delhi", "Delhi", "North", 28.6139, 77.2090, "UT"),
    ("jammu-kashmir", "Jammu & Kashmir", "North", 34.0837, 74.7973, "UT"),
    ("ladakh", "Ladakh", "North", 34.1526, 77.5771, "UT"),
    ("lakshadweep", "Lakshadweep", "South", 10.5667, 72.6417, "UT"),
    ("puducherry", "Puducherry", "South", 11.9416, 79.8083, "UT"),
]

REGION_BY_ID = {r[0]: r for r in REGIONS}
_frames: dict[str, pd.DataFrame] = {}


def location_key(region_id: str) -> str:
    """The location string a region is addressed by throughout the API."""
    return f"region:{region_id}"


def is_region(location: str | None) -> bool:
    return bool(location) and str(location).startswith("region:")


def _band(value: float, bands) -> str:
    for edge, label in bands:
        if value < edge:
            return label
    return bands[-1][1]


#: Six years of daily data is a costly request, and the free tier throttles by
#: weighted units rather than plain call count - so space the calls out and back
#: off when the API says 429.
MIN_SECONDS_BETWEEN_CALLS = 12.0
MAX_ATTEMPTS = 6
_last_call_at = 0.0


def _throttle() -> None:
    global _last_call_at
    wait = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call_at)
    if wait > 0:
        time.sleep(wait)
    _last_call_at = time.monotonic()


def _fetch_archive(lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "daily": ",".join([
            "temperature_2m_max", "temperature_2m_min", "temperature_2m_mean",
            "relative_humidity_2m_max", "relative_humidity_2m_min",
            "relative_humidity_2m_mean", "wind_speed_10m_max",
            "pressure_msl_mean", "precipitation_sum",
        ]),
        "timezone": "auto",
        "wind_speed_unit": "kmh",
    }
    delay = 20.0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        _throttle()
        res = requests.get(ARCHIVE_URL, params=params, timeout=180)

        if res.status_code == 429:
            if attempt == MAX_ATTEMPTS:
                res.raise_for_status()
            retry_after = res.headers.get("Retry-After")
            pause = float(retry_after) if retry_after and retry_after.isdigit() else delay
            print(f"      rate limited, retrying in {pause:.0f}s "
                  f"(attempt {attempt}/{MAX_ATTEMPTS})", flush=True)
            time.sleep(pause)
            delay = min(delay * 2, 180)
            continue

        res.raise_for_status()
        return res.json()

    raise RuntimeError("archive fetch exhausted its retries")


def _build_frame(region_id: str) -> pd.DataFrame:
    rid, name, zone, lat, lon, kind = REGION_BY_ID[region_id]
    payload = _fetch_archive(lat, lon)
    daily = payload["daily"]
    elevation = float(payload.get("elevation") or 0)

    df = pd.DataFrame({
        "date_parsed": pd.to_datetime(daily["time"]),
        "tmax_c": daily["temperature_2m_max"],
        "tmin_c": daily["temperature_2m_min"],
        "mean_temp_c": daily["temperature_2m_mean"],
        "rh_max_pct": daily["relative_humidity_2m_max"],
        "rh_min_pct": daily["relative_humidity_2m_min"],
        "rh_mean_pct": daily["relative_humidity_2m_mean"],
        "wind_speed_kmph": daily["wind_speed_10m_max"],
        "pressure_hpa": daily["pressure_msl_mean"],
        "precip_mm": daily["precipitation_sum"],
    }).dropna(subset=["tmax_c", "tmin_c"])

    # numeric columns arrive as floats already; fill the rare gap the way Exp-2
    # does (mean imputation) so downstream code never sees NaN
    for col in ["mean_temp_c", "rh_max_pct", "rh_min_pct", "rh_mean_pct",
                "wind_speed_kmph", "pressure_hpa", "precip_mm"]:
        if df[col].isna().any():
            df[col] = df[col].fillna(df[col].mean())

    terrain = ("HILLY" if elevation >= 600
               else "COASTAL" if rid in COASTAL_REGIONS else "PLAINS")

    df["date"] = df["date_parsed"].dt.strftime("%d-%m-%Y")
    df["year"] = df["date_parsed"].dt.year
    df["month"] = df["date_parsed"].dt.month
    df["month_name"] = df["date_parsed"].dt.month_name()
    df["day"] = df["date_parsed"].dt.day
    df["day_of_year"] = df["date_parsed"].dt.dayofyear
    df["season"] = df["month"].map(SEASON_BY_MONTH)

    df["location"] = f"{name}, {kind}, India"
    df["station"] = name
    df["state"] = name
    df["zone"] = zone
    df["terrain_type"] = terrain
    df["latitude"] = lat
    df["longitude"] = lon
    df["elevation_m"] = int(round(elevation))

    df["diurnal_temp_range_c"] = (df["tmax_c"] - df["tmin_c"]).round(1)

    # Normals: the climatological mean for each calendar day, smoothed over a
    # +/- 7 day window, which is how a station normal is defined.
    for src, dest in [("tmax_c", "normal_tmax_c"), ("tmin_c", "normal_tmin_c")]:
        by_doy = df.groupby("day_of_year")[src].mean()
        smooth = (pd.concat([by_doy] * 3).rolling(15, center=True, min_periods=1)
                  .mean().iloc[len(by_doy):2 * len(by_doy)])
        smooth.index = by_doy.index
        df[dest] = df["day_of_year"].map(smooth).round(1)

    df["departure_tmax_c"] = (df["tmax_c"] - df["normal_tmax_c"]).round(1)
    df["departure_tmin_c"] = (df["tmin_c"] - df["normal_tmin_c"]).round(1)

    hot_enough = df["tmax_c"] >= HEATWAVE_MIN_TMAX[terrain]
    df["heatwave_flag"] = ((df["departure_tmax_c"] >= 4.5) & hot_enough).astype(int)
    df["warm_night_flag"] = ((df["departure_tmin_c"] >= 4.5) & hot_enough).astype(int)

    severity = np.where(~hot_enough | (df["departure_tmax_c"] < 4.5), "NONE",
                        np.where(df["departure_tmax_c"] >= 6.5, "SEVERE", "MODERATE"))
    df["severity"] = severity
    df["alert_color"] = np.select(
        [severity == "SEVERE", severity == "MODERATE", df["departure_tmax_c"] >= 3.0],
        ["RED", "ORANGE", "YELLOW"], default="GREEN")

    df["tmax_category"] = df["tmax_c"].map(lambda v: _band(v, TMAX_BANDS))
    df["wind_category"] = df["wind_speed_kmph"].map(lambda v: _band(v, WIND_BANDS))
    df["pressure_category"] = df["pressure_hpa"].map(lambda v: _band(v, PRESSURE_BANDS))
    df["data_corrected_flag"] = 0

    return df


def region_frame(region_id: str, refresh: bool = False) -> pd.DataFrame:
    """Region history in the dataset's schema, memoised in RAM and on disk."""
    if not refresh and region_id in _frames:
        return _frames[region_id]

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{region_id}.csv"

    if cache_file.exists() and not refresh:
        df = pd.read_csv(cache_file)
        df["date_parsed"] = pd.to_datetime(df["date_parsed"])
    else:
        df = _build_frame(region_id)
        df.to_csv(cache_file, index=False)

    df["month_name"] = pd.Categorical(df["month_name"], categories=MONTH_ORDER, ordered=True)
    df["season"] = pd.Categorical(
        df["season"], categories=["Winter", "Pre-Monsoon/Summer", "Monsoon", "Post-Monsoon"],
        ordered=True)

    _frames[region_id] = df
    return df


def region_catalogue(only_cached: bool = False) -> list:
    """Region records shaped exactly like analysis.station_catalogue() rows."""
    out = []
    for rid, name, zone, lat, lon, kind in REGIONS:
        cache_file = CACHE_DIR / f"{rid}.csv"
        if only_cached and not cache_file.exists():
            continue
        try:
            df = region_frame(rid)
        except Exception:
            continue
        out.append({
            "location": location_key(rid),
            "id": rid,
            "station": name,
            "state": name,
            "zone": zone,
            "terrain_type": df["terrain_type"].iloc[0],
            "kind": kind,
            "source": "open-meteo-archive",
            "latitude": lat,
            "longitude": lon,
            "elevation_m": int(df["elevation_m"].iloc[0]),
            "avg_tmax": round(float(df["tmax_c"].mean()), 1),
            "avg_tmin": round(float(df["tmin_c"].mean()), 1),
            "avg_mean_temp": round(float(df["mean_temp_c"].mean()), 1),
            "avg_rh": round(float(df["rh_mean_pct"].mean()), 1),
            "avg_wind": round(float(df["wind_speed_kmph"].mean()), 1),
            "avg_pressure": round(float(df["pressure_hpa"].mean()), 1),
            "heatwave_days": int(df["heatwave_flag"].sum()),
            "records": int(len(df)),
        })
    return sorted(out, key=lambda d: d["station"])


def prefetch(verbose: bool = True) -> None:
    """Warm the disk cache for every region (used by the static build)."""
    for i, (rid, name, *_rest) in enumerate(REGIONS, 1):
        try:
            df = region_frame(rid)
            if verbose:
                print(f"  [{i:2d}/{len(REGIONS)}] {name}: {len(df)} days", flush=True)
        except Exception as exc:
            print(f"  [{i:2d}/{len(REGIONS)}] {name}: FAILED - {exc}", flush=True)
