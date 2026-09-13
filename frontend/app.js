/* =========================================================================
   Aethercast - dashboard frontend
   Talks to the FastAPI service in ../backend and draws the panels.
   Every analytical number on screen comes from the experiment code
   (Exp 1 - Exp 5); the live readings come from the weather provider.
   ========================================================================= */

const API = "";                       // same origin
const REFRESH_MS = { live: 60000, hourly: 300000, daily: 900000 };

const state = {
  station: null,
  stations: [],
  range: "live",
  layer: "temp",
  scope: "all",
  distColumn: "tmax_c",
  heatMetric: "tmax_c",
  timer: null,
  charts: {},
  last: {},
};

/* ------------------------------------------------------------------ utils */
const $ = (id) => document.getElementById(id);

async function api(path, params = {}) {
  // On GitHub Pages there is no FastAPI process: static-source.js answers the
  // same paths from pre-computed JSON and a direct call to the weather API.
  if (window.AETHERCAST_STATIC && window.StaticSource) {
    const t0 = performance.now();
    const json = await window.StaticSource.get(path, params);
    json.__latency = Math.round(performance.now() - t0);
    return json;
  }

  const url = new URL(API + path, window.location.origin);
  Object.entries(params).forEach(([k, v]) => v != null && url.searchParams.set(k, v));
  const t0 = performance.now();
  const res = await fetch(url);
  const ms = Math.round(performance.now() - t0);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  const json = await res.json();
  json.__latency = ms;
  return json;
}

const fmt = (v, d = 1, suffix = "") =>
  v === null || v === undefined || Number.isNaN(v) ? "--" : `${Number(v).toFixed(d)}${suffix}`;

