"""
app.py
------
FastAPI service behind the Aethercast dashboard.

It exposes one endpoint per experiment (data quality, descriptive statistics,
distribution, correlation, regression, aggregation, heatmap, geospatial,
categorical encoding) plus the live-weather endpoints, and serves the frontend
as static files.

Run:  python backend/app.py      ->  http://127.0.0.1:8000
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analysis  # noqa: E402
import live_weather  # noqa: E402
import regions  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

app = FastAPI(title="Aethercast - Live Climate Intelligence API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _catalogue() -> list:
    """
    Every selectable location: the 30 AWS stations, every state / UT, and the
    cities whose archive is on disk.

    only_cached keeps this honest and fast - an uncached city is simply not
    offered, rather than making a request thread wait on a throttled archive
    fetch.  Cities backfill as their archives land.
    """
    return analysis.station_catalogue() + regions.region_catalogue(only_cached=True)


def _station(location: str):
    """Resolve a location string to a station or region record."""
    if regions.is_region(location):
        region_id = location.split(":", 1)[1]
        if regions.place(region_id) and not regions.cache_path(region_id).exists():
            raise HTTPException(
                status_code=503,
                detail=f"Archive for '{region_id}' has not been fetched yet.")
        for r in regions.region_catalogue(only_cached=True):
            if r["id"] == region_id:
                return r
        raise HTTPException(status_code=404, detail=f"Unknown region: {region_id}")

    stations = analysis.station_catalogue()
    if not location or location == "ALL":
        return stations[0]
    for s in stations:
        if s["location"] == location or s["station"] == location:
            return s
    raise HTTPException(status_code=404, detail=f"Unknown station: {location}")


# ------------------------------------------------------------------ meta
@app.get("/api/stations")
def stations():
    return {"stations": _catalogue()}


@app.get("/api/schema")
def schema():
    """Exp-1: attribute taxonomy (nominal / ordinal / interval / ratio)."""
    return {
        "attributes": [
            {"attribute": a, "kind": k, "scale_type": s, "measurement": m, "justification": j}
            for a, k, s, m, j in analysis.ATTRIBUTE_TAXONOMY
        ]
    }


@app.get("/api/quality")
def quality():
    """Exp-2: null counts, duplicates, IQR outliers, completeness."""
    return analysis.data_quality_report()


# ------------------------------------------------------------------ live
@app.get("/api/live")
def live(location: str = Query("ALL")):
    """Live conditions for a station, scored against its dataset climatology."""
    st = _station(location)
    try:
        obs = live_weather.fetch_live(st["latitude"], st["longitude"], st["station"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Live provider unavailable: {exc}")

    import datetime as dt
    doy = dt.date.today().timetuple().tm_yday
    normals = analysis.climatology(st["location"], doy)

    # departure is scored on today's MAX against the station's normal max, the
    # same pairing the dataset uses for departure_tmax_c / heatwave_flag
    day_max = (obs.get("today") or {}).get("tmax_c")
    reference = day_max if day_max is not None else obs.get("temperature_c")
    departure = round(reference - normals["normal_tmax"], 1) if reference is not None else None

    if departure is None:
        severity, alert = "NONE", "GREEN"
    elif departure >= 6.5:
        severity, alert = "SEVERE", "RED"
    elif departure >= 4.5:
        severity, alert = "MODERATE", "ORANGE"
    elif departure >= 3.0:
        severity, alert = "MILD", "YELLOW"
    else:
        severity, alert = "NONE", "GREEN"

    return {
        "station": st,
        "observation": obs,
        "normals": normals,
        "archive": analysis.data_source(st["location"]),
        "departure_reference_c": reference,
        "departure_tmax_c": departure,
        "severity": severity,
        "alert_color": alert,
    }


@app.get("/api/forecast")
def forecast(location: str = Query("ALL"), live_temp: float | None = None):
    """Exp-5 normal equation, harmonic basis: +-7 day seasonal projection."""
    st = _station(location)
    return analysis.forecast_model(st["location"], live_temp)


# ------------------------------------------------------- experiment APIs
@app.get("/api/timeseries")
def timeseries(location: str = Query("ALL"), days: int = 365):
    st = _station(location)
    return analysis.time_series(st["location"], days=days)


@app.get("/api/stats")
def stats(location: str = Query("ALL"), column: str = "tmax_c"):
    """Exp-3: manual central tendency & variability."""
    st = _station(location)
    return analysis.descriptive_stats(column, st["location"])


@app.get("/api/distribution")
def distribution(location: str = Query("ALL"), column: str = "tmax_c", classes: int = 10):
    """Exp-3 grouped data + Exp-2 histogram/KDE."""
    st = _station(location)
    return analysis.grouped_frequency(column, classes, st["location"])


@app.get("/api/correlation")
def correlation(location: str = Query("ALL")):
    """Exp-4 manual Pearson r + Exp-2 correlation heatmap."""
    st = _station(location)
    return analysis.correlation_matrix(st["location"])


@app.get("/api/regression")
def regression(location: str = Query("ALL")):
    """Exp-5: simple vs multiple linear regression."""
    st = _station(location)
    return analysis.regression_report(st["location"])


@app.get("/api/aggregation")
def aggregation(location: str = Query("ALL")):
    """Exp-2 groupby suite."""
    st = _station(location)
    return analysis.aggregations(st["location"])


@app.get("/api/heatmap")
def heatmap(location: str = Query("ALL"), metric: str = "tmax_c"):
    """Exp-2 month x year matrix."""
    st = _station(location)
    return analysis.heatmap_matrix(st["location"], metric)


@app.get("/api/categorical")
def categorical(location: str = Query("ALL")):
    """Exp-1 ordinal encoding + frequency listing."""
    st = _station(location)
    return analysis.categorical_encoding(st["location"])


@app.get("/api/field")
def field(lat_min: float, lat_max: float, lon_min: float, lon_max: float, n: int = 20):
    """Live gridded surface fields for the geospatial maps (see fieldgrid.py)."""
    import fieldgrid
    try:
        return fieldgrid.fetch_grid(lat_min, lat_max, lon_min, lon_max, n)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Field grid unavailable: {exc}")


@app.get("/api/health")
def health():
    q = analysis.data_quality_report()
    return {"status": "ok", "rows": q["rows"], "stations": q["stations"],
            "date_range": q["date_range"]}


# --------------------------------------------------------------- static
@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
