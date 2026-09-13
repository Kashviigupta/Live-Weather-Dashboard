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
│   └── app.js                    # data binding + charts
└── requirements.txt
```

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

> **Reading the departure badge.** The archive's `normal_tmax_c` for these
> stations runs several degrees cooler than what the live provider reports for
> the same calendar window (e.g. mid-September Delhi: archive normal ≈ 25.8 °C,
> live day max ≈ 31.9 °C). That is a property of the dataset, not a bug — so
> live departures and severity flags read high. The panel always prints both
> numbers (live max and station normal) so the offset is visible rather than
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

## Dataset note

`data/Climate_final_k.csv` currently holds **9,025 rows across 5 stations**
(2019-01-01 → 2024-12-31) — the portion of the file recovered from the chat
attachment, which was truncated at 2 MB. Drop the full 65,760-row
`Climate_final_k.csv` into `data/` (same filename) and restart; every panel,
station list and statistic reads from it directly with no code change.