function tempColor(v, min, max) {
  if (v === null || v === undefined) return "#1f3056";
  const t = Math.max(0, Math.min(1, (v - min) / (max - min || 1)));
  const stops = [
    [0.0, [8, 145, 178]],    // cyan-600
    [0.35, [16, 185, 129]],  // emerald
    [0.65, [245, 158, 11]],  // amber
    [1.0, [225, 29, 72]],    // rose
  ];
  let a = stops[0], b = stops[stops.length - 1];
  for (let i = 0; i < stops.length - 1; i++) {
    if (t >= stops[i][0] && t <= stops[i + 1][0]) { a = stops[i]; b = stops[i + 1]; break; }
  }
  const f = (t - a[0]) / ((b[0] - a[0]) || 1);
  const c = a[1].map((ch, i) => Math.round(ch + f * (b[1][i] - ch)));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

function corrColor(r) {
  if (r >= 0.999) return "background:#06b6d4;color:#070a13;font-weight:700";
  const a = Math.min(Math.abs(r), 1);
  return r >= 0
    ? `background:rgba(6,182,212,${0.15 + a * 0.7});color:#e2e8f0`
    : `background:rgba(225,29,72,${0.15 + a * 0.7});color:#ffe4e6`;
}

/* Chart.js shared look. The library is a CDN script, so treat it as optional:
   if it failed to load, every other panel must still render and the controls
   must still work. */
const HAS_CHARTS = typeof Chart !== "undefined";

if (HAS_CHARTS) {
  Chart.defaults.color = "#94a3b8";
  Chart.defaults.font.family = "ui-monospace, SFMono-Regular, Consolas, monospace";
  Chart.defaults.font.size = 10;
  Chart.defaults.plugins.legend.display = false;
  Chart.defaults.maintainAspectRatio = false;
}

const gridStyle = { color: "rgba(31,48,86,0.55)", drawTicks: false };

function drawChart(key, canvasId, config) {
  if (!HAS_CHARTS) return;
  if (state.charts[key]) state.charts[key].destroy();
  state.charts[key] = new Chart($(canvasId).getContext("2d"), config);
}

/* ------------------------------------------------------------ weather icon */
function weatherIconSvg(icon, isDay) {
  const sun = `<circle cx="64" cy="38" r="18" fill="url(#sunGrad)" opacity="0.95"></circle>`;
  const moon = `<path d="M74 30a18 18 0 11-20-12 14 14 0 0020 12z" fill="#cbd5e1" opacity="0.9"></path>`;
  const cloud = `<path d="M28 62a14 14 0 0113-14 18 18 0 0134 4 13 13 0 014 25H32a12 12 0 01-4-15z" fill="url(#cloudGrad)" opacity="0.95"></path>`;
  const rain = [38, 48, 58, 68].map((x) =>
    `<line x1="${x}" y1="78" x2="${x - 4}" y2="86" stroke="#38bdf8" stroke-width="2.5" stroke-linecap="round"></line>`).join("");
  const snow = [40, 52, 64].map((x) =>
    `<circle cx="${x}" cy="82" r="2.6" fill="#e0f2fe"></circle>`).join("");
  const bolt = `<path d="M52 70l-10 16h8l-4 14 16-20h-9l5-10z" fill="#facc15"></path>`;

  let body = isDay ? sun : moon;
  if (["partly", "cloudy", "fog", "drizzle", "rain", "snow", "storm"].includes(icon)) body += cloud;
  if (icon === "rain" || icon === "drizzle") body += rain;
  if (icon === "snow") body += snow;
  if (icon === "storm") body += bolt;

  return `<svg class="w-24 h-24 relative z-10 filter drop-shadow-[0_10px_10px_rgba(0,242,254,0.3)]" viewBox="0 0 100 100">
    <defs>
      <linearGradient id="sunGrad" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#fbbf24"></stop><stop offset="100%" stop-color="#ea580c"></stop>
      </linearGradient>
      <linearGradient id="cloudGrad" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#93c5fd"></stop><stop offset="100%" stop-color="#3b82f6"></stop>
      </linearGradient>
    </defs>${body}</svg>`;
}

/* ------------------------------------------------------------------ live */
function renderLive(data) {
  const obs = data.observation;
  const st = data.station;
  const n = data.normals;
  state.last.live = data;

  const isRegion = st.source === "open-meteo-archive";
  $("stationTitle").classList.remove("skeleton");
  $("stationTitle").textContent = isRegion
    ? `${st.station} (${st.kind})`
    : `Station ${st.station} - ${st.state}`;
  $("stationCoords").textContent =
    `Lat: ${st.latitude.toFixed(4)} | Lon: ${st.longitude.toFixed(4)} | Alt: ${st.elevation_m} m ASL | ${st.terrain_type} / ${st.zone}`;

  const badge = $("sourceBadge");
  const archive = data.archive || {};
  badge.textContent = archive.label || "--";
  badge.title = archive.detail || "";
  badge.className = "text-[10px] px-2 py-0.5 rounded-full font-mono border " + (isRegion
    ? "bg-violet-500/10 text-violet-300 border-violet-500/30"
    : "bg-cyan-500/10 text-cyan-300 border-cyan-500/30");

  $("observedAt").textContent = `ISO 8601: ${(obs.observed_at || "").replace("T", " ")} ${obs.timezone || ""}`;
  $("liveTemp").textContent = fmt(obs.temperature_c, 1);
  $("feelsLike").textContent = fmt(obs.apparent_c, 1, " C");
  $("conditionText").textContent = obs.condition;
  $("weatherIcon").innerHTML = weatherIconSvg(obs.icon, obs.is_day);

  const dep = data.departure_tmax_c;
  const depEl = $("departureBadge");
  depEl.textContent = `Today max ${fmt(data.departure_reference_c, 1)} C = ${dep >= 0 ? "+" : ""}${fmt(dep, 1)} C vs normal (${data.severity})`;
  depEl.className = "font-medium " + (
    data.alert_color === "RED" ? "text-rose-400" :
    data.alert_color === "ORANGE" ? "text-amber-400" :
    data.alert_color === "YELLOW" ? "text-yellow-300" : "text-emerald-400");

  const tmax = obs.today.tmax_c, tmin = obs.today.tmin_c;
  $("todayMin").textContent = fmt(tmin, 1, " C");
  $("todayMax").textContent = fmt(tmax, 1, " C");
  $("diurnal").textContent = fmt((tmax ?? 0) - (tmin ?? 0), 1, " C");
  if (tmax != null && tmin != null) {
    const lo = Math.min(tmin, n.record_tmin), hi = Math.max(tmax, n.record_tmax);
    const left = ((tmin - lo) / (hi - lo || 1)) * 100;
    const width = ((tmax - tmin) / (hi - lo || 1)) * 100;
    $("diurnalBar").style.marginLeft = `${left.toFixed(0)}%`;
    $("diurnalBar").style.width = `${Math.max(width, 4).toFixed(0)}%`;
  }

  $("precipProb").textContent = fmt(obs.precip_probability_peak_pct, 0);
  $("precipPeak").textContent = obs.precip_probability_peak_time
    ? `Probability peak ${obs.precip_probability_peak_time.slice(11, 16)}`
    : "No precipitation signal";

  $("pressure").textContent = fmt(obs.pressure_hpa, 1);
  const trend = obs.pressure_trend_3h;
  $("pressureTrend").textContent = `${trend >= 0 ? "+" : ""}${fmt(trend, 1)} hPa / 3h trend`;
  const tl = $("pressureTrendLabel");
  tl.textContent = trend == null ? "--" : trend < -0.5 ? "Falling" : trend > 0.5 ? "Rising" : "Steady";
  tl.className = "text-[10px] font-mono " + (trend < -0.5 ? "text-amber-400" : trend > 0.5 ? "text-emerald-400" : "text-slate-400");

  $("dewPoint").textContent = fmt(obs.dew_point_c, 1);
  $("rhSpread").textContent = fmt((obs.temperature_c ?? 0) - (obs.dew_point_c ?? 0), 1, " C");
  const hum = obs.humidity_pct;
  const humLabel = $("humidityLabel");
  humLabel.textContent = hum >= 75 ? "Humid" : hum >= 45 ? "Moderate" : "Dry";
  humLabel.className = "text-[10px] font-mono " + (hum >= 75 ? "text-emerald-400" : hum >= 45 ? "text-cyan-300" : "text-amber-400");

  const cc = obs.cloud_cover_pct ?? 0;
  $("cloudCover").textContent = fmt(cc, 0);
  $("cloudOktas").textContent = `${Math.round((cc / 100) * 8)}/8 oktas`;
  $("cloudNote").textContent = cc > 87 ? "Overcast (OVC)" : cc > 50 ? "Broken (BKN)" : cc > 25 ? "Scattered (SCT)" : "Few / Clear (FEW)";

  // METAR-style narrative, generated from live + dataset climatology
  $("metarText").textContent = buildNarrative(data);

  // wind / moisture / visibility / ephemeris cards
  $("windDir").textContent = `${obs.wind_compass} (${Math.round(obs.wind_direction_deg)} deg)`;
  $("windSpeed").textContent = fmt(obs.wind_speed_kmph, 1);
  $("windGust").textContent = fmt(obs.wind_gust_kmph, 1, " km/h");
  $("windBar").style.width = `${Math.min(100, (obs.wind_speed_kmph / 40) * 100).toFixed(0)}%`;
  $("windNormal").textContent = fmt(n.mean_wind, 1, " km/h");
  $("compassArrow").style.transform = `rotate(${obs.wind_direction_deg}deg)`;

  $("humidity").textContent = fmt(hum, 0);
  $("humidityBar").style.width = `${Math.min(100, hum || 0).toFixed(0)}%`;
  $("saturationLabel").textContent = hum >= 80 ? "High Saturation" : hum >= 50 ? "Moderate" : "Low Saturation";
  const es = 6.112 * Math.exp((17.67 * obs.temperature_c) / (obs.temperature_c + 243.5));
  const e = (es * hum) / 100;
  $("vapourPressure").textContent = `${(e / 10).toFixed(2)} kPa`;
  $("mixingRatio").textContent = `${(621.97 * e / ((obs.pressure_hpa || 1013) - e)).toFixed(1)} g/kg`;
  $("rhNormal").textContent = fmt(n.mean_rh, 1, " %");

  $("visibility").textContent = fmt(obs.visibility_km, 1);
  $("visibilityBar").style.width = `${Math.min(100, ((obs.visibility_km || 0) / 30) * 100).toFixed(0)}%`;
  $("visibilityNote").textContent = (obs.visibility_km ?? 0) > 10 ? "Unrestricted clear air"
    : (obs.visibility_km ?? 0) > 5 ? "Slight haze" : "Restricted / fog risk";
  $("precipSum").textContent = fmt(obs.today.precip_sum_mm, 1, " mm");
  $("visibilityCondition").textContent = obs.condition;

  renderEphemeris(obs);
  renderGauges(obs, n);

  // map footer facts
  $("stationElev").textContent = `${st.elevation_m} m`;
  $("terrainTag").textContent = st.terrain_type;
  $("heatwaveDays").textContent = st.heatwave_days;
  $("heatwaveRate").textContent = `${n.heatwave_rate_pct}% of window`;
  const alertEl = $("alertState");
  alertEl.textContent = `${data.alert_color} / ${data.severity}`;
  alertEl.className = "font-semibold text-sm " + (
    data.alert_color === "RED" ? "text-rose-400" :
    data.alert_color === "ORANGE" ? "text-amber-400" :
    data.alert_color === "YELLOW" ? "text-yellow-300" : "text-emerald-400");

  $("normalTmax").textContent = fmt(n.normal_tmax, 1, " C");
  $("recordTmax").textContent = fmt(n.record_tmax, 1, " C");
  $("providerTag").textContent = `Provider: ${obs.provider}`;
  $("lastSync").textContent = `Synced ${new Date().toLocaleTimeString()}`;
  $("pingValue").textContent = `${data.__latency} ms`;
}

function buildNarrative(data) {
  const o = data.observation, n = data.normals, dep = data.departure_tmax_c;
  const bits = [];
  bits.push(`${o.condition} at ${fmt(o.temperature_c, 1)} C; today's max of ${fmt(data.departure_reference_c, 1)} C is ${dep >= 0 ? "above" : "below"} the station normal max of ${n.normal_tmax} C by ${Math.abs(dep).toFixed(1)} C.`);
  if (o.pressure_trend_3h != null && o.pressure_trend_3h < -1)
    bits.push("Pressure falling sharply over 3h - destabilising airmass.");
  else if (o.pressure_trend_3h != null && o.pressure_trend_3h > 1)
    bits.push("Pressure rising - subsidence and settling conditions.");
  if ((o.precip_probability_peak_pct ?? 0) >= 60)
    bits.push(`Precipitation likelihood peaks at ${o.precip_probability_peak_pct}% near ${(o.precip_probability_peak_time || "").slice(11, 16)}.`);
  if ((o.wind_gust_kmph ?? 0) > 30)
    bits.push(`Gust potential to ${fmt(o.wind_gust_kmph, 0)} km/h from the ${o.wind_compass}.`);
  if (data.severity !== "NONE")
    bits.push(`Heatwave screening flags ${data.severity} (${data.alert_color}); this window historically records heatwave conditions on ${n.heatwave_rate_pct}% of days.`);
  return bits.join(" ");
}

function renderEphemeris(obs) {
  const { sunrise, sunset, daylight_seconds } = obs.today;
  if (!sunrise || !sunset) return;
  $("sunrise").textContent = sunrise.slice(11, 16);
  $("sunset").textContent = sunset.slice(11, 16);
  const h = Math.floor((daylight_seconds || 0) / 3600);
  const m = Math.round(((daylight_seconds || 0) % 3600) / 60);
  $("daylight").textContent = `${h}h ${m}m`;

  const now = new Date(obs.observed_at || Date.now());
  $("localTime").textContent = now.toTimeString().slice(0, 5);
  const rise = new Date(sunrise), set = new Date(sunset);
  const frac = Math.max(0, Math.min(1, (now - rise) / (set - rise || 1)));

  // point on the quadratic arc M10,45 Q80,5 150,45
  const bez = (t, p0, p1, p2) => (1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t ** 2 * p2;
  const x = bez(frac, 10, 80, 150), y = bez(frac, 45, 5, 45);
  $("sunDot").setAttribute("cx", x.toFixed(1));
  $("sunDot").setAttribute("cy", y.toFixed(1));

  const pts = [];
  for (let t = 0; t <= frac; t += 0.02) pts.push(`${bez(t, 10, 80, 150).toFixed(1)},${bez(t, 45, 5, 45).toFixed(1)}`);
  $("solarArc").setAttribute("d", pts.length > 1 ? `M ${pts.join(" L ")}` : "M 10 45");
}

function arcPath(fraction) {
  const f = Math.max(0, Math.min(1, fraction));
  const angle = Math.PI * (1 - f);
  const x = 50 + 40 * Math.cos(angle) * -1;
  const y = 50 - 40 * Math.sin(angle);
  return `M 10 50 A 40 40 0 0 1 ${x.toFixed(2)} ${y.toFixed(2)}`;
}

function renderGauges(obs, normals) {
  const aq = obs.air_quality || {};
  const uv = aq.uv_index ?? obs.today.uv_index_max ?? 0;
  $("uvValue").textContent = fmt(uv, 1);
  $("uvArc").setAttribute("d", arcPath(uv / 11));
  const uvLabel = uv < 3 ? "LOW" : uv < 6 ? "MODERATE" : uv < 8 ? "HIGH" : uv < 11 ? "VERY HIGH" : "EXTREME";
  $("uvLabel").textContent = uvLabel;
  $("uvArc").setAttribute("stroke", uv < 3 ? "#10b981" : uv < 6 ? "#f59e0b" : uv < 8 ? "#f97316" : "#e11d48");

  const aqi = aq.european_aqi ?? 0;
  $("aqiValue").textContent = fmt(aqi, 0);
  $("aqiArc").setAttribute("d", arcPath(aqi / 150));
  const aqiLabel = aqi <= 20 ? "GOOD" : aqi <= 40 ? "FAIR" : aqi <= 60 ? "MODERATE" : aqi <= 80 ? "POOR" : "VERY POOR";
  const aqiColor = aqi <= 20 ? "#10b981" : aqi <= 40 ? "#84cc16" : aqi <= 60 ? "#f59e0b" : aqi <= 80 ? "#f97316" : "#e11d48";
  $("aqiArc").setAttribute("stroke", aqiColor);
  $("aqiLabel").textContent = aqiLabel;
  $("aqiLabel").style.color = aqiColor;

  $("pm25").textContent = fmt(aq.pm2_5, 1, " ug/m3");
  $("pm10").textContent = fmt(aq.pm10, 1, " ug/m3");
  $("sensorState").textContent = `${obs.provider} feed`;
}

/* ------------------------------------------------------- geospatial grid */
function renderStationMap() {
  const layer = $("stationLayer");
  const all = state.stations;
  if (!all.length) return;

  // the scope pills filter which source is plotted; the selected location is
  // always drawn so it never disappears from under the user
  const stations = all.filter((s) =>
    state.scope === "all" || s.source === state.scope ||
    (state.station && s.location === state.station.location));
  if (!stations.length) return;

  const lats = stations.map((s) => s.latitude), lons = stations.map((s) => s.longitude);
  const padLat = 1.2, padLon = 1.2;
  const minLat = Math.min(...lats) - padLat, maxLat = Math.max(...lats) + padLat;
  const minLon = Math.min(...lons) - padLon, maxLon = Math.max(...lons) + padLon;

  const metricOf = {
    temp: (s) => s.avg_tmax, humidity: (s) => s.avg_rh,
    elevation: (s) => s.elevation_m, heatwave: (s) => s.heatwave_days,
  }[state.layer];
  const unit = { temp: "C", humidity: "%", elevation: "m", heatwave: "days" }[state.layer];

  const values = stations.map(metricOf);
  const lo = Math.min(...values), hi = Math.max(...values);

  layer.innerHTML = stations.map((s) => {
    const x = ((s.longitude - minLon) / (maxLon - minLon)) * 100;
    const y = 100 - ((s.latitude - minLat) / (maxLat - minLat)) * 100;
    const v = metricOf(s);
    const color = tempColor(v, lo, hi);
    const active = state.station && s.location === state.station.location;
    const isRegion = s.source === "open-meteo-archive";
    const size = active ? 16 : 11;
    // regions are drawn as diamonds so the two sources stay distinguishable
    const shape = isRegion
      ? `clip-path: polygon(50% 0,100% 50%,50% 100%,0 50%); border-radius:0;`
      : `border-radius:9999px;`;
    return `<div class="absolute flex flex-col items-center group cursor-pointer" style="left:${x.toFixed(2)}%; top:${y.toFixed(2)}%; transform: translate(-50%,-50%); z-index:${active ? 20 : 10};"
                 data-location="${s.location.replace(/"/g, "&quot;")}">
      ${active ? `<span class="absolute animate-ping" style="width:${size}px;height:${size}px;background:${color};opacity:.7;${shape}"></span>` : ""}
      <span class="station-dot relative" style="width:${size}px;height:${size}px;background:${color};box-shadow:0 0 10px ${color};${shape}"></span>
      <div class="mt-1.5 px-2 py-0.5 rounded bg-space-900/95 border ${active ? "border-cyan-400/60 text-cyan-200" : "border-slate-700 text-slate-300"} text-[9px] font-mono whitespace-nowrap ${active ? "" : "opacity-0 group-hover:opacity-100 transition-opacity"}">
        ${s.station}: ${fmt(v, unit === "m" || unit === "days" ? 0 : 1)} ${unit}
      </div>
    </div>`;
  }).join("");

  layer.querySelectorAll("[data-location]").forEach((el) => {
    el.addEventListener("click", () => {
      $("stationSelect").value = el.dataset.location;
      selectStation(el.dataset.location);
    });
  });

  const nStations = stations.filter((s) => s.source === "climate-final-k").length;
  $("mapExtent").textContent =
    `Extent: ${minLat.toFixed(1)}-${maxLat.toFixed(1)} N, ${minLon.toFixed(1)}-${maxLon.toFixed(1)} E | ` +
    `${nStations} AWS nodes + ${stations.length - nStations} regions | equirectangular`;
  $("scaleUnit").textContent = unit;
  $("scaleLow").textContent = fmt(lo, 0);
  $("scaleMid").textContent = fmt((lo + hi) / 2, 0);
  $("scaleHigh").textContent = fmt(hi, 0);

  const hottest = [...stations].sort((a, b) => b.avg_tmax - a.avg_tmax)[0];
  $("hottestStation").textContent = `${hottest.station} (${hottest.avg_tmax} C)`;
}

/* -------------------------------------------------- time series + forecast */
function renderSeries(series, forecast, live) {
  const histLabels = series.dates.slice(-120);
  const tmax = series.tmax.slice(-120);
  const tmin = series.tmin.slice(-120);
  const normal = series.normal_tmax.slice(-120);

  let labels = [...histLabels];
  let predicted = new Array(labels.length).fill(null);
  let ciHi = new Array(labels.length).fill(null);
  let ciLo = new Array(labels.length).fill(null);

  // anchor the projection at "now"
  labels.push("NOW");
  tmax.push(live ? live.observation.temperature_c : null);
  tmin.push(null); normal.push(null);
  predicted.push(live ? live.observation.temperature_c : forecast.predicted[7]);
  ciHi.push(predicted[predicted.length - 1]);
  ciLo.push(predicted[predicted.length - 1]);

  forecast.predicted.slice(8).forEach((p, i) => {
    labels.push(`+${i + 1}d`);
    tmax.push(null); tmin.push(null); normal.push(null);
    predicted.push(p);
    ciHi.push(forecast.ci_upper[8 + i]);
    ciLo.push(forecast.ci_lower[8 + i]);
  });

  drawChart("series", "seriesChart", {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "CI upper", data: ciHi, borderColor: "transparent", backgroundColor: "rgba(139,92,246,0.18)",
          fill: "+1", pointRadius: 0, tension: 0.35 },
        { label: "CI lower", data: ciLo, borderColor: "transparent", backgroundColor: "transparent",
          fill: false, pointRadius: 0, tension: 0.35 },
        { label: "Tmax (C)", data: tmax, borderColor: "#00f2fe", backgroundColor: "rgba(0,242,254,0.12)",
          borderWidth: 2, pointRadius: 0, tension: 0.3, fill: true, spanGaps: false },
        { label: "Tmin (C)", data: tmin, borderColor: "#10b981", borderWidth: 1.8, pointRadius: 0, tension: 0.3 },
        { label: "Normal Tmax", data: normal, borderColor: "rgba(148,163,184,0.55)", borderDash: [4, 4],
          borderWidth: 1.2, pointRadius: 0, tension: 0.3 },
        { label: "Predicted", data: predicted, borderColor: "#8b5cf6", borderDash: [6, 4],
          borderWidth: 2.5, pointRadius: 0, tension: 0.35 },
      ],
    },
    options: {
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#0c1222", borderColor: "#1f3056", borderWidth: 1,
          filter: (item) => !item.dataset.label.startsWith("CI"),
        },
      },
      scales: {
        x: { grid: gridStyle, ticks: { maxTicksLimit: 10, autoSkip: true } },
        y: { grid: gridStyle, ticks: { callback: (v) => `${v} C` } },
      },
    },
  });

  $("fcRmse").textContent = `${forecast.rmse} C`;
  $("fcR2").textContent = forecast.r2;
  $("fcSigma").textContent = `${forecast.residual_sd} C`;
  $("seriesSubtitle").textContent =
    `Last ${histLabels.length} dataset days vs +7d harmonic projection (anchor offset ${forecast.anchor_offset >= 0 ? "+" : ""}${forecast.anchor_offset} C)`;
}

