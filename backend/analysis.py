"""
analysis.py
-----------
The FDS experiment code (Exp 1 - Exp 5) refactored into reusable functions that
the dashboard API calls.  The statistical procedures are kept exactly as they
were written in the experiments (manual mean/median/mode/variance/IQR, manual
Pearson r, least-squares simple regression, normal-equation multiple
regression); only the matplotlib calls were replaced by JSON-friendly returns so
the numbers can be drawn in the browser instead.

Dataset: Climate_final_k.csv  (India daily AWS climate records)
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

import regions

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "Climate_final_k.csv"

MONTH_ORDER = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]
SEASON_ORDER = ["Winter", "Pre-Monsoon/Summer", "Monsoon", "Post-Monsoon"]

# Exp-2: correlation heatmap column set
CORR_COLS = ["tmax_c", "tmin_c", "mean_temp_c", "diurnal_temp_range_c",
             "rh_max_pct", "rh_min_pct", "rh_mean_pct", "wind_speed_kmph",
             "pressure_hpa", "elevation_m", "departure_tmax_c", "departure_tmin_c"]

# Exp-2: distribution plot column set
DIST_COLS = ["tmax_c", "tmin_c", "mean_temp_c", "rh_mean_pct",
             "wind_speed_kmph", "pressure_hpa", "diurnal_temp_range_c",
             "departure_tmax_c"]

# Exp-2 step 13: columns excluded from IQR outlier trimming
EXCLUDE_FROM_OUTLIERS = ["heatwave_flag", "warm_night_flag", "data_corrected_flag",
                         "year", "month", "day", "day_of_year",
                         "elevation_m", "latitude", "longitude"]


# ---------------------------------------------------------------- Exp 1
# Attribute classification table (Nominal / Ordinal / Interval / Ratio)
ATTRIBUTE_TAXONOMY = [
    ("location", "Categorical", "Discrete", "Nominal", "Station names - labels with no inherent order."),
    ("zone", "Categorical", "Discrete", "Nominal", "Region names (North, South, ...) - unordered labels."),
    ("terrain_type", "Categorical", "Discrete", "Nominal", "PLAINS / COASTAL / HILLY - classification labels."),
    ("season", "Categorical", "Discrete", "Nominal", "Winter / Monsoon / etc - distinct categories."),
    ("heatwave_flag", "Categorical", "Discrete", "Nominal", "Binary 0/1 presence indicator, not a quantity."),
    ("warm_night_flag", "Categorical", "Discrete", "Nominal", "Binary categorical marker."),
    ("severity", "Categorical", "Discrete", "Ordinal", "NONE < MODERATE < SEVERE - ranked, gaps unmeasurable."),
    ("alert_color", "Categorical", "Discrete", "Ordinal", "GREEN < YELLOW < ORANGE < RED - increasing alert level."),
    ("tmax_category", "Categorical", "Discrete", "Ordinal", "Cool < Warm < Hot < Very Hot - ordered bands."),
    ("wind_category", "Categorical", "Discrete", "Ordinal", "Calm < Light < Moderate < Strong - ordered bands."),
    ("pressure_category", "Categorical", "Discrete", "Ordinal", "Low < Normal < High - ordered bands."),
    ("date", "Numerical", "Discrete", "Interval", "Calendar date - equal units, arbitrary day 0."),
    ("year", "Numerical", "Discrete", "Interval", "Calendar year - equal spacing, no true zero."),
    ("latitude", "Numerical", "Continuous", "Interval", "Degrees - 0 deg is the equator, an arbitrary reference."),
    ("longitude", "Numerical", "Continuous", "Interval", "Arbitrary zero at the Prime Meridian."),
    ("tmax_c", "Numerical", "Continuous", "Interval", "Temperature in C - 0 C is arbitrary."),
    ("tmin_c", "Numerical", "Continuous", "Interval", "Same reasoning as tmax_c."),
    ("mean_temp_c", "Numerical", "Continuous", "Interval", "Derived average temperature."),
    ("elevation_m", "Numerical", "Continuous", "Ratio", "Metres above sea level - true zero, ratios valid."),
    ("rh_max_pct", "Numerical", "Continuous", "Ratio", "Percentage - 0% is true absence of humidity."),
    ("wind_speed_kmph", "Numerical", "Continuous", "Ratio", "0 km/h means no wind; 20 is twice 10."),
    ("pressure_hpa", "Numerical", "Continuous", "Ratio", "True physical zero, valid ratios."),
    ("day_of_year", "Numerical", "Discrete", "Ratio", "Day count 1-366 from a true zero reference."),
]

# Ordinal encodings (Exp-1 ordering -> label encoding used by the UI)
SEVERITY_ENCODING = {"NONE": 0, "MODERATE": 1, "SEVERE": 2}
ALERT_ENCODING = {"GREEN": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3}
TMAX_CAT_ENCODING = {"Cool": 0, "Warm": 1, "Hot": 2, "Very Hot": 3}
WIND_CAT_ENCODING = {"Calm": 0, "Light": 1, "Moderate": 2, "Strong": 3}
PRESSURE_CAT_ENCODING = {"Low": 0, "Normal": 1, "High": 2}


# ---------------------------------------------------------------- Exp 2
@lru_cache(maxsize=1)
def load_data() -> pd.DataFrame:
    """Exp-2 step 2: load the CSV and set a sensible categorical ordering."""
    df = pd.read_csv(DATA_PATH)

    df["month_name"] = pd.Categorical(df["month_name"], categories=MONTH_ORDER, ordered=True)
    df["season"] = pd.Categorical(df["season"], categories=SEASON_ORDER, ordered=True)
    df["date_parsed"] = pd.to_datetime(df["date"], format="%d-%m-%Y", errors="coerce")

    # Exp-2 step 10: imputation (mode for objects, mean for numerics)
    for col in df.columns:
        if df[col].isna().any():
            if df[col].dtype == "object":
                df[col] = df[col].fillna(df[col].mode()[0])
            elif pd.api.types.is_numeric_dtype(df[col]):
                df[col] = df[col].fillna(df[col].mean())

    df["station"] = df["location"].str.split(",").str[0].str.strip()
    return df


def data_quality_report() -> dict:
    """Exp-2 steps 4, 9, 11, 13: nulls, duplicates, IQR outliers, shape change."""
    df = load_data()
    raw = pd.read_csv(DATA_PATH)

    nulls = {c: int(v) for c, v in raw.isnull().sum().items() if v > 0}
    numeric_cols = df.select_dtypes(include="number").columns
    cols_to_check = [c for c in numeric_cols if c not in EXCLUDE_FROM_OUTLIERS]

    outliers = []
    trimmed = df
    for col in cols_to_check:
        # bounds recomputed on the progressively trimmed frame, exactly as the
        # Exp-2 loop does (`df = df[(df[i] > LB) & (df[i] <= UB)]`)
        q1, q3 = trimmed[col].quantile(0.25), trimmed[col].quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lb, ub = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        n_out = int(((trimmed[col] < lb) | (trimmed[col] > ub)).sum())
        if n_out:
            outliers.append({"column": col, "count": n_out,
                             "lower": round(float(lb), 2), "upper": round(float(ub), 2)})
        trimmed = trimmed[(trimmed[col] > lb) & (trimmed[col] <= ub)]

    total_cells = int(raw.shape[0] * raw.shape[1])
    missing_cells = int(raw.isnull().sum().sum())

    return {
        "rows": int(raw.shape[0]),
        "columns": int(raw.shape[1]),
        "rows_after_iqr_trim": int(trimmed.shape[0]),
        "rows_removed": int(df.shape[0] - trimmed.shape[0]),
        "duplicates": int(raw.duplicated().sum()),
        "null_columns": nulls,
        "completeness_pct": round(100 * (1 - missing_cells / total_cells), 2) if total_cells else 100.0,
        "outliers": sorted(outliers, key=lambda d: -d["count"]),
        "outlier_total": int(sum(o["count"] for o in outliers)),
        "corrected_records": int(df["data_corrected_flag"].sum()),
        "date_range": [str(df["date_parsed"].min().date()), str(df["date_parsed"].max().date())],
        "stations": int(df["location"].nunique()),
    }


def station_catalogue() -> list:
    """Exp-2 geospatial view: one row per station with its climatology."""
    df = load_data()
    # Jan-Dec mean Tmax per location, for the league table's sparkline
    monthly = (df.pivot_table(index="location", columns="month", values="tmax_c",
                              aggfunc="mean", observed=True)
                 .reindex(columns=range(1, 13)).round(1))

    grouped = df.groupby("location", observed=True).agg(
        station=("station", "first"),
        state=("state", "first"),
        zone=("zone", "first"),
        terrain_type=("terrain_type", "first"),
        latitude=("latitude", "first"),
        longitude=("longitude", "first"),
        elevation_m=("elevation_m", "first"),
        avg_tmax=("tmax_c", "mean"),
        avg_tmin=("tmin_c", "mean"),
        avg_mean_temp=("mean_temp_c", "mean"),
        avg_rh=("rh_mean_pct", "mean"),
        avg_wind=("wind_speed_kmph", "mean"),
        avg_pressure=("pressure_hpa", "mean"),
        hottest=("tmax_c", "max"),
        coolest=("tmin_c", "min"),
        heatwave_days=("heatwave_flag", "sum"),
        records=("tmax_c", "size"),
    ).reset_index()

    out = []
    for _, r in grouped.iterrows():
        out.append({
            "location": r["location"],
            "id": re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", r["station"].lower())).strip("-"),
            "source": "climate-final-k",
            "kind": "AWS station",
            "station": r["station"],
            "state": r["state"],
            "zone": r["zone"],
            "terrain_type": r["terrain_type"],
            "latitude": float(r["latitude"]),
            "longitude": float(r["longitude"]),
            "elevation_m": int(r["elevation_m"]),
            "avg_tmax": round(float(r["avg_tmax"]), 1),
            "avg_tmin": round(float(r["avg_tmin"]), 1),
            "avg_mean_temp": round(float(r["avg_mean_temp"]), 1),
            "avg_rh": round(float(r["avg_rh"]), 1),
            "avg_wind": round(float(r["avg_wind"]), 1),
            "avg_pressure": round(float(r["avg_pressure"]), 1),
            "hottest": round(float(r["hottest"]), 1),
            "coolest": round(float(r["coolest"]), 1),
            "heatwave_days": int(r["heatwave_days"]),
            "records": int(r["records"]),
            "monthly_tmax": [None if pd.isna(v) else float(v)
                             for v in monthly.loc[r["location"]]],
        })
    return sorted(out, key=lambda d: d["station"])


def _subset(location):
    """
    Rows for one location.

    A dataset station resolves to its slice of Climate_final_k.csv; a
    "region:<id>" key resolves to that state/UT's archive frame, which
    regions.py builds in the same schema.  Everything downstream is identical
    either way, so the experiment code never branches on the source.
    """
    if regions.is_region(location):
        return regions.region_frame(str(location).split(":", 1)[1])

    df = load_data()
    if location and location != "ALL":
        sub = df[df["location"] == location]
        if len(sub):
            return sub
    return df


def data_source(location) -> dict:
    """Provenance for the selected location, surfaced in the UI."""
    if regions.is_region(location):
        return {
            "source": "open-meteo-archive",
            "label": "Open-Meteo reanalysis 2019-2024",
            "detail": "Daily history for the state/UT reference point, reshaped "
                      "into the dataset schema; heatwave flags applied with the "
                      "IMD rule (departure >= 4.5 C on a day already hot for the terrain).",
        }
    return {
        "source": "climate-final-k",
        "label": "Climate_final_k.csv archive",
        "detail": "IMD-style AWS records shipped with the project, 2019-2024.",
    }


# ---------------------------------------------------------------- Exp 3
# Central tendency & variability - computed the manual way (no built-ins)
def mean_manual(data):
    total = 0
    for x in data:
        total += x
    return total / len(data)


def median_manual(data):
    d = sorted(data)
    n = len(d)
    mid = n // 2
    if n % 2 == 0:
        return (d[mid - 1] + d[mid]) / 2
    return d[mid]


def mode_manual(data):
    counts = {}
    for x in data:
        counts[x] = counts.get(x, 0) + 1
    max_count = max(counts.values())
    modes = [k for k, v in counts.items() if v == max_count]
    return modes, max_count


def variance_manual(data):
    m = mean_manual(data)
    total = 0
    for x in data:
        total += (x - m) ** 2
    return total / len(data)


def std_manual(data):
    var = variance_manual(data)
    if var == 0:
        return 0
    guess = var / 2
    for _ in range(50):                      # Newton-Raphson square root
        guess = (guess + var / guess) / 2
    return guess


def percentile_manual(data, p):
    d = sorted(data)
    rank = p * (len(d) - 1)
    lower = int(rank)
    frac = rank - lower
    if lower + 1 < len(d):
        return d[lower] + frac * (d[lower + 1] - d[lower])
    return d[lower]


def iqr_manual(data):
    q1 = percentile_manual(data, 0.25)
    q3 = percentile_manual(data, 0.75)
    return q3 - q1, q1, q3


def descriptive_stats(column: str = "tmax_c", location=None) -> dict:
    """Exp-3: full descriptive report for one attribute, manual procedures."""
    df = _subset(location)
    data = df[column].dropna().tolist()

    mean_v = mean_manual(data)
    median_v = median_manual(data)
    modes, mode_count = mode_manual([round(x, 1) for x in data])
    var_v = variance_manual(data)
    std_v = std_manual(data)
    iqr_v, q1, q3 = iqr_manual(data)
    lower, upper = q1 - 1.5 * iqr_v, q3 + 1.5 * iqr_v
    outliers = [x for x in data if x < lower or x > upper]

    # skewness & kurtosis (moment based) for the distribution panel
    arr = np.asarray(data, dtype=float)
    sd = arr.std()
    skew = float(((arr - arr.mean()) ** 3).mean() / sd ** 3) if sd else 0.0
    kurt = float(((arr - arr.mean()) ** 4).mean() / sd ** 4) if sd else 0.0

    return {
        "column": column,
        "n": len(data),
        "mean": round(mean_v, 2),
        "median": round(median_v, 2),
        "mode": round(modes[0], 2),
        "mode_frequency": mode_count,
        "min": round(min(data), 2),
        "max": round(max(data), 2),
        "range": round(max(data) - min(data), 2),
        "variance": round(var_v, 2),
        "std": round(std_v, 2),
        "cv_pct": round(100 * std_v / mean_v, 2) if mean_v else None,
        "q1": round(q1, 2),
        "q3": round(q3, 2),
        "iqr": round(iqr_v, 2),
        "p25": round(percentile_manual(data, 0.25), 2),
        "p50": round(percentile_manual(data, 0.50), 2),
        "p75": round(percentile_manual(data, 0.75), 2),
        "p99": round(percentile_manual(data, 0.99), 2),
        "whisker_low": round(max(min(data), lower), 2),
        "whisker_high": round(min(max(data), upper), 2),
        "outlier_count": len(outliers),
        "skewness": round(skew, 3),
        "kurtosis": round(kurt, 3),
    }


def grouped_frequency(column: str = "tmax_c", n_classes: int = 10, location=None) -> dict:
    """Exp-3 part 3: grouped-data frequency table + grouped statistics."""
    df = _subset(location)
    values = df[column].dropna().tolist()

    min_v, max_v = min(values), max(values)
    width = math.ceil(((max_v - min_v) / n_classes) * 10) / 10
    boundaries = [round(min_v + i * width, 1) for i in range(n_classes + 1)]
    boundaries[-1] = max(boundaries[-1], max_v + 0.1)

    freq = [0] * n_classes
    for x in values:
        for i in range(n_classes):
            lo, hi = boundaries[i], boundaries[i + 1]
            if (i < n_classes - 1 and lo <= x < hi) or (i == n_classes - 1 and lo <= x <= hi):
                freq[i] += 1
                break

    midpoints = [round((boundaries[i] + boundaries[i + 1]) / 2, 2) for i in range(n_classes)]
    n = sum(freq)

    grouped_mean = sum(f * m for f, m in zip(freq, midpoints)) / n
    grouped_var = sum(f * (m - grouped_mean) ** 2 for f, m in zip(freq, midpoints)) / n
    grouped_std = grouped_var ** 0.5

    cum, median_class = 0, 0
    for i, f in enumerate(freq):
        cum += f
        if cum >= n / 2:
            median_class = i
            break
    cf_before = sum(freq[:median_class])
    grouped_median = boundaries[median_class] + ((n / 2 - cf_before) / freq[median_class]) * width

    modal_class = freq.index(max(freq))
    f1 = freq[modal_class]
    f0 = freq[modal_class - 1] if modal_class > 0 else 0
    f2 = freq[modal_class + 1] if modal_class < n_classes - 1 else 0
    denom = (f1 - f0) + (f1 - f2)
    grouped_mode = boundaries[modal_class] + ((f1 - f0) / denom) * width if denom else midpoints[modal_class]

    # Gaussian KDE overlay (Exp-2 histplot(kde=True), drawn as a polyline)
    arr = np.asarray(values, dtype=float)
    bw = 1.06 * arr.std() * len(arr) ** (-1 / 5) or 1.0
    grid = np.linspace(min_v, max_v, 80)
    dens = np.exp(-0.5 * ((grid[:, None] - arr[None, :]) / bw) ** 2).sum(axis=1)
    dens = dens / (len(arr) * bw * math.sqrt(2 * math.pi))
    scale = max(freq) / dens.max() if dens.max() else 1

    return {
        "column": column,
        "classes": [f"{boundaries[i]}-{boundaries[i + 1]}" for i in range(n_classes)],
        "midpoints": midpoints,
        "frequency": freq,
        "kde_x": [round(float(x), 2) for x in grid],
        "kde_y": [round(float(y * scale), 2) for y in dens],
        "grouped": {
            "n": n,
            "mean": round(grouped_mean, 2),
            "median": round(grouped_median, 2),
            "mode": round(grouped_mode, 2),
            "variance": round(grouped_var, 2),
            "std": round(grouped_std, 2),
        },
        "ungrouped": {
            "mean": round(float(np.mean(values)), 2),
            "median": round(float(np.median(values)), 2),
            "variance": round(float(np.var(values)), 2),
            "std": round(float(np.std(values)), 2),
        },
    }


# ---------------------------------------------------------------- Exp 4
def correlation_coefficient(x, y):
    """Exp-4: Pearson r from first principles (no built-in)."""
    n = len(x)
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    sum_sq_x = sum((x[i] - mean_x) ** 2 for i in range(n))
    sum_sq_y = sum((y[i] - mean_y) ** 2 for i in range(n))
    denominator = math.sqrt(sum_sq_x * sum_sq_y)
    if denominator == 0:
        return 0
    return numerator / denominator


def correlation_matrix(location=None, cols=None) -> dict:
    """Exp-2 heatmap + Exp-4 manual r over the weather variables."""
    df = _subset(location)
    cols = [c for c in (cols or CORR_COLS) if c in df.columns]
    # a single-station subset has constant elevation/lat/lon -> undefined r
    cols = [c for c in cols if df[c].nunique() > 1]

    matrix = df[cols].corr(numeric_only=True).round(2)
    values = [[None if pd.isna(v) else float(v) for v in row] for row in matrix.values]
    labels = [c.replace("_c", "").replace("_pct", "").replace("_kmph", "")
               .replace("_hpa", "").replace("_m", "").upper()[:9] for c in cols]

    pairs = [
        ("tmax_c", "mean_temp_c", "Expected positive"),
        ("tmax_c", "rh_max_pct", "Expected negative"),
        ("wind_speed_kmph", "pressure_hpa", "Expected none"),
    ]
    manual = []
    sample = df.sample(min(len(df), 4000), random_state=42)
    for a, b, note in pairs:
        x, y = sample[a].tolist(), sample[b].tolist()
        manual.append({
            "x": a, "y": b, "note": note,
            "r": round(correlation_coefficient(x, y), 4),
            "points": [[round(float(xi), 1), round(float(yi), 1)]
                       for xi, yi in zip(x[:900], y[:900])],
        })

    return {
        "columns": cols,
        "labels": labels,
        "matrix": values,
        "manual_pairs": manual,
    }


# ---------------------------------------------------------------- Exp 5
def simple_linear_regression(x, y):
    """Exp-5: least squares w0, w1."""
    n = len(x)
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    num = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    den = sum((x[i] - mean_x) ** 2 for i in range(n))
    w1 = num / den
    w0 = mean_y - w1 * mean_x
    return w0, w1


def multiple_linear_regression(X, y):
    """Exp-5: normal equation  b = (X^T X)^-1 X^T y."""
    n = X.shape[0]
    X_design = np.hstack([np.ones((n, 1)), X])
    XT = X_design.T
    return np.linalg.inv(XT @ X_design) @ (XT @ y)


def regression_report(location=None) -> dict:
    """Exp-5: SLR vs MLR imputation of tmax_c, with MAE / RMSE comparison."""
    df = _subset(location)

    # --- Simple linear regression: tmax_c ~ mean_temp_c
    target, predictor = "tmax_c", "mean_temp_c"
    data = df[[predictor, target]].copy().reset_index(drop=True)

    rng = np.random.default_rng(42)
    n_missing = max(1, int(0.10 * len(data)))
    missing_idx = rng.choice(data.index.to_numpy(), size=n_missing, replace=False)
    data_missing = data.copy()
    data_missing.loc[missing_idx, target] = np.nan

    train = data_missing.dropna()
    w0, w1 = simple_linear_regression(train[predictor].tolist(), train[target].tolist())

    predicted_slr = w0 + w1 * data_missing.loc[missing_idx, predictor]
    actual = data.loc[missing_idx, target]
    mae_slr = float(np.mean(np.abs(actual - predicted_slr)))
    rmse_slr = float(np.sqrt(np.mean((actual - predicted_slr) ** 2)))
    ss_res = float(((actual - predicted_slr) ** 2).sum())
    ss_tot = float(((actual - actual.mean()) ** 2).sum())
    r2_slr = 1 - ss_res / ss_tot if ss_tot else 0.0

    x_line = np.linspace(train[predictor].min(), train[predictor].max(), 40)
    y_line = w0 + w1 * x_line
    scatter = train.sample(min(len(train), 700), random_state=42)

    # --- Multiple linear regression: tmax_c ~ mean_temp + rh_max + wind
    mlr_cols = ["mean_temp_c", "rh_max_pct", "wind_speed_kmph"]
    data_mlr = df[mlr_cols + [target]].copy().reset_index(drop=True)
    idx_mlr = rng.choice(data_mlr.index.to_numpy(),
                         size=max(1, int(0.10 * len(data_mlr))), replace=False)
    mlr_missing = data_mlr.copy()
    mlr_missing.loc[idx_mlr, target] = np.nan
    train_mlr = mlr_missing.dropna()

    b = multiple_linear_regression(train_mlr[mlr_cols].values.astype(float),
                                   train_mlr[target].values.astype(float))
    X_missing = data_mlr.loc[idx_mlr, mlr_cols].values.astype(float)
    predicted_mlr = np.hstack([np.ones((len(X_missing), 1)), X_missing]) @ b
    actual_mlr = data_mlr.loc[idx_mlr, target].values

    mae_mlr = float(np.mean(np.abs(actual_mlr - predicted_mlr)))
    rmse_mlr = float(np.sqrt(np.mean((actual_mlr - predicted_mlr) ** 2)))
    ss_res_m = float(((actual_mlr - predicted_mlr) ** 2).sum())
    ss_tot_m = float(((actual_mlr - actual_mlr.mean()) ** 2).sum())
    r2_mlr = 1 - ss_res_m / ss_tot_m if ss_tot_m else 0.0

    keep = slice(0, 600)
    return {
        "slr": {
            "target": target,
            "predictor": predictor,
            "w0": round(w0, 4),
            "w1": round(w1, 4),
            "equation": f"{target} = {w0:.4f} + {w1:.4f} * {predictor}",
            "mae": round(mae_slr, 4),
            "rmse": round(rmse_slr, 4),
            "r2": round(r2_slr, 4),
            "scatter": [[round(float(a), 1), round(float(c), 1)]
                        for a, c in zip(scatter[predictor], scatter[target])],
            "line": [[round(float(a), 2), round(float(c), 2)] for a, c in zip(x_line, y_line)],
        },
        "mlr": {
            "target": target,
            "predictors": mlr_cols,
            "coefficients": [round(float(v), 4) for v in b],
            "equation": f"{target} = {b[0]:.4f} + " + " + ".join(
                f"({b[i + 1]:.4f} * {c})" for i, c in enumerate(mlr_cols)),
            "mae": round(mae_mlr, 4),
            "rmse": round(rmse_mlr, 4),
            "r2": round(r2_mlr, 4),
            "actual_vs_pred": [[round(float(a), 1), round(float(p), 1)]
                               for a, p in zip(actual_mlr[keep], predicted_mlr[keep])],
        },
    }


def forecast_model(location, live_temp=None) -> dict:
    """
    Seasonal (harmonic) least-squares forecast used for the projection ribbon.

    Same normal equation as Exp-5, with sin/cos basis functions of day_of_year
    instead of raw predictors, so the projection follows the station's annual
    cycle.  The live reading, when supplied, shifts the curve to now.
    """
    df = _subset(location)
    doy = df["day_of_year"].values.astype(float)
    y = df["tmax_c"].values.astype(float)

    def basis(d):
        w = 2 * math.pi * d / 365.25
        return np.column_stack([np.sin(w), np.cos(w), np.sin(2 * w), np.cos(2 * w)])

    b = multiple_linear_regression(basis(doy), y)
    fitted = np.hstack([np.ones((len(doy), 1)), basis(doy)]) @ b
    resid_sd = float(np.std(y - fitted))

    today = pd.Timestamp.utcnow().dayofyear
    horizon = (np.arange(today - 7, today + 8) - 1) % 366 + 1
    pred = np.hstack([np.ones((len(horizon), 1)), basis(horizon.astype(float))]) @ b

    offset = (live_temp - pred[7]) if live_temp is not None else 0.0
    pred = pred + offset

    ss_res = float(((y - fitted) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())

    return {
        "coefficients": [round(float(v), 4) for v in b],
        "day_of_year": [int(d) for d in horizon],
        "predicted": [round(float(v), 2) for v in pred],
        "ci_upper": [round(float(v + 1.96 * resid_sd), 2) for v in pred],
        "ci_lower": [round(float(v - 1.96 * resid_sd), 2) for v in pred],
        "rmse": round(float(np.sqrt(((y - fitted) ** 2).mean())), 3),
        "r2": round(1 - ss_res / ss_tot, 4) if ss_tot else 0.0,
        "residual_sd": round(resid_sd, 3),
        "anchor_offset": round(float(offset), 2),
    }


# ---------------------------------------------------- Exp 2: aggregation
def aggregations(location=None) -> dict:
    """Exp-2 groupby set: yearly, zonal, monthly-by-terrain, station ranking."""
    df = load_data()
    sub = _subset(location)

    yearly = sub.groupby("year", observed=True)["tmax_c"].mean().round(2)
    yearly_zone = df.groupby(["year", "zone"], observed=True)["tmax_c"].mean().round(2)
    monthly_terrain = df.groupby(["month_name", "terrain_type"], observed=True)["tmax_c"].mean().round(2)
    station_avg = df.groupby("station", observed=True)["mean_temp_c"].mean().round(2).sort_values()

    years = sorted(df["year"].unique().tolist())
    zones = sorted(df["zone"].unique().tolist())
    terrains = sorted(df["terrain_type"].unique().tolist())

    def pick(series, key):
        try:
            v = series.loc[key]
            return None if pd.isna(v) else float(v)
        except KeyError:
            return None

    season_counts = sub["season"].value_counts().reindex(SEASON_ORDER).fillna(0)
    severity_counts = sub["severity"].value_counts().reindex(["NONE", "MODERATE", "SEVERE"]).fillna(0)
    alert_counts = sub["alert_color"].value_counts().reindex(["GREEN", "YELLOW", "ORANGE", "RED"]).fillna(0)

    # Exp-2 boxplots by terrain, reduced to five-number summaries
    terrain_box = []
    for terrain, g in df.groupby("terrain_type", observed=True):
        terrain_box.append({
            "terrain": terrain,
            "tmax": [round(float(g["tmax_c"].quantile(q)), 1) for q in (0.05, 0.25, 0.5, 0.75, 0.95)],
            "rh": [round(float(g["rh_mean_pct"].quantile(q)), 1) for q in (0.05, 0.25, 0.5, 0.75, 0.95)],
            "wind": [round(float(g["wind_speed_kmph"].quantile(q)), 1) for q in (0.05, 0.25, 0.5, 0.75, 0.95)],
        })

    return {
        "yearly": {"years": [int(y) for y in yearly.index], "tmax": yearly.tolist()},
        "yearly_by_zone": {
            "years": [int(y) for y in years],
            "series": [{"zone": z, "tmax": [pick(yearly_zone, (y, z)) for y in years]} for z in zones],
        },
        "monthly_by_terrain": {
            "months": MONTH_ORDER,
            "series": [{"terrain": t, "tmax": [pick(monthly_terrain, (m, t)) for m in MONTH_ORDER]}
                       for t in terrains],
        },
        "station_ranking": [{"station": s, "mean_temp": float(v)} for s, v in station_avg.items()],
        "season_counts": {k: int(v) for k, v in season_counts.items()},
        "severity_counts": {k: int(v) for k, v in severity_counts.items()},
        "alert_counts": {k: int(v) for k, v in alert_counts.items()},
        "terrain_box": terrain_box,
        "elevation_scatter": [
            {"station": r["station"], "elevation": r["elevation_m"],
             "mean_temp": r["avg_mean_temp"], "terrain": r["terrain_type"]}
            for r in station_catalogue()
        ],
    }


def heatmap_matrix(location=None, metric: str = "tmax_c") -> dict:
    """Exp-2 style month x year matrix (the dashboard's density heatmap)."""
    df = _subset(location)
    pivot = df.pivot_table(index="month_name", columns="year", values=metric,
                           aggfunc="mean", observed=True).round(1)
    pivot = pivot.reindex(MONTH_ORDER)

    values = [[None if pd.isna(v) else float(v) for v in row] for row in pivot.values]
    flat = [v for row in values for v in row if v is not None]

    return {
        "metric": metric,
        "months": MONTH_ORDER,
        "years": [int(c) for c in pivot.columns],
        "values": values,
        "min": round(min(flat), 1) if flat else 0,
        "max": round(max(flat), 1) if flat else 0,
    }


def time_series(location=None, metric: str = "tmax_c", days: int = 365) -> dict:
    """Exp-2 daily Tmax/Tmin series for one station (tail of the record)."""
    df = _subset(location).sort_values("date_parsed").tail(days)
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in df["date_parsed"]],
        "tmax": [round(float(v), 1) for v in df["tmax_c"]],
        "tmin": [round(float(v), 1) for v in df["tmin_c"]],
        "mean": [round(float(v), 1) for v in df["mean_temp_c"]],
        "normal_tmax": [round(float(v), 1) for v in df["normal_tmax_c"]],
        "rh": [round(float(v), 1) for v in df["rh_mean_pct"]],
        "wind": [round(float(v), 1) for v in df["wind_speed_kmph"]],
        "pressure": [round(float(v), 1) for v in df["pressure_hpa"]],
    }


