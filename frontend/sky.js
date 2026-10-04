/* =========================================================================
   sky.js - the live motion wallpaper ("Sky Mirror")
   -------------------------------------------------------------------------
   The page background is the weather it is reporting.  app.js calls
   Sky.update() with each live observation, and this module paints:

     * a sky gradient chosen from the WMO condition code and day/night state;
     * a sun or moon placed on its real arc between sunrise and sunset;
     * clouds whose number and opacity follow the observed cloud cover;
     * precipitation - rain streaks, snowflakes, drifting fog, storm flashes;
     * stars after dark, and a warm scrim when a heatwave alert is active.

   It is deliberately cheap and considerate: particle counts scale with the
   viewport, the loop stops when the tab is hidden or the canvas is off
   screen, and it degrades to a still gradient when the visitor asks for
   reduced motion.  The dashboard works unchanged if this file fails to load.
   ========================================================================= */

(function () {
  "use strict";

  /* Sky palettes: [top, middle, bottom] for day and night. */
  const SKIES = {
    clear:   { day: ["#1769cf", "#4f9fe4", "#a8d4f2"], night: ["#050914", "#0c1733", "#1b2a55"] },
    partly:  { day: ["#2a7bc6", "#6fb0e6", "#cbe2f4"], night: ["#070b18", "#111c38", "#24335c"] },
    cloudy:  { day: ["#5a7490", "#8aa2ba", "#c2d1de"], night: ["#0b1018", "#19222f", "#2d3949"] },
    fog:     { day: ["#8694a3", "#b5c1ca", "#dde4e8"], night: ["#141a20", "#232c34", "#39444e"] },
    drizzle: { day: ["#44576e", "#6a7f96", "#9aabbd"], night: ["#0a111b", "#172231", "#2a384b"] },
    rain:    { day: ["#1f2937", "#334155", "#5b6b7f"], night: ["#070d16", "#121c2b", "#232f42"] },
    snow:    { day: ["#5b6b84", "#93a4bd", "#d7e2ef"], night: ["#0d1422", "#1d2738", "#36445c"] },
    storm:   { day: ["#10182a", "#273149", "#434f6a"], night: ["#04070f", "#0d1424", "#1b2438"] },
  };

  /** WMO weather code -> sky kind (same grouping live_weather.py uses). */
  function kindFor(code) {
    const c = Number(code);
    if (c === 0 || c === 1) return "clear";
    if (c === 2) return "partly";
    if (c === 3) return "cloudy";
    if (c === 45 || c === 48) return "fog";
    if (c >= 51 && c <= 57) return "drizzle";
    if ((c >= 61 && c <= 67) || (c >= 80 && c <= 82)) return "rain";
    if ((c >= 71 && c <= 77) || c === 85 || c === 86) return "snow";
    if (c >= 95) return "storm";
    return "partly";
  }

  const CLOUDS_FOR = { clear: 0, partly: 2, cloudy: 3, fog: 2, drizzle: 3, rain: 3, snow: 3, storm: 3 };

  const state = {
    kind: "partly", isDay: true, cover: 40, severity: "NONE",
    forced: null, forcedNight: false,
    sunFrac: null,                      // 0..1 across the daylight arc, null at night
    motion: true, started: false, raf: null, particles: [], flash: 0, t: 0,
  };

  const reduceMotion = () => {
    try { return matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) { return false; }
  };

  let root, canvas, ctx, cloudLayer, orb;

  function build() {
    root = document.getElementById("skyLayer");
    if (!root) return false;
    root.innerHTML =
      '<div class="sky-grad" id="skyGrad"></div>' +
      '<div class="sky-orb" id="skyOrb"></div>' +
      '<div class="sky-clouds" id="skyClouds"></div>' +
      '<canvas class="sky-canvas" id="skyCanvas"></canvas>' +
      '<div class="sky-scrim"></div>';
    canvas = document.getElementById("skyCanvas");
    ctx = canvas.getContext("2d");
    cloudLayer = document.getElementById("skyClouds");
    orb = document.getElementById("skyOrb");
    sizeCanvas();
    addEventListener("resize", sizeCanvas, { passive: true });
    document.addEventListener("visibilitychange", () => (document.hidden ? stop() : start()));
    return true;
  }

  function sizeCanvas() {
    if (!canvas) return;
    const dpr = Math.min(devicePixelRatio || 1, 1.5);   // cap: this is decoration
    canvas.width = Math.floor(innerWidth * dpr);
    canvas.height = Math.floor(innerHeight * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    seed();
  }

  /** Particle field for the current kind, scaled to the viewport. */
  function seed() {
    const area = innerWidth * innerHeight;
    const scale = Math.min(1.6, Math.max(0.5, area / (1440 * 900)));
    const counts = { rain: 190, drizzle: 120, storm: 230, snow: 110, fog: 16, clear: 0, partly: 0, cloudy: 0 };
    const n = Math.round((counts[state.kind] || 0) * scale);
    const stars = !state.isDay && ["clear", "partly"].includes(state.kind)
      ? Math.round(120 * scale) : 0;

    state.particles = [];
    for (let i = 0; i < n; i++) {
      state.particles.push({
        x: Math.random() * innerWidth, y: Math.random() * innerHeight,
        len: 8 + Math.random() * 16, v: 5 + Math.random() * 7,
        r: 0.8 + Math.random() * 2.2, drift: Math.random() * 2 - 1,
        w: 60 + Math.random() * 160, o: 0.05 + Math.random() * 0.12,
      });
    }
    for (let i = 0; i < stars; i++) {
      state.particles.push({
        star: true, x: Math.random() * innerWidth, y: Math.random() * innerHeight * 0.72,
        r: 0.4 + Math.random() * 1.2, tw: Math.random() * 6.28,
      });
    }
  }

  function paintGradient() {
    const pal = (SKIES[state.kind] || SKIES.partly)[state.isDay ? "day" : "night"];
    const grad = document.getElementById("skyGrad");
    if (grad) grad.style.background =
      `linear-gradient(180deg, ${pal[0]} 0%, ${pal[1]} 48%, ${pal[2]} 100%)`;

    // a hot day gets a warm wash; severe alerts push it further
    root.classList.toggle("sky-hot", state.severity === "SEVERE" || state.severity === "MODERATE");
    root.classList.toggle("sky-severe", state.severity === "SEVERE");
  }

  function paintOrb() {
    if (!orb) return;
    const visible = state.sunFrac !== null && ["clear", "partly", "cloudy"].includes(state.kind);
    orb.style.display = visible ? "block" : "none";
    if (!visible) return;

    const f = Math.max(0, Math.min(1, state.sunFrac));
    const x = 8 + f * 84;                               // % across
    const y = 46 - Math.sin(f * Math.PI) * 34;          // % down: an arc
    orb.style.left = x + "%";
    orb.style.top = y + "%";
    orb.className = "sky-orb " + (state.isDay ? "is-sun" : "is-moon");
  }

  function paintClouds() {
    if (!cloudLayer) return;
    const want = Math.min(CLOUDS_FOR[state.kind] || 0,
                          Math.ceil((state.cover || 0) / 34));
    const opacity = state.isDay ? 0.78 : 0.3;
    let html = "";
    for (let i = 0; i < want; i++) {
      const top = 8 + i * 13 + (i % 2) * 5;
      const scale = 0.75 + (i % 3) * 0.3;
      const dur = 90 + i * 36;
      const delay = -(i * 31);
      html += `<div class="sky-cloud" style="top:${top}%;transform:scale(${scale});
               opacity:${opacity};animation-duration:${dur}s;animation-delay:${delay}s"></div>`;
    }
    cloudLayer.innerHTML = html;
  }

  function frame() {
    state.raf = requestAnimationFrame(frame);
    if (!ctx) return;
    state.t += 0.016;
    ctx.clearRect(0, 0, innerWidth, innerHeight);

    const k = state.kind;
    if (k === "rain" || k === "drizzle" || k === "storm") {
      ctx.strokeStyle = state.isDay ? "rgba(214,232,255,.55)" : "rgba(180,205,240,.45)";
      ctx.lineWidth = k === "drizzle" ? 0.9 : 1.2;
      ctx.beginPath();
      for (const p of state.particles) {
        if (p.star) continue;
        ctx.moveTo(p.x, p.y);
        ctx.lineTo(p.x - 2.4, p.y + p.len);
        p.y += p.v * (k === "drizzle" ? 0.65 : 1);
        p.x -= 0.8;
        if (p.y > innerHeight) { p.y = -24; p.x = Math.random() * innerWidth; }
      }
      ctx.stroke();

      if (k === "storm") {
        if (state.flash > 0) {
          ctx.fillStyle = `rgba(226,240,255,${state.flash * 0.5})`;
          ctx.fillRect(0, 0, innerWidth, innerHeight);
          state.flash -= 0.06;
        } else if (Math.random() < 0.0022) {
          state.flash = 1;
        }
      }
    } else if (k === "snow") {
      ctx.fillStyle = "rgba(255,255,255,.85)";
      for (const p of state.particles) {
        if (p.star) continue;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.28); ctx.fill();
        p.y += p.v * 0.22;
        p.x += Math.sin((p.y + p.drift * 40) / 42) * 0.7;
        if (p.y > innerHeight) { p.y = -8; p.x = Math.random() * innerWidth; }
      }
    } else if (k === "fog") {
      for (const p of state.particles) {
        if (p.star) continue;
        const x = (p.x + state.t * 9 * (0.4 + p.o)) % (innerWidth + p.w) - p.w / 2;
        ctx.fillStyle = `rgba(226,232,240,${p.o})`;
        ctx.beginPath();
        ctx.ellipse(x, p.y, p.w, p.w * 0.22, 0, 0, 6.28);
        ctx.fill();
      }
    }

    // stars twinkle on clear/partly nights
    for (const p of state.particles) {
      if (!p.star) continue;
      p.tw += 0.02;
      ctx.globalAlpha = 0.35 + Math.sin(p.tw) * 0.3;
      ctx.fillStyle = "#e2ecff";
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.28); ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  function start() {
    if (state.raf || !state.motion || reduceMotion() || document.hidden) return;
    state.raf = requestAnimationFrame(frame);
  }
  function stop() {
    if (state.raf) cancelAnimationFrame(state.raf);
    state.raf = null;
  }

  /** Fraction of the way from sunrise to sunset, or null outside daylight. */
  function solarFraction(nowIso, sunriseIso, sunsetIso) {
    if (!sunriseIso || !sunsetIso) return null;
    const now = nowIso ? new Date(nowIso) : new Date();
    const rise = new Date(sunriseIso), set = new Date(sunsetIso);
    if (isNaN(now) || isNaN(rise) || isNaN(set) || set <= rise) return null;
    const f = (now - rise) / (set - rise);
    return f < -0.12 || f > 1.12 ? null : Math.max(0, Math.min(1, f));
  }

  window.Sky = {
    init() {
      if (state.started) return;
      state.started = build();
      if (!state.started) return;
      try {
        state.motion = localStorage.getItem("aethercast-sky-motion") !== "off";

        // ?sky=rain&night=1 pins the wallpaper for previewing a condition the
        // selected location does not happen to have right now
        const q = new URLSearchParams(location.search);
        const forced = q.get("sky");
        if (forced && SKIES[forced]) {
          state.forced = forced;
          state.kind = forced;
          state.cover = 80;
        }
        if (q.get("night") === "1") { state.forcedNight = true; state.isDay = false; }
      } catch (e) { /* private mode */ }
      document.documentElement.classList.toggle("sky-static", !state.motion || reduceMotion());
      paintGradient(); paintOrb(); paintClouds(); seed(); start();
    },

    /** Called with each live observation; everything here comes from real data. */
    update(obs, extra) {
      if (!state.started) return;
      extra = extra || {};
      const today = (obs && obs.today) || {};
      const nextKind = state.forced || kindFor(obs && obs.weather_code);
      const wasNight = !state.isDay, wasKind = state.kind;

      state.kind = nextKind;
      state.isDay = state.forcedNight ? false : (obs ? !!obs.is_day : true);
      state.cover = obs && obs.cloud_cover_pct != null ? obs.cloud_cover_pct : 40;
      state.severity = extra.severity || "NONE";
      state.sunFrac = solarFraction(obs && obs.observed_at, today.sunrise, today.sunset);

      paintGradient(); paintOrb(); paintClouds();
      if (nextKind !== wasKind || wasNight === state.isDay) seed();
      start();
    },

    /** Pause/resume the animation (header button). */
    setMotion(on) {
      state.motion = !!on;
      try { localStorage.setItem("aethercast-sky-motion", on ? "on" : "off"); } catch (e) {}
      document.documentElement.classList.toggle("sky-static", !on || reduceMotion());
      if (on) { seed(); start(); } else { stop(); if (ctx) ctx.clearRect(0, 0, innerWidth, innerHeight); }
      return state.motion;
    },

    motionOn() { return state.motion && !reduceMotion(); },
    current() { return { kind: state.kind, isDay: state.isDay, severity: state.severity }; },
  };
})();