/* ------------------------------------------------------------ distribution */
function renderDistribution(dist, stats) {
  $("kdeN").textContent = dist.grouped.n;

  drawChart("dist", "distChart", {
    data: {
      labels: dist.midpoints,
      datasets: [
        { type: "bar", label: "Frequency", data: dist.frequency,
          backgroundColor: dist.frequency.map((f) => f === Math.max(...dist.frequency)
            ? "rgba(0,242,254,0.85)" : "rgba(59,130,246,0.45)"),
          borderRadius: 3, barPercentage: 0.95, categoryPercentage: 0.95 },
        { type: "line", label: "KDE", data: dist.kde_x.map((x, i) => ({ x, y: dist.kde_y[i] })),
          borderColor: "#f59e0b", borderWidth: 2, pointRadius: 0, tension: 0.4, xAxisID: "xKde" },
      ],
    },
    options: {
      plugins: { tooltip: { backgroundColor: "#0c1222" } },
      scales: {
        x: { grid: { display: false }, ticks: { maxTicksLimit: 6 } },
        xKde: { display: false, type: "linear", min: Math.min(...dist.kde_x), max: Math.max(...dist.kde_x) },
        y: { grid: gridStyle, ticks: { maxTicksLimit: 4 } },
      },
    },
  });

  // box plot built from the manual quantiles (Exp-3)
  const lo = stats.whisker_low, hi = stats.whisker_high, span = hi - lo || 1;
  const pct = (v) => `${(((v - lo) / span) * 92 + 4).toFixed(1)}%`;
  $("boxPlot").innerHTML = `
    <div class="absolute top-1/2 h-0.5 bg-slate-600" style="left:${pct(lo)};right:${100 - parseFloat(pct(hi))}%"></div>
    <div class="absolute top-1/2 -translate-y-1/2 h-3 w-0.5 bg-slate-400" style="left:${pct(lo)}"></div>
    <div class="absolute top-1/2 -translate-y-1/2 h-3 w-0.5 bg-slate-400" style="left:${pct(hi)}"></div>
    <div class="absolute top-1/2 -translate-y-1/2 h-4 bg-cyan-500/20 border border-cyan-400 rounded-sm"
         style="left:${pct(stats.q1)};width:${(((stats.q3 - stats.q1) / span) * 92).toFixed(1)}%"></div>
    <div class="absolute top-1/2 -translate-y-1/2 h-4 w-1 bg-amber-400 shadow-sm shadow-amber-400" style="left:${pct(stats.median)}"></div>`;

  $("statIqr").textContent = fmt(stats.iqr, 2);
  $("statMean").textContent = fmt(stats.mean, 2);
  $("statStd").textContent = `+/-${fmt(stats.std, 2)}`;
  $("statMedian").textContent = fmt(stats.median, 2);
  $("statMode").textContent = fmt(stats.mode, 2);
  $("statSkew").textContent = fmt(stats.skewness, 3);
  $("statKurt").textContent = fmt(stats.kurtosis, 3);
  $("statVar").textContent = fmt(stats.variance, 2);
  $("statCv").textContent = fmt(stats.cv_pct, 1, "%");
  $("p25").textContent = fmt(stats.p25, 1);
  $("p50").textContent = fmt(stats.p50, 1);
  $("p75").textContent = fmt(stats.p75, 1);
  $("p99").textContent = fmt(stats.p99, 1);

  $("gMean").textContent = dist.grouped.mean;
  $("gMedian").textContent = dist.grouped.median;
  $("gMode").textContent = dist.grouped.mode;
  $("gStd").textContent = dist.grouped.std;
}