def categorical_encoding(location=None) -> dict:
    """Exp-1 ordinal ordering applied as label encoding + frequency listing."""
    df = _subset(location)
    encodings = {
        "severity": SEVERITY_ENCODING,
        "alert_color": ALERT_ENCODING,
        "tmax_category": TMAX_CAT_ENCODING,
        "wind_category": WIND_CAT_ENCODING,
        "pressure_category": PRESSURE_CAT_ENCODING,
    }
    out = {}
    for col, mapping in encodings.items():
        counts = df[col].value_counts()
        out[col] = [{"label": k, "code": v, "count": int(counts.get(k, 0))}
                    for k, v in mapping.items()]
    out["nominal_counts"] = {
        "terrain_type": {k: int(v) for k, v in df["terrain_type"].value_counts().items()},
        "zone": {k: int(v) for k, v in df["zone"].value_counts().items()},
    }
    return out


def climatology(location, day_of_year: int) -> dict:
    """Station normals around a calendar day - used to score the live reading."""
    df = _subset(location)
    window = df[(df["day_of_year"] - day_of_year).abs() <= 5]
    if window.empty:
        window = df
    return {
        "normal_tmax": round(float(window["normal_tmax_c"].mean()), 1),
        "normal_tmin": round(float(window["normal_tmin_c"].mean()), 1),
        "record_tmax": round(float(window["tmax_c"].max()), 1),
        "record_tmin": round(float(window["tmin_c"].min()), 1),
        "mean_rh": round(float(window["rh_mean_pct"].mean()), 1),
        "mean_wind": round(float(window["wind_speed_kmph"].mean()), 1),
        "mean_pressure": round(float(window["pressure_hpa"].mean()), 1),
        "heatwave_rate_pct": round(100 * float(window["heatwave_flag"].mean()), 1),
        "samples": int(len(window)),
    }
