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
| **Exp 2** — data handling | `info` / `isnull` / `duplicated`, mean–mode imputation, 1.5 × IQR outlier trimming, groupby suite, correlation heatmap, station scatter | *Pipeline & Anomaly Engine* strip, *Climate Density Matrix*, *Geospatial Station Grid*, *Aggregation* chart, *Location League Table*, outlier ledger |
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

## Locations

The selector carries **234 locations**, grouped one `<optgroup>` per state —
the state's own reference point first, then its main cities:

- **30 AWS stations** — your `Climate_final_k.csv` archive (their own group).
- **36 states and union territories** — every Indian state/UT, at its capital.
- **168 cities** — the main cities of each state (Maharashtra: Mumbai, Pune,
  Nagpur, Nashik, Navi Mumbai, Chhatrapati Sambhajinagar, Solapur, Kolhapur;
  Uttar Pradesh: Lucknow, Kanpur, Varanasi, Agra, Prayagraj, Ghaziabad, Noida,
  Meerut, Bareilly; and so on).

Every one of them gets the complete dashboard — live conditions, time series,
forecast, distribution, correlation, regression, heatmap and aggregation.

City coordinates are not hand-typed. [backend/cities.py](backend/cities.py)
resolves each name through the Open-Meteo geocoding API once and pins the
result in `data/cache/cities.json`, checking the returned `admin1` against the
state the city is listed under. That check earned its keep: Panaji resolved
into Gujarat and Dharamshala into Uttar Pradesh, and four names returned no
Indian match — all six are now pinned by hand in `MANUAL_COORDS` with verified
coordinates. Terrain is derived per place, so Pune reads as plains while
Mumbai, in the same state, reads as coastal.

States have no rows in the CSV, so [backend/regions.py](backend/regions.py)
pulls their real 2019–2024 daily history from the Open-Meteo reanalysis and
reshapes it into *exactly* the dataset schema: same column names, the same
category bands (`Cool`/`Warm`/`Hot`/`Very Hot` at 25/35/40 °C, wind at
6/12/20 km/h, pressure at 1000/1013 hPa, all read off your CSV), the same
seasons, day-of-year normals computed over a ±7-day window, and departure /
heatwave / alert fields derived from those normals with the IMD rule
(departure ≥ 4.5 °C on a day already hot for the terrain).

Because the frame matches, `analysis.py` runs unchanged — regression,
correlation, distribution, aggregation, heatmap and the harmonic forecast are
computed by the same Exp 1–5 code for every source. A badge in the header
always says which archive is behind the numbers on screen, and the geospatial
grid draws AWS stations as circles, states as diamonds and cities as squares,
with an All / Stations / States / Cities filter so 204 archive points stay
readable.

The **Geospatial Field Maps** draw six live surface variables as continuous,
contoured maps — **temperature, humidity, rain, wind, gust and visibility** —
each in its own colour ramp. [backend/fieldgrid.py](backend/fieldgrid.py)
samples a regular 22 × 22 grid over the selected location's state (or 20 × 20
over all of India) from the Open-Meteo forecast API, 90 points per request; the
browser upsamples the lattice bilinearly onto a canvas, traces contour lines
with marching squares, and lays place names over the surface with collision
avoidance. Switching variables re-colours the same grid without refetching.
Rain is the previous full day's total, since the current hour is dry almost
everywhere and would draw a flat map.

A whole grid costs several hundred weighted API units and shares a per-minute
quota with the live reading, so batches are paced and retried, and the map is
only sampled *after* the live card has loaded — the field map can never starve
the core panel.

The **Location League Table** ranks every location over its full record —
mean and peak temperature, humidity, wind, heatwave days, elevation, and a
Jan–Dec sparkline of mean Tmax. Click any header to sort, type to filter by
name / state / zone, switch scope between stations, states and cities, and
click a row to load that location's dashboard.

The top taskbar tracks scroll position: as you move down the page the active
tab advances section by section, and the bar scrolls horizontally to keep the
current tab visible. Clicking a tab holds its highlight until the smooth scroll
settles, so it does not flicker through the sections on the way.

One useful side effect: for states, the normals and the live feed come from the
same provider, so departures are internally consistent and severity reads
true — unlike the dataset stations, where the archive's normals run cooler than
the live provider (see the note above).

Archives are cached under `data/cache/regions/` (gitignored, ~18 MB) and in CI
via `actions/cache`, so only the first build pays the fetch cost.

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