/* ---------------------------------------------------------------- heatmap */
function renderHeatmap(h) {
  const unit = h.metric.includes("rh") ? "%" : h.metric.includes("wind") ? "" : "";
  const head = `<thead><tr class="text-[10px] font-mono text-slate-400">
      <th class="py-1 px-1 text-left">Month</th>
      ${h.years.map((y) => `<th class="p-1">${y}</th>`).join("")}
    </tr></thead>`;

  const body = h.months.map((m, i) => {
    const cells = h.values[i].map((v) => {
      if (v === null) return `<td class="p-1"><div class="h-6 rounded bg-space-900 border border-slate-800/60 flex items-center justify-center text-slate-600">-</div></td>`;
      const bg = tempColor(v, h.min, h.max);
      const strong = (v - h.min) / (h.max - h.min || 1) > 0.55;
      return `<td class="p-1"><div class="h-6 rounded flex items-center justify-center ${strong ? "text-white font-bold" : "text-slate-100"}"
        style="background:${bg}${strong ? "" : "; opacity:.85"}" title="${m} - ${v}${unit}">${v}</div></td>`;
    }).join("");
    return `<tr class="border-t border-slate-800/40">
      <td class="text-left font-semibold text-slate-400 py-1 pr-1 text-[10px]">${m.slice(0, 3)}</td>${cells}</tr>`;
  }).join("");

  $("heatTable").innerHTML = head + `<tbody class="text-[10px] font-mono">${body}</tbody>`;

  const steps = 5;
  $("heatLegend").innerHTML = Array.from({ length: steps }, (_, i) => {
    const v = h.min + ((h.max - h.min) * i) / (steps - 1);
    return `<span class="w-3 h-3 rounded ml-2" style="background:${tempColor(v, h.min, h.max)}"></span><span>${v.toFixed(0)}</span>`;
  }).join("");
}

