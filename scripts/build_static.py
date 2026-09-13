"""
build_static.py
---------------
Produce a fully static build of the dashboard for GitHub Pages.

The Exp 1-5 code in backend/analysis.py runs here (locally, or in the GitHub
Actions runner) and every result is frozen to JSON under docs/data/.  The page
then needs no Python at runtime: static-source.js reads those files and calls
the weather API directly from the browser for the live panels.

Usage:  python scripts/build_static.py [--out docs]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import analysis  # noqa: E402
import regions  # noqa: E402

STAT_COLUMNS = ["tmax_c", "tmin_c", "mean_temp_c", "rh_mean_pct",
                "wind_speed_kmph", "pressure_hpa", "diurnal_temp_range_c",
                "departure_tmax_c"]
HEAT_METRICS = ["tmax_c", "tmin_c", "rh_mean_pct", "wind_speed_kmph"]


def slug(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def write(path: Path, payload) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    path.write_text(text, encoding="utf-8")
    return len(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="docs", help="output directory (default: docs)")
    args = parser.parse_args()

    out = ROOT / args.out
    data = out / "data"
    if out.exists():
        shutil.rmtree(out)
    data.mkdir(parents=True)

    # ---- the page itself -------------------------------------------------
    frontend = ROOT / "frontend"
    html = (frontend / "index.html").read_text(encoding="utf-8")
    html = html.replace(
        '<script src="static-source.js"></script>',
        '<script>window.AETHERCAST_STATIC = true;</script>\n'
        '<script src="static-source.js"></script>',
    )
    (out / "index.html").write_text(html, encoding="utf-8")
    shutil.copy(frontend / "app.js", out / "app.js")
    shutil.copy(frontend / "static-source.js", out / "static-source.js")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    # ---- dataset-wide results -------------------------------------------
    # Warm the region archive first: every state / UT is fetched once and
    # cached on disk, so the analysis loop below never waits on the network.
    print("Loading archives from the repo (nothing is fetched at build time)...", flush=True)
    region_rows = regions.region_catalogue(only_cached=True)
    have = {r["id"] for r in region_rows}

    # Every state and UT must be present - publishing a site quietly missing
    # states is what went wrong when CI was rate limited mid-fetch.
    missing_states = {r[0] for r in regions.REGIONS} - have
    if missing_states:
        raise SystemExit(
            f"aborting: {len(missing_states)} state/UT archive(s) missing -> "
            f"{sorted(missing_states)}\nrestore them from the repo, or re-run the prefetch."
        )

    # Cities, by contrast, backfill over time: build with whatever has landed
    # and say plainly how many are still outstanding.
    import cities as cities_mod
    all_cities = set(cities_mod.catalogue())
    missing_cities = sorted(all_cities - have)
    print(f"  states/UTs: {len(regions.REGIONS)}/{len(regions.REGIONS)}")
    print(f"  cities:     {len(all_cities) - len(missing_cities)}/{len(all_cities)}"
          + (f"  (pending: {len(missing_cities)})" if missing_cities else ""))

    stations = analysis.station_catalogue() + region_rows
    for s in stations:
        s.setdefault("id", slug(s["station"]))

    total = 0
    total += write(data / "stations.json", {"stations": stations})
    total += write(data / "quality.json", analysis.data_quality_report())
    total += write(data / "schema.json", {
        "attributes": [
            {"attribute": a, "kind": k, "scale_type": sc, "measurement": m, "justification": j}
            for a, k, sc, m, j in analysis.ATTRIBUTE_TAXONOMY
        ]
    })

    # ---- per-station results --------------------------------------------
    for i, s in enumerate(stations, 1):
        loc, sid = s["location"], s["id"]
        print(f"[{i:2d}/{len(stations)}] {s['station']}", flush=True)

        total += write(data / "timeseries" / f"{sid}.json", analysis.time_series(loc))
        total += write(data / "correlation" / f"{sid}.json", analysis.correlation_matrix(loc))
        total += write(data / "regression" / f"{sid}.json", analysis.regression_report(loc))
        total += write(data / "aggregation" / f"{sid}.json", analysis.aggregations(loc))
        total += write(data / "categorical" / f"{sid}.json", analysis.categorical_encoding(loc))

        for col in STAT_COLUMNS:
            total += write(data / "stats" / f"{sid}__{col}.json",
                           analysis.descriptive_stats(col, loc))
            total += write(data / "distribution" / f"{sid}__{col}.json",
                           analysis.grouped_frequency(col, 10, loc))

        for metric in HEAT_METRICS:
            total += write(data / "heatmap" / f"{sid}__{metric}.json",
                           analysis.heatmap_matrix(loc, metric))

        # harmonic model coefficients - the browser evaluates them for "today"
        model = analysis.forecast_model(loc)
        total += write(data / "forecast" / f"{sid}.json", {
            "coefficients": model["coefficients"],
            "residual_sd": model["residual_sd"],
            "rmse": model["rmse"],
            "r2": model["r2"],
        })

        # climatology for every calendar day, so severity can be scored offline
        total += write(data / "normals" / f"{sid}.json",
                       {str(d): analysis.climatology(loc, d) for d in range(1, 367)})

    files = sum(1 for _ in data.rglob("*.json"))
    print(f"\nWrote {files} JSON files ({total / 1_048_576:.1f} MB) to {data.relative_to(ROOT)}")
    print(f"Open {out.relative_to(ROOT)}/index.html through any static server.")


if __name__ == "__main__":
    main()
