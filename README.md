# Aethercast — Live Climate Intelligence Dashboard

A live weather dashboard built on the **Climate_final_k** India AWS dataset and the
FDS experiments (Exp 1–5). Every analytical panel is computed by the experiment
code running server-side; the current-conditions panels stream from a live
weather API.

```
Live-Weather-Dashboard/
├── data/Climate_final_k.csv      # the climate dataset
├── backend/
│   ├── analysis.py               # Exp 1–5 code as reusable functions
│   ├── live_weather.py           # live provider client (Open-Meteo / OpenWeatherMap)
│   └── app.py                    # FastAPI service + static hosting
├── frontend/
│   ├── index.html                # the Aethercast UI
│   ├── app.js                    # data binding + charts
│   └── static-source.js          # serverless mode for GitHub Pages
├── scripts/build_static.py       # freezes the analysis to JSON for Pages
├── .github/workflows/            # Pages build + deploy
├── render.yaml                   # optional: host the real FastAPI service
└── requirements.txt
```

Two ways to run it: **with the FastAPI backend**, where the experiment code runs
per request, or **fully static on GitHub Pages**, where it runs at build time and
the browser talks to the weather API directly. Both serve the same UI from the
same source files — see [Deploying](#deploying).

## Run it

```bash
pip install -r requirements.txt
python backend/app.py
# open http://127.0.0.1:8000
```

No API key is needed — the default provider is **Open-Meteo** (free, keyless),
plus its air-quality API for PM2.5 / PM10 / AQI / UV. To use OpenWeatherMap for
current conditions instead, set a key before starting:

```powershell
$env:OPENWEATHER_API_KEY = "your_key"; python backend/app.py
```

The dashboard polls `/api/live` every 60 s in **Live** mode (5 min in Hourly,
15 min in Daily); responses are cached server-side for 60 s so the provider is
not hammered.

## Deploying

### GitHub Pages (live URL, no server to run)

`.github/workflows/deploy-pages.yml` runs on every push to `main`. It installs
the dependencies, executes `scripts/build_static.py` — which runs the Exp 1–5
code over the full dataset and freezes every result to JSON — and publishes the
`docs/` build to Pages:

**https://kashviigupta.github.io/Live-Weather-Dashboard/**

The page stays live: `frontend/static-source.js` calls Open-Meteo straight from
the browser for current conditions, air quality and the hourly/daily outlook,
then scores heatwave severity against the station normals and evaluates the
Exp-5 harmonic forecast client-side from the stored coefficients. Only the
archive analytics are pre-computed — they're derived from a fixed CSV, so
nothing is lost by building them ahead of time.

**One-time setup:** open **Settings → Pages** and set **Source** to *GitHub
Actions*. The workflow token is not permitted to switch Pages on by itself, so
the first run fails at the `configure-pages` step until this is set. Then push
anything (or **Actions → Deploy dashboard to GitHub Pages → Run workflow**) and
the site goes up. A build takes ~4 minutes — 813 JSON files, ~4.4 MB.

To preview the exact Pages build locally:

```bash
python scripts/build_static.py      # writes docs/
python -m http.server 8080 -d docs  # http://127.0.0.1:8080
```

### Render (runs the real FastAPI service)

`render.yaml` is a Blueprint for the full backend, so the experiment code runs
per request instead of at build time. On [render.com](https://render.com):
**New → Blueprint → connect this repo → Apply**. The free instance sleeps after
15 minutes idle and takes ~50 s to wake. `OPENWEATHER_API_KEY` is optional.

## Where each experiment appears

| Experiment | What it computes | Where it shows up |
|---|---|---|
| **Exp 1** — attribute classification | Nominal / Ordinal / Interval / Ratio taxonomy; ordinal label encodings | *Model Diagnostics* drawer (taxonomy table); *Aggregation & Encoding* card (severity, alert_color, tmax_category, wind_category codes) |
| **Exp 2** — data handling | `info` / `isnull` / `duplicated`, mean–mode imputation, 1.5 × IQR outlier trimming, groupby suite, correlation heatmap, station scatter | *Pipeline & Anomaly Engine* strip, *Climate Density Matrix*, *Geospatial Station Grid*, *Aggregation* chart, outlier ledger |
| **Exp 3** — central tendency & variability | `mean_manual`, `median_manual`, `mode_manual`, `variance_manual`, `std_manual` (Newton–Raphson), `percentile_manual`, `iqr_manual`, grouped-data frequency table | *Statistical Distribution* panel — histogram, KDE, box-plot, μ/σ/median/mode/skew/kurtosis, grouped-vs-ungrouped comparison line |
| **Exp 4** — correlation coefficient | `correlation_coefficient(x, y)` from first principles + full Pearson matrix | *Correlation Matrix* panel and the three labelled pairs below it (positive / negative / no correlation) |
| **Exp 5** — regression | `simple_linear_regression` (least squares) and `multiple_linear_regression` (normal equation `b = (XᵀX)⁻¹Xᵀy`), MAE / RMSE / R² | *Regression Lab* (SLR scatter + line, MLR actual-vs-predicted) and the forecast ribbon in the time-series panel |

The forecast curve reuses the Exp-5 normal equation with a harmonic
(sin/cos of `day_of_year`) basis, so the ±7-day projection follows the station's
annual cycle; the live reading anchors the curve at *now*, and the ribbon is
±1.96 σ of the fit residuals.

> **Reading the departure badge.** The archive's `normal_tmax_c` runs a few
> degrees cooler than what the live provider reports for the same calendar
> window at many stations (mid-September Delhi: archive normal ≈ 25.8 °C vs
> live day max ≈ 31.9 °C), so live departures and severity flags read high —
> a property of the dataset, not a bug. The panel always prints both numbers
> (today's max and the station normal) so the offset stays visible rather than
> hidden.

Heatwave severity on the live card is scored the way the dataset labels it —
live temperature minus the station's `normal_tmax_c` for this calendar window
(±5 days), mapped to NONE / MILD / MODERATE / SEVERE and GREEN → RED.

## API

| Endpoint | Returns |
|---|---|
| `GET /api/stations` | station catalogue with per-station climatology |
| `GET /api/schema` | Exp-1 attribute taxonomy |
| `GET /api/quality` | nulls, duplicates, IQR outliers, completeness |
| `GET /api/live?location=` | live observation + dataset normals + severity |
| `GET /api/forecast?location=&live_temp=` | harmonic LS projection with 95 % CI |
| `GET /api/timeseries?location=&days=` | daily Tmax/Tmin/mean/normal series |
| `GET /api/stats?location=&column=` | Exp-3 manual descriptive statistics |
| `GET /api/distribution?location=&column=&classes=` | grouped frequency + KDE |
| `GET /api/correlation?location=` | Pearson matrix + manual pairs |
| `GET /api/regression?location=` | SLR vs MLR with MAE/RMSE/R² |
| `GET /api/aggregation?location=` | yearly / zonal / monthly-by-terrain / ranking |
| `GET /api/heatmap?location=&metric=` | month × year matrix |
| `GET /api/categorical?location=` | ordinal encodings + frequency listing |

## Dataset

`data/Climate_final_k.csv` — **65,760 daily records × 35 attributes across 30
AWS stations**, 2019-01-01 → 2024-12-31 (~14 MB, committed to the repo). No
nulls, no duplicate rows; the Exp-2 pipeline trims it to **58,852 rows** under
sequential 1.5 × IQR filtering, matching the experiment report exactly.

Stations span all five zones and three terrain types — from Jaisalmer and
Bikaner in the desert plains to Gangtok, Manali, Darjeeling and Ooty in the
hills, and Kochi, Puri, Alibaug and Visakhapatnam on the coast. Every panel,
the station selector and the geospatial grid read straight from this file, so
replacing it is the only step needed to point the dashboard at new data.