/* ------------------------------------------------------------ correlation */
function renderCorrelation(c) {
  const size = c.labels.length;
  const header = `<div class="text-slate-500"></div>` +
    c.labels.map((l) => `<div class="text-slate-400 font-bold text-[9px] truncate" title="${l}">${l.slice(0, 5)}</div>`).join("");

  const rows = c.matrix.map((row, i) =>
    `<div class="text-slate-400 font-bold text-left text-[9px] truncate" title="${c.columns[i]}">${c.labels[i].slice(0, 5)}</div>` +
    row.map((r) => r === null
      ? `<div class="p-1.5 rounded bg-space-900 text-slate-600">-</div>`
      : `<div class="p-1.5 rounded" style="${corrColor(r)}" title="${r}">${r.toFixed(2)}</div>`).join("")
  ).join("");

  $("corrGrid").style.display = "grid";
  $("corrGrid").style.gridTemplateColumns = `minmax(34px,auto) repeat(${size}, minmax(30px,1fr))`;
  $("corrGrid").style.gap = "2px";
  $("corrGrid").innerHTML = header + rows;

  $("corrPairs").innerHTML = c.manual_pairs.map((p) => {
    const color = p.r > 0.3 ? "text-cyan-300" : p.r < -0.3 ? "text-rose-300" : "text-slate-400";
    return `<div class="flex justify-between bg-space-950/60 border border-slate-800 rounded px-2 py-1">
      <span class="text-slate-500 truncate">${p.x} vs ${p.y}</span>
      <span class="${color} font-bold">r = ${p.r.toFixed(3)}</span></div>`;
  }).join("");
}

