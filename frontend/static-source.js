/* =========================================================================
   static-source.js
   -----------------
   Lets the dashboard run with no Python server behind it (GitHub Pages).

   In static mode the analytical endpoints are served from JSON that
   scripts/build_static.py pre-computed with the same Exp 1-5 code, and the
   live observation is fetched straight from Open-Meteo in the browser -
   a port of backend/live_weather.py's normalisation plus the severity
   scoring from backend/app.py.

   When window.AETHERCAST_STATIC is not set this file does nothing and
   app.js talks to the FastAPI service as usual.
   ========================================================================= */

(function () {
  if (!window.AETHERCAST_STATIC) return;

  const BASE = (window.AETHERCAST_DATA_BASE || "data").replace(/\/$/, "");
  const FORECAST_URL = "https://api.open-meteo.com/v1/forecast";
  const AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality";

  const WMO_CODES = {
    0: ["Clear sky", "clear"], 1: ["Mainly clear", "clear"], 2: ["Partly cloudy", "partly"],
    3: ["Overcast", "cloudy"], 45: ["Fog", "fog"], 48: ["Depositing rime fog", "fog"],
    51: ["Light drizzle", "drizzle"], 53: ["Moderate drizzle", "drizzle"],
    55: ["Dense drizzle", "drizzle"], 61: ["Slight rain", "rain"],
    63: ["Moderate rain", "rain"], 65: ["Heavy rain", "rain"],
    66: ["Freezing rain", "rain"], 67: ["Heavy freezing rain", "rain"],
    71: ["Slight snow", "snow"], 73: ["Moderate snow", "snow"], 75: ["Heavy snow", "snow"],
    77: ["Snow grains", "snow"], 80: ["Rain showers", "rain"],
    81: ["Moderate rain showers", "rain"], 82: ["Violent rain showers", "rain"],
    85: ["Snow showers", "snow"], 86: ["Heavy snow showers", "snow"],
    95: ["Thunderstorm", "storm"], 96: ["Thunderstorm with hail", "storm"],
    99: ["Thunderstorm with heavy hail", "storm"],
  };
  const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                   "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];

  const cache = new Map();
  let stationIndex = null;                 // location -> station record (with .id)

  async function json(file) {
    if (cache.has(file)) return cache.get(file);
    const res = await fetch(`${BASE}/${file}`);
    if (!res.ok) throw new Error(`missing static file: ${file}`);
    const data = await res.json();
    cache.set(file, data);
    return data;
  }

  async function stationFor(location) {
    if (!stationIndex) {
      const { stations } = await json("stations.json");
      stationIndex = new Map(stations.map((s) => [s.location, s]));
    }
    if (location && location !== "ALL" && stationIndex.has(location)) return stationIndex.get(location);
    return stationIndex.values().next().value;
  }

  const compassPoint = (deg) => COMPASS[Math.round((((deg % 360) + 360) % 360) / 22.5) % 16];

  function dewPoint(tempC, rhPct) {
    const a = 17.27, b = 237.7;
    const rh = Math.min(Math.max(rhPct, 1), 100);
    const alpha = (a * tempC) / (b + tempC) + Math.log(rh / 100);
    return Math.round(((b * alpha) / (a - alpha)) * 10) / 10;
  }

  /* ------------------------------------------------- live from Open-Meteo */
  async function fetchLive(station) {
    const q = new URLSearchParams({
      latitude: station.latitude, longitude: station.longitude,
      current: ["temperature_2m", "relative_humidity_2m", "apparent_temperature", "is_day",
                "precipitation", "weather_code", "cloud_cover", "pressure_msl",
                "surface_pressure", "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"].join(","),
      hourly: ["temperature_2m", "relative_humidity_2m", "dew_point_2m",
               "precipitation_probability", "precipitation", "pressure_msl",
               "wind_speed_10m", "visibility"].join(","),
      daily: ["temperature_2m_max", "temperature_2m_min", "precipitation_sum",
              "precipitation_probability_max", "wind_speed_10m_max", "uv_index_max",
              "sunrise", "sunset", "daylight_duration"].join(","),
      timezone: "auto", forecast_days: 7, past_days: 2, wind_speed_unit: "kmh",
    });

    const [data, aqRes] = await Promise.all([
      fetch(`${FORECAST_URL}?${q}`).then((r) => r.json()),
      fetch(`${AIR_QUALITY_URL}?` + new URLSearchParams({
        latitude: station.latitude, longitude: station.longitude,
        current: "pm10,pm2_5,european_aqi,us_aqi,uv_index", timezone: "auto",
      })).then((r) => r.json()).catch(() => ({})),
    ]);

    const cur = data.current || {}, hourly = data.hourly || {}, daily = data.daily || {};
    const aq = aqRes.current || {};

    const times = hourly.time || [];
    let nowIndex = times.findIndex((t) => t.slice(0, 13) === (cur.time || "").slice(0, 13));
    if (nowIndex < 0) nowIndex = Math.floor(times.length / 2);

    const press = hourly.pressure_msl || [];
    const trend = nowIndex >= 3 && press[nowIndex] != null && press[nowIndex - 3] != null
      ? Math.round((press[nowIndex] - press[nowIndex - 3]) * 10) / 10 : null;

    const probs = hourly.precipitation_probability || [];
    let peakProb = null, peakTime = null;
    for (let i = nowIndex; i < Math.min(nowIndex + 24, probs.length); i++) {
      if (probs[i] != null && (peakProb === null || probs[i] > peakProb)) {
        peakProb = probs[i]; peakTime = times[i];
      }
    }

    const vis = hourly.visibility || [];
    const visibilityKm = vis[nowIndex] != null ? Math.round((vis[nowIndex] / 1000) * 10) / 10 : null;

    const dayTimes = daily.time || [];
    let dayIndex = dayTimes.indexOf((cur.time || "").slice(0, 10));
    if (dayIndex < 0) dayIndex = Math.min(2, dayTimes.length - 1);

    const [desc, icon] = WMO_CODES[cur.weather_code] || ["Unknown", "clear"];
    const lo = Math.max(nowIndex - 12, 0), hi = nowIndex + 13;

    return {
      station: station.station,
      provider: "Open-Meteo (browser)",
      observed_at: cur.time,
      timezone: data.timezone,
      latitude: station.latitude,
      longitude: station.longitude,
      elevation_m: data.elevation,
      temperature_c: cur.temperature_2m,
      apparent_c: cur.apparent_temperature,
      humidity_pct: cur.relative_humidity_2m,
      dew_point_c: cur.temperature_2m != null && cur.relative_humidity_2m != null
        ? dewPoint(cur.temperature_2m, cur.relative_humidity_2m) : null,
      pressure_hpa: cur.pressure_msl,
      pressure_trend_3h: trend,
      wind_speed_kmph: cur.wind_speed_10m,
      wind_gust_kmph: cur.wind_gusts_10m,
      wind_direction_deg: cur.wind_direction_10m || 0,
      wind_compass: compassPoint(cur.wind_direction_10m || 0),
      cloud_cover_pct: cur.cloud_cover,
      precipitation_mm: cur.precipitation,
      precip_probability_peak_pct: peakProb,
      precip_probability_peak_time: peakTime,
      visibility_km: visibilityKm,
      is_day: !!cur.is_day,
      condition: desc,
      icon,
      weather_code: cur.weather_code,
      air_quality: {
        pm2_5: aq.pm2_5, pm10: aq.pm10, european_aqi: aq.european_aqi,
        us_aqi: aq.us_aqi, uv_index: aq.uv_index,
      },
      today: {
        tmax_c: (daily.temperature_2m_max || [])[dayIndex],
        tmin_c: (daily.temperature_2m_min || [])[dayIndex],
        precip_sum_mm: (daily.precipitation_sum || [])[dayIndex],
        uv_index_max: (daily.uv_index_max || [])[dayIndex],
        sunrise: (daily.sunrise || [])[dayIndex],
        sunset: (daily.sunset || [])[dayIndex],
        daylight_seconds: (daily.daylight_duration || [])[dayIndex],
      },
      hourly: {
        time: times.slice(lo, hi),
        temperature: (hourly.temperature_2m || []).slice(lo, hi),
        dew_point: (hourly.dew_point_2m || []).slice(lo, hi),
        humidity: (hourly.relative_humidity_2m || []).slice(lo, hi),
        precip_probability: probs.slice(lo, hi),
        now_offset: Math.min(12, nowIndex),
      },
      daily: {
        time: dayTimes, tmax: daily.temperature_2m_max || [], tmin: daily.temperature_2m_min || [],
        precip: daily.precipitation_sum || [],
        precip_probability: daily.precipitation_probability_max || [],
        wind_max: daily.wind_speed_10m_max || [],
      },
    };
  }

  const dayOfYear = (d = new Date()) =>
    Math.floor((d - new Date(d.getFullYear(), 0, 0)) / 86400000);

  /* severity scoring - mirrors backend/app.py */
  function score(reference, normalTmax) {
    if (reference == null) return { departure: null, severity: "NONE", alert: "GREEN" };
    const departure = Math.round((reference - normalTmax) * 10) / 10;
    if (departure >= 6.5) return { departure, severity: "SEVERE", alert: "RED" };
    if (departure >= 4.5) return { departure, severity: "MODERATE", alert: "ORANGE" };
    if (departure >= 3.0) return { departure, severity: "MILD", alert: "YELLOW" };
    return { departure, severity: "NONE", alert: "GREEN" };
  }

  /* Exp-5 harmonic model, evaluated in the browser from stored coefficients */
  function evaluateForecast(model, liveTemp) {
    const b = model.coefficients;
    const value = (d) => {
      const w = (2 * Math.PI * d) / 365.25;
      return b[0] + b[1] * Math.sin(w) + b[2] * Math.cos(w)
                  + b[3] * Math.sin(2 * w) + b[4] * Math.cos(2 * w);
    };
    const today = dayOfYear();
    const days = [], pred = [];
    for (let k = -7; k <= 7; k++) {
      const d = ((today + k - 1) % 366 + 366) % 366 + 1;
      days.push(d); pred.push(value(d));
    }
    const offset = liveTemp != null ? liveTemp - pred[7] : 0;
    const sd = model.residual_sd;
    const round = (v) => Math.round(v * 100) / 100;
    return {
      coefficients: b,
      day_of_year: days,
      predicted: pred.map((v) => round(v + offset)),
      ci_upper: pred.map((v) => round(v + offset + 1.96 * sd)),
      ci_lower: pred.map((v) => round(v + offset - 1.96 * sd)),
      rmse: model.rmse, r2: model.r2, residual_sd: sd,
      anchor_offset: round(offset),
    };
  }

  /* ------------------------------------------------------------ dispatch */
  window.StaticSource = {
    async get(path, params = {}) {
      const location = params.location;

      switch (path) {
        case "/api/stations": return json("stations.json");
        case "/api/schema":   return json("schema.json");
        case "/api/quality":  return json("quality.json");

        case "/api/live": {
          const station = await stationFor(location);
          const [observation, normalsByDay] = await Promise.all([
            fetchLive(station), json(`normals/${station.id}.json`),
          ]);
          const normals = normalsByDay[String(dayOfYear())] || normalsByDay["1"];
          const reference = observation.today.tmax_c ?? observation.temperature_c;
          const { departure, severity, alert } = score(reference, normals.normal_tmax);
          return {
            station, observation, normals,
            departure_reference_c: reference,
            departure_tmax_c: departure,
            severity, alert_color: alert,
          };
        }

        case "/api/forecast": {
          const station = await stationFor(location);
          const model = await json(`forecast/${station.id}.json`);
          return evaluateForecast(model, params.live_temp != null ? Number(params.live_temp) : null);
        }

        case "/api/timeseries":  return json(`timeseries/${(await stationFor(location)).id}.json`);
        case "/api/correlation": return json(`correlation/${(await stationFor(location)).id}.json`);
        case "/api/regression":  return json(`regression/${(await stationFor(location)).id}.json`);
        case "/api/aggregation": return json(`aggregation/${(await stationFor(location)).id}.json`);
        case "/api/categorical": return json(`categorical/${(await stationFor(location)).id}.json`);
        case "/api/stats":
          return json(`stats/${(await stationFor(location)).id}__${params.column || "tmax_c"}.json`);
        case "/api/distribution":
          return json(`distribution/${(await stationFor(location)).id}__${params.column || "tmax_c"}.json`);
        case "/api/heatmap":
          return json(`heatmap/${(await stationFor(location)).id}__${params.metric || "tmax_c"}.json`);

        default:
          throw new Error(`no static handler for ${path}`);
      }
    },
  };
})();