/* ------------------------------------------------------------- regression */
function renderRegression(reg) {
  drawChart("slr", "slrChart", {
    type: "scatter",
    data: {
      datasets: [
        { label: "Observations", data: reg.slr.scatter.map(([x, y]) => ({ x, y })),
          backgroundColor: "rgba(56,189,248,0.35)", pointRadius: 2 },
        { type: "line", label: "Regression line", data: reg.slr.line.map(([x, y]) => ({ x, y })),
          borderColor: "#f43f5e", borderWidth: 2, pointRadius: 0 },
      ],
    },
    options: {
      plugins: { tooltip: { backgroundColor: "#0c1222" } },
      scales: {
        x: { grid: gridStyle, title: { display: true, text: reg.slr.predictor, color: "#64748b" } },
        y: { grid: gridStyle, title: { display: true, text: reg.slr.target, color: "#64748b" } },
      },
    },
  });
  $("slrEquation").textContent = reg.slr.equation;
  $("slrMae").textContent = reg.slr.mae;
  $("slrRmse").textContent = reg.slr.rmse;
  $("slrR2").textContent = reg.slr.r2;

  const pts = reg.mlr.actual_vs_pred;
  const all = pts.flat();
  const lim = [Math.min(...all), Math.max(...all)];
  drawChart("mlr", "mlrChart", {
    type: "scatter",
    data: {
      datasets: [
        { label: "Actual vs predicted", data: pts.map(([a, p]) => ({ x: a, y: p })),
          backgroundColor: "rgba(139,92,246,0.45)", pointRadius: 2.5 },
        { type: "line", label: "Ideal", data: lim.map((v) => ({ x: v, y: v })),
          borderColor: "#f43f5e", borderWidth: 1.5, pointRadius: 0 },
      ],
    },
    options: {
      plugins: { tooltip: { backgroundColor: "#0c1222" } },
      scales: {
        x: { grid: gridStyle, title: { display: true, text: "Actual tmax_c", color: "#64748b" } },
        y: { grid: gridStyle, title: { display: true, text: "Predicted tmax_c", color: "#64748b" } },
      },
    },
  });
  $("mlrEquation").textContent = reg.mlr.equation;
  $("mlrMae").textContent = reg.mlr.mae;
  $("mlrRmse").textContent = reg.mlr.rmse;
  $("mlrR2").textContent = reg.mlr.r2;
}

/* ------------------------------------------------- aggregation + encoding */
function renderAggregation(agg, enc) {
  const palette = ["#00f2fe", "#10b981", "#f59e0b", "#8b5cf6", "#f43f5e", "#3b82f6"];
  drawChart("agg", "aggChart", {
    type: "line",
    data: {
      labels: agg.monthly_by_terrain.months.map((m) => m.slice(0, 3)),
      datasets: agg.monthly_by_terrain.series.map((s, i) => ({
        label: s.terrain, data: s.tmax, borderColor: palette[i % palette.length],
        backgroundColor: palette[i % palette.length], borderWidth: 2, pointRadius: 2, tension: 0.35,
      })),
    },
    options: {
      plugins: {
        legend: { display: true, position: "bottom", labels: { boxWidth: 8, font: { size: 9 } } },
        tooltip: { backgroundColor: "#0c1222" },
      },
      scales: { x: { grid: gridStyle }, y: { grid: gridStyle, ticks: { callback: (v) => `${v}C` } } },
    },
  });

  const chips = (title, items, colors) => `
    <div class="bg-space-950/60 border border-slate-800 rounded-lg p-2">
      <div class="text-slate-500 uppercase text-[9px] mb-1">${title}</div>
      ${items.map((it, i) => `<div class="flex justify-between">
        <span style="color:${colors[i % colors.length]}">${it.label} [${it.code}]</span>
        <span class="text-slate-300">${it.count}</span></div>`).join("")}
    </div>`;

  $("encodingGrid").innerHTML =
    chips("severity (ordinal)", enc.severity, ["#10b981", "#f59e0b", "#f43f5e"]) +
    chips("alert_color (ordinal)", enc.alert_color, ["#10b981", "#facc15", "#f97316", "#f43f5e"]) +
    chips("tmax_category", enc.tmax_category, ["#38bdf8", "#00f2fe", "#f59e0b", "#f43f5e"]) +
    chips("wind_category", enc.wind_category, ["#64748b", "#38bdf8", "#00f2fe", "#8b5cf6"]);

  const rank = agg.station_ranking;
  if (rank.length) {
    const coolest = rank[0], hottest = rank[rank.length - 1];
    $("rankingNote").innerHTML =
      `Station ranking by mean_temp_c &mdash; coolest <span class="text-cyan-300">${coolest.station} (${coolest.mean_temp} C)</span>,
       hottest <span class="text-rose-300">${hottest.station} (${hottest.mean_temp} C)</span>.
       Yearly mean Tmax ${agg.yearly.years[0]}&ndash;${agg.yearly.years[agg.yearly.years.length - 1]}:
       <span class="text-slate-200">${agg.yearly.tmax[0]} C &rarr; ${agg.yearly.tmax[agg.yearly.tmax.length - 1]} C</span>.`;
  }
}

/* ------------------------------------------------------------- quality UI */
function renderQuality(q) {
  $("completeness").textContent = `${q.completeness_pct}%`;
  $("qCompleteness").textContent = `${q.completeness_pct}%`;
  $("qOutliers").textContent = `${q.outlier_total.toLocaleString()} anomalies`;
  $("qDuplicates").textContent = q.duplicates;
  $("qTrimmed").textContent = q.rows_after_iqr_trim.toLocaleString();
  $("pipelineRows").textContent = q.rows.toLocaleString();
  $("pipelineRange").textContent = `${q.date_range[0]} to ${q.date_range[1]} across ${q.stations} stations`;

  $("outlierTable").innerHTML = `
    <thead><tr class="text-slate-500 uppercase text-[9px]">
      <th class="py-1 text-left">Column</th><th class="text-right">Outliers</th>
      <th class="text-right">Lower</th><th class="text-right">Upper</th></tr></thead>
    <tbody>${q.outliers.map((o) => `<tr class="border-t border-slate-800/60">
      <td class="py-1 text-slate-300">${o.column}</td>
      <td class="text-right text-amber-400">${o.count}</td>
      <td class="text-right text-slate-400">${o.lower}</td>
      <td class="text-right text-slate-400">${o.upper}</td></tr>`).join("")}</tbody>`;
}

function renderTaxonomy(schema) {
  const badge = (m) => ({
    Nominal: "text-cyan-300", Ordinal: "text-violet-300",
    Interval: "text-amber-300", Ratio: "text-emerald-300",
  }[m] || "text-slate-300");

  $("taxonomyTable").innerHTML = `
    <thead><tr class="text-slate-500 uppercase text-[9px]">
      <th class="py-1 text-left">Attribute</th><th class="text-left">Kind</th>
      <th class="text-left">Scale</th><th class="text-left">Measurement</th></tr></thead>
    <tbody>${schema.attributes.map((a) => `<tr class="border-t border-slate-800/60">
      <td class="py-1 text-slate-300">${a.attribute}</td>
      <td class="text-slate-400">${a.kind}</td>
      <td class="text-slate-400">${a.scale_type}</td>
      <td class="${badge(a.measurement)}">${a.measurement}</td></tr>`).join("")}</tbody>`;
}

/* --------------------------------------------------------------- loading */
async function loadStatic() {
  const [quality, schema] = await Promise.all([api("/api/quality"), api("/api/schema")]);
  renderQuality(quality);
  renderTaxonomy(schema);
  state.last.quality = quality;
}

async function loadStationAnalytics(location) {
  const [series, stats, dist, corr, reg, agg, heat, enc] = await Promise.all([
    api("/api/timeseries", { location }),
    api("/api/stats", { location, column: state.distColumn }),
    api("/api/distribution", { location, column: state.distColumn }),
    api("/api/correlation", { location }),
    api("/api/regression", { location }),
    api("/api/aggregation", { location }),
    api("/api/heatmap", { location, metric: state.heatMetric }),
    api("/api/categorical", { location }),
  ]);

  state.last.series = series;
  renderDistribution(dist, stats);
  renderCorrelation(corr);
  renderRegression(reg);
  renderAggregation(agg, enc);
  renderHeatmap(heat);
  Object.assign(state.last, { stats, dist, corr, reg, agg, heat, enc });
  return series;
}

async function refreshLive() {
  const location = state.station?.location;
  if (!location) return;
  try {
    const live = await api("/api/live", { location });
    renderLive(live);
    const forecast = await api("/api/forecast", { location, live_temp: live.observation.temperature_c });
    state.last.forecast = forecast;
    if (state.last.series) renderSeries(state.last.series, forecast, live);
    renderStationMap();
    $("syncBadge").textContent = "OK";
    $("syncBadge").className = "w-8 h-8 rounded-full bg-slate-800 border border-emerald-500/40 flex items-center justify-center text-xs text-emerald-400 font-mono";
    $("streamState").textContent = "active stream";
    $("qSync").textContent = "Synced";
  } catch (err) {
    console.error(err);
    $("syncBadge").textContent = "ERR";
    $("syncBadge").className = "w-8 h-8 rounded-full bg-slate-800 border border-rose-500/40 flex items-center justify-center text-xs text-rose-400 font-mono";
    $("streamState").textContent = "provider offline";
    $("qSync").textContent = "Degraded";
    $("metarText").textContent =
      "Live provider unreachable - the dataset panels below are still computed from the local climate archive.";
  }
}

async function selectStation(location) {
  state.station = state.stations.find((s) => s.location === location) || state.stations[0];
  const series = await loadStationAnalytics(state.station.location);
  await refreshLive();
  if (state.last.forecast) renderSeries(series, state.last.forecast, state.last.live);
  scheduleRefresh();
}

function scheduleRefresh() {
  clearInterval(state.timer);
  state.timer = setInterval(refreshLive, REFRESH_MS[state.range]);
}

/* ------------------------------------------------------------------ init */
async function init() {
  if (!HAS_CHARTS) {
    console.warn("Chart.js did not load - charts are disabled, panels still work.");
    $("seriesSubtitle").textContent =
      "Chart library unavailable (offline or CDN blocked) - numeric panels below still update.";
  }

  // Controls are wired before any data is fetched, so the dashboard stays
  // interactive even if an endpoint or the provider is down.
  wireEvents();

  await loadStatic();

  const { stations } = await api("/api/stations");
  state.stations = stations;

  // grouped: the dataset's own AWS stations, then every state / UT
  const group = (label, rows, describe) => rows.length
    ? `<optgroup label="${label}">` + rows.map((s) =>
        `<option value="${s.location}">${describe(s)}</option>`).join("") + "</optgroup>"
    : "";

  $("stationSelect").innerHTML =
    group("AWS stations - Climate_final_k dataset",
          stations.filter((s) => s.source === "climate-final-k"),
          (s) => `${s.station} - ${s.zone} (${s.terrain_type})`) +
    group("States & union territories - live archive",
          stations.filter((s) => s.source === "open-meteo-archive"),
          (s) => `${s.station} - ${s.zone} (${s.kind})`);

  await selectStation(stations[0].location);
  renderStationMap();
}

function wireEvents() {
  $("stationSelect").addEventListener("change", (e) => selectStation(e.target.value));
  $("refreshBtn").addEventListener("click", refreshLive);

  $("rangePills").addEventListener("click", (e) => {
    const btn = e.target.closest(".range-pill");
    if (!btn) return;
    state.range = btn.dataset.range;
    document.querySelectorAll(".range-pill").forEach((b) => {
      b.className = b === btn
        ? "range-pill px-3 py-1 rounded-lg bg-blue-600/30 text-cyan-300 font-medium border border-cyan-500/30"
        : "range-pill px-3 py-1 rounded-lg text-slate-400 hover:text-slate-200 transition-colors";
    });
    scheduleRefresh();
    refreshLive();
  });

  $("mapScope").addEventListener("click", (e) => {
    const btn = e.target.closest(".scope-pill");
    if (!btn) return;
    state.scope = btn.dataset.scope;
    document.querySelectorAll(".scope-pill").forEach((b) => {
      b.className = b === btn
        ? "scope-pill px-2.5 py-1 rounded-lg bg-slate-700/50 text-slate-200 border border-slate-600/50"
        : "scope-pill px-2.5 py-1 rounded-lg text-slate-400 hover:text-slate-200 transition-colors";
    });
    renderStationMap();
  });

  $("mapLayers").addEventListener("click", (e) => {
    const btn = e.target.closest(".layer-pill");
    if (!btn) return;
    state.layer = btn.dataset.layer;
    document.querySelectorAll(".layer-pill").forEach((b) => {
      b.className = b === btn
        ? "layer-pill px-2.5 py-1 rounded-lg bg-blue-600/40 text-cyan-300 font-medium border border-blue-500/40"
        : "layer-pill px-2.5 py-1 rounded-lg text-slate-400 hover:text-slate-200 transition-colors";
    });
    renderStationMap();
  });

  $("distColumn").addEventListener("change", async (e) => {
    state.distColumn = e.target.value;
    if (!state.station) return;
    const location = state.station.location;
    const [stats, dist] = await Promise.all([
      api("/api/stats", { location, column: state.distColumn }),
      api("/api/distribution", { location, column: state.distColumn }),
    ]);
    renderDistribution(dist, stats);
  });

  $("heatMetric").addEventListener("change", async (e) => {
    state.heatMetric = e.target.value;
    if (!state.station) return;
    renderHeatmap(await api("/api/heatmap", { location: state.station.location, metric: state.heatMetric }));
  });

  $("showDiagnostics").addEventListener("click", () => {
    $("diagnosticsPanel").classList.toggle("hidden");
    $("diagnosticsPanel").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $("closeDiagnostics").addEventListener("click", () => $("diagnosticsPanel").classList.add("hidden"));

  $("exportJson").addEventListener("click", () => {
    if (!state.station) return;
    const blob = new Blob([JSON.stringify(state.last, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `aethercast_${state.station.station.replace(/\s+/g, "_")}_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  });

  $("alertBell").addEventListener("click", () => {
    const live = state.last.live;
    if (!live) return;
    alert(`${live.station.station}\nSeverity: ${live.severity} (${live.alert_color})\n` +
          `Live ${live.observation.temperature_c} C vs normal ${live.normals.normal_tmax} C ` +
          `(departure ${live.departure_tmax_c} C)\nRecord Tmax in this window: ${live.normals.record_tmax} C`);
  });

  $("topNav").addEventListener("click", (e) => {
    const btn = e.target.closest(".nav-btn");
    if (!btn) return;
    document.querySelectorAll(".nav-btn").forEach((b) => {
      b.className = b === btn
        ? "nav-btn px-3.5 py-1.5 rounded-lg bg-cyan-500/10 text-cyan-300 border border-cyan-500/30 whitespace-nowrap transition-all"
        : "nav-btn px-3.5 py-1.5 rounded-lg text-slate-400 hover:text-cyan-300 hover:bg-space-800/60 border border-transparent whitespace-nowrap transition-all";
    });
    $(btn.dataset.target)?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

init().catch((err) => {
  console.error(err);
  document.getElementById("metarText").textContent =
    "Dashboard failed to start: " + err.message + " - is the FastAPI backend running on port 8000?";
});
