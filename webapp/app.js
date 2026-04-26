const LBF_TO_N = 4.44822;
const PSI_TO_PA = 6894.76;
const LBM_TO_KG = 0.453592;
const G0_FT_S2 = 32.174;
const G0_M_S2 = 9.80665;
const MAX_POINTS_DISPLAY = 2500;

/** Plotly: match dashboard dark theme (style.css) — not only plotly_dark template */
const PLOT_DARK = {
  template: "plotly_dark",
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "#0a0a0a",
  colorway: ["#3b82f6", "#10b981", "#f59e0b", "#a78bfa", "#ec4899", "#14b8a6", "#f472b6"],
  font: { color: "#ffffff", family: "'JetBrains Mono', 'Roboto Mono', Consolas, monospace" },
  xaxis: {
    color: "#94a3b8",
    tickfont: { color: "#94a3b8" },
    title: { font: { color: "#94a3b8" } },
    gridcolor: "rgba(42, 42, 42, 0.9)",
    zerolinecolor: "rgba(42, 42, 42, 0.7)",
  },
  yaxis: {
    color: "#94a3b8",
    tickfont: { color: "#94a3b8" },
    title: { font: { color: "#94a3b8" } },
    gridcolor: "rgba(42, 42, 42, 0.9)",
    zerolinecolor: "rgba(42, 42, 42, 0.7)",
  },
  title: { font: { color: "#ffffff" } },
  legend: {
    bgcolor: "rgba(10, 10, 10, 0.5)",
    bordercolor: "#2a2a2a",
    font: { color: "#e2e8f0" },
  },
};

/**
 * @param {object} overrides - title, xaxis, yaxis, shapes, margin, etc.
 */
function darkLayout(overrides = {}) {
  const { xaxis: xo = {}, yaxis: yo = {}, ...rest } = overrides;
  return {
    ...PLOT_DARK,
    ...rest,
    xaxis: { ...PLOT_DARK.xaxis, ...xo },
    yaxis: { ...PLOT_DARK.yaxis, ...yo },
  };
}

const PLOT_CONFIG = { responsive: true, displaylogo: false };

/** rAF: avoid Plotly re-render on every noUi move tick */
let rafNouiTimeseries = null;
let rafNouiAnalysis = null;

/**
 * noUi range must have max > min. For a single time sample, expand slightly so dual handles work.
 * Returns slider range and initial handle positions.
 */
function nudgeTimeRange(tMin, tMax) {
  if (tMax > tMin) {
    return { rangeMin: tMin, rangeMax: tMax, startLo: tMin, startHi: tMax };
  }
  const eps = 1e-6;
  return { rangeMin: tMin, rangeMax: tMin + eps, startLo: tMin, startHi: tMin + eps };
}

function timeStepForNoui(rangeMin, rangeMax) {
  const span = rangeMax - rangeMin;
  if (!Number.isFinite(span) || span <= 0) return 1e-12;
  return Math.max(1e-15, Math.min(span / 2000, span));
}

/** Slider start: use valid numbers from inputs when in range, else full span. */
function nouiStartFromMergedAndInputs(merged, inputStartId, inputEndId) {
  const { tMin, tMax } = merged;
  const { rangeMin, rangeMax, startLo, startHi } = nudgeTimeRange(tMin, tMax);
  const lo = toNumber($(inputStartId)?.value);
  const hi = toNumber($(inputEndId)?.value);
  const eps = 1e-9;
  let s0 = Number.isFinite(lo) && lo >= rangeMin - eps && lo <= rangeMax + eps ? lo : startLo;
  let s1 = Number.isFinite(hi) && hi >= rangeMin - eps && hi <= rangeMax + eps ? hi : startHi;
  if (s0 > s1) [s0, s1] = [s1, s0];
  return { tMin, tMax, rangeMin, rangeMax, step: timeStepForNoui(rangeMin, rangeMax), s0, s1 };
}

/**
 * Start/end time (s) of the longest run where venturi ṁ (kg/s) is ≥ 10% of the series peak
 * (consecutive samples in time order). No venturi / all NaN → [NaN, NaN].
 */
function detectVenturiMdotActiveWindow(mdotArr, tArr) {
  const n = mdotArr.length;
  if (!n || n !== tArr.length) return [NaN, NaN];
  const peak = Math.max(
    -Infinity,
    ...mdotArr.map((m) => (Number.isFinite(m) && m > 0 ? m : -Infinity)),
  );
  if (!Number.isFinite(peak) || peak <= 0) return [NaN, NaN];
  const thr = 0.1 * peak;
  let bestLo = 0;
  let bestLen = 0;
  let i = 0;
  while (i < n) {
    if (!Number.isFinite(mdotArr[i]) || mdotArr[i] < thr || !Number.isFinite(tArr[i])) {
      i += 1;
      continue;
    }
    const j0 = i;
    let j = i;
    while (j < n && Number.isFinite(mdotArr[j]) && mdotArr[j] >= thr && Number.isFinite(tArr[j])) {
      j += 1;
    }
    if (j - j0 > bestLen) {
      bestLen = j - j0;
      bestLo = j0;
    }
    i = j;
  }
  if (bestLen === 0) return [NaN, NaN];
  return [tArr[bestLo], tArr[bestLo + bestLen - 1]];
}

function destroyNouiIfExists(el) {
  if (el && el.noUiSlider) el.noUiSlider.destroy();
}

function initTimeseriesNoui(merged) {
  const el = $("time-range-noui");
  if (!el || typeof noUiSlider === "undefined") return;
  destroyNouiIfExists(el);
  const { tMin, tMax, rangeMin, rangeMax, step, s0, s1 } = nouiStartFromMergedAndInputs(merged, "time-start", "time-end");
  $("time-range-data-min").textContent = String(tMin);
  $("time-range-data-max").textContent = String(tMax);
  $("time-range-noui-hint")?.classList.add("d-none");
  $("time-range-noui-wrap")?.classList.remove("d-none");
  noUiSlider.create(el, {
    start: [s0, s1],
    connect: true,
    range: { min: rangeMin, max: rangeMax },
    step,
  });
  el.noUiSlider.on("update", (values) => {
    $("time-start").value = String(parseFloat(values[0]));
    $("time-end").value = String(parseFloat(values[1]));
    if (rafNouiTimeseries) cancelAnimationFrame(rafNouiTimeseries);
    rafNouiTimeseries = requestAnimationFrame(() => {
      rafNouiTimeseries = null;
      drawTimeseries();
    });
    scheduleConfigSave();
  });
}

function initAnalysisNoui(merged) {
  const el = $("analysis-time-range-noui");
  if (!el || typeof noUiSlider === "undefined") return;
  destroyNouiIfExists(el);
  const { tMin, tMax, rangeMin, rangeMax, step, s0, s1 } = nouiStartFromMergedAndInputs(merged, "analysis-time-start", "analysis-time-end");
  $("analysis-time-data-min").textContent = String(tMin);
  $("analysis-time-data-max").textContent = String(tMax);
  $("analysis-time-range-noui-hint")?.classList.add("d-none");
  $("analysis-time-range-noui-wrap")?.classList.remove("d-none");
  noUiSlider.create(el, {
    start: [s0, s1],
    connect: true,
    range: { min: rangeMin, max: rangeMax },
    step,
  });
  el.noUiSlider.on("update", (values) => {
    $("analysis-time-start").value = String(parseFloat(values[0]));
    $("analysis-time-end").value = String(parseFloat(values[1]));
    if (rafNouiAnalysis) cancelAnimationFrame(rafNouiAnalysis);
    rafNouiAnalysis = requestAnimationFrame(() => {
      rafNouiAnalysis = null;
      drawAnalysisGraph();
    });
    scheduleConfigSave();
  });
}

function syncTimeseriesNouiFromInputs() {
  const el = $("time-range-noui");
  if (!el?.noUiSlider) return;
  const lo = toNumber($("time-start").value);
  const hi = toNumber($("time-end").value);
  if (Number.isFinite(lo) && Number.isFinite(hi) && lo <= hi) {
    el.noUiSlider.set([lo, hi]);
  }
}

function syncAnalysisNouiFromInputs() {
  const el = $("analysis-time-range-noui");
  if (!el?.noUiSlider) return;
  const lo = toNumber($("analysis-time-start").value);
  const hi = toNumber($("analysis-time-end").value);
  if (Number.isFinite(lo) && Number.isFinite(hi) && lo <= hi) {
    el.noUiSlider.set([lo, hi]);
  }
}

/** Keep saved time windows when a new file still spans that [lo,hi]; else use full [tMin,tMax]. */
function mergeSavedTimeOnUpload(pre, startKey, endKey, tMin, tMax) {
  const { rangeMin, rangeMax, startLo, startHi } = nudgeTimeRange(tMin, tMax);
  if (pre?.e) {
    const a = toNumber(pre.e[startKey]);
    const b = toNumber(pre.e[endKey]);
    if (Number.isFinite(a) && Number.isFinite(b) && a < b) {
      if (a >= rangeMin - 1e-9 && b <= rangeMax + 1e-9) return { lo: a, hi: b };
    }
  }
  return { lo: startLo, hi: startHi };
}

const METRICS = [
  "Total thrust (lbf)",
  "Isp (s)",
  "Cf",
  "C* (m/s)",
  "Venturi fuel mdot (kg/s)",
  "Venturi ox mdot (kg/s)",
  "O/F",
  "Burn time",
];

const DASH_CONFIG_KEY = "rocketHotFireDashboardConfigV1";
const DASH_CONFIG_INPUT_IDS = [
  "input-throat-area", "venturi-fuel-rho-constant", "venturi-ox-rho-constant",
  "venturi-fuel-cda", "venturi-fuel-beta", "venturi-ox-cda", "venturi-ox-beta",
  "time-start", "time-end", "analysis-time-start", "analysis-time-end",
];
const DASH_CONFIG_CHECKBOX_IDS = [
  "analysis-regression", "analysis-show-burn",
];
const DASH_CONFIG_SELECT_IDS = [
  "chamber-pressure-select", "fuel-weight-select", "ox-weight-select",
  "venturi-fuel-inlet-select", "venturi-fuel-throat-select",
  "venturi-ox-inlet-select", "venturi-ox-throat-select",
];

const state = {
  dataset: null,
  selectedChannels: [],
  selectedThrustChannels: [],
  perf: null,
  perfMeta: null,
  /** Last parsed localStorage dashboard config; used when CSV loads */
  pendingDashConfig: null,
};

function $(id) { return document.getElementById(id); }

/**
 * Parse a numeric field from CSV or form input.
 * Handles US thousands ("1,234.56"), European ("1.234,56" / "12,3" decimal), NBSP,
 * cell BOM, leading minus, $ / %, and spaces used as thousands (e "1 234,56" rare).
 * Raw Number() yields NaN for comma-separated values — the main reason venturi mdot is all-NaN.
 */
function toNumber(v) {
  if (v === null || v === undefined) return NaN;
  if (typeof v === "number") return Number.isFinite(v) ? v : NaN;
  let s0 = String(v).replace(/^\uFEFF/, "");
  s0 = s0.replace(/[\u00A0\u2000-\u200B\u202F\u2009\uFEFF]+/g, " ").trim();
  if (s0 === "" || s0 === "—" || s0 === "–") return NaN;
  let sign = 1;
  if (s0.startsWith("-") || s0.startsWith("−")) {
    sign = -1;
    s0 = s0.replace(/^[-−]+/, "").trim();
  }
  s0 = s0.replace(/^\$/, "").replace(/\s*%\s*$/, "").trim();
  let s = s0.replace(/(\d)\s+(?=\d)/g, "$1");
  if (/^[\d.]+,\d{1,6}$/.test(s) && s.includes(".")) {
    s = s.replace(/\./g, "").replace(",", ".");
  } else if (/^\d+,\d{1,2}$/.test(s) && !s.includes(".")) {
    s = s.replace(",", ".");
  } else {
    s = s.replace(/,/g, "");
  }
  s = s.trim();
  const x = sign * Number(s);
  return Number.isFinite(x) ? x : NaN;
}

/** Remove BOM from header keys so "Inlet" matches venturi select (Excel often adds \uFEFF to first column). */
function stripBomFromRowKeys(row) {
  if (!row || typeof row !== "object") return row;
  const out = {};
  for (const k of Object.keys(row)) {
    out[k.replace(/^\uFEFF/, "")] = row[k];
  }
  return out;
}

function numericColumns(rows) {
  if (!rows.length) return [];
  return Object.keys(rows[0]).filter((k) => k !== "Time (s)" && rows.some((r) => Number.isFinite(toNumber(r[k]))));
}

function parseTimeSeconds(rows) {
  if (!rows.length) return rows;
  const cols = Object.keys(rows[0]);
  const timeCandidates = cols.filter((c) => /time|timestamp/i.test(c));
  const timeCol = timeCandidates.length ? timeCandidates[0] : cols[0];
  const first = rows[0][timeCol];
  const firstNum = toNumber(first);
  let t0 = null;
  for (const row of rows) {
    let t = toNumber(row[timeCol]);
    if (!Number.isFinite(t)) {
      const d = new Date(row[timeCol]);
      if (!Number.isNaN(d.getTime())) {
        if (t0 === null) t0 = d.getTime();
        t = (d.getTime() - t0) / 1000;
      }
    }
    row["Time (s)"] = Number.isFinite(t) ? t : NaN;
  }
  return rows.filter((r) => Number.isFinite(r["Time (s)"])).sort((a, b) => a["Time (s)"] - b["Time (s)"]);
}

function mergeDatasets(datasets) {
  if (!datasets.length) return { rows: [], tMin: 0, tMax: 0 };
  const key = "Time (s)";
  const map = new Map();
  datasets.forEach((rows, idx) => {
    rows.forEach((row) => {
      const t = row[key];
      if (!map.has(t)) map.set(t, { [key]: t });
      const target = map.get(t);
      Object.entries(row).forEach(([k, v]) => {
        if (k === key) return;
        const name = target[k] === undefined ? k : `${k}_${idx}`;
        target[name] = v;
      });
    });
  });
  const rows = Array.from(map.values()).sort((a, b) => a[key] - b[key]);
  return { rows, tMin: rows.length ? rows[0][key] : 0, tMax: rows.length ? rows[rows.length - 1][key] : 0 };
}

function makeCheckboxList(container, values, selected, onChange) {
  container.innerHTML = "";
  values.forEach((v) => {
    const id = `${container.id}-${v.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
    const div = document.createElement("div");
    div.className = "form-check";
    const input = document.createElement("input");
    input.className = "form-check-input";
    input.type = "checkbox";
    input.id = id;
    input.value = v;
    if (selected.includes(v)) input.checked = true;
    const label = document.createElement("label");
    label.className = "form-check-label";
    label.htmlFor = id;
    label.textContent = v;
    input.addEventListener("change", onChange);
    div.appendChild(input);
    div.appendChild(label);
    container.appendChild(div);
  });
}

function updateThrustSummary() {
  const summary = $("thrust-channels-summary");
  const n = state.selectedThrustChannels.length;
  summary.textContent = n ? `${n} selected: ${state.selectedThrustChannels.join(", ")}` : "Select thrust channels";
}

function initThrustChannelPicker(columns, preselected) {
  const have = (preselected && preselected.length)
    ? preselected.filter((n) => columns.includes(n))
    : [];
  state.selectedThrustChannels = have.slice();
  const checklist = $("thrust-channels-checklist");
  makeCheckboxList(checklist, columns, state.selectedThrustChannels, () => {
    state.selectedThrustChannels = Array.from(document.querySelectorAll("#thrust-channels-checklist input:checked"))
      .map((i) => i.value);
    updateThrustSummary();
    maybeRecomputeAnalysis();
    scheduleConfigSave();
  });
  updateThrustSummary();
}

function setSelectOptions(select, options, keepMultiple = false) {
  const current = keepMultiple ? Array.from(select.selectedOptions).map((o) => o.value) : select.value;
  select.innerHTML = "";
  if (!keepMultiple) {
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "";
    select.appendChild(empty);
  }
  options.forEach((o) => {
    const opt = document.createElement("option");
    opt.value = o;
    opt.textContent = o;
    select.appendChild(opt);
  });
  if (keepMultiple) {
    Array.from(select.options).forEach((o) => { if (current.includes(o.value)) o.selected = true; });
  } else {
    select.value = current;
  }
}

function yAxisLabel(cols) {
  if (!cols.length) return "Value";
  const s = cols.join(" ").toLowerCase();
  const hasP = /(pt|psi|pressure|pa|bar)/.test(s);
  const hasW = /(lc|load|cell|thrust|weight|lbf)/.test(s);
  const hasT = /(tc|temp|thermocouple)/.test(s);
  const labels = [];
  if (hasP) labels.push("Pressure");
  if (hasT) labels.push("Temperature");
  if (hasW) labels.push("Weight");
  return labels.length ? labels.join(", ") : cols.join(", ");
}

function downsample(rows) {
  if (rows.length <= MAX_POINTS_DISPLAY) return rows;
  const out = [];
  for (let i = 0; i < MAX_POINTS_DISPLAY; i++) out.push(rows[Math.floor(i * (rows.length - 1) / (MAX_POINTS_DISPLAY - 1))]);
  return out;
}

function detectBurnWindowFromWeight(rows, weightCol) {
  const x = rows.map((r) => r["Time (s)"]);
  const w = rows.map((r) => toNumber(r[weightCol]));
  if (!x.length) return [NaN, NaN];
  const rate = [];
  const tmid = [];
  for (let i = 1; i < x.length; i++) {
    const dt = x[i] - x[i - 1];
    const dw = w[i] - w[i - 1];
    if (Number.isFinite(dt) && dt > 0 && Number.isFinite(dw)) {
      rate.push(-dw / dt);
      tmid.push((x[i] + x[i - 1]) / 2);
    }
  }
  if (!rate.length) return [NaN, NaN];
  const maxR = Math.max(...rate.filter(Number.isFinite));
  if (!Number.isFinite(maxR) || maxR <= 0) return [NaN, NaN];
  const threshold = 0.1 * maxR;
  const idx = rate.map((v, i) => ({ v, i })).filter((o) => Number.isFinite(o.v) && o.v >= threshold).map((o) => o.i);
  if (!idx.length) return [NaN, NaN];
  return [tmid[idx[0]], tmid[idx[idx.length - 1]]];
}

function computeRegressionSlope(rows, timeCol, yCol, tStart, tEnd) {
  const pts = rows.filter((r) => r[timeCol] >= tStart && r[timeCol] <= tEnd)
    .map((r) => [toNumber(r[timeCol]), toNumber(r[yCol])])
    .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
  if (pts.length < 2) return NaN;
  const n = pts.length;
  const sx = pts.reduce((a, p) => a + p[0], 0);
  const sy = pts.reduce((a, p) => a + p[1], 0);
  const sxy = pts.reduce((a, p) => a + p[0] * p[1], 0);
  const sx2 = pts.reduce((a, p) => a + p[0] * p[0], 0);
  const denom = n * sx2 - sx * sx;
  if (!Number.isFinite(denom) || denom === 0) return NaN;
  return (n * sxy - sx * sy) / denom;
}

/**
 * Incompressible venturi (ideal gas/liquid, low Ma): ṁ = C_d A √[2ρ |ΔP| / (1−β⁴)] (kg/s).
 * β must be the diameter ratio d_throat / d_inlet (not area ratio A_t/A_1 — that would use a different form).
 * P1,P2: static pressures in psi (converted to Pa). cda: C_d·A in m². rho: kg/m³.
 * Matches: mdot = (C_d A) * sqrt( (2 ρ ΔP) / (1 - β^4) ).
 */
function computeVenturiMdot(rows, p1, p2, rho, cda, beta) {
  const out = [];
  if (!p1 || !p2) {
    rows.forEach(() => out.push(NaN));
    return out;
  }
  rows.forEach((r) => {
    const P1 = toNumber(r[p1]);
    const P2 = toNumber(r[p2]);
    // `rho` is the density passed in for this stream only (fuel or ox) — not shared across calls
    if (!Number.isFinite(P1) || !Number.isFinite(P2) || !Number.isFinite(rho) || !Number.isFinite(cda) || !Number.isFinite(beta) || beta <= 0 || beta >= 1 || cda <= 0 || rho <= 0) {
      out.push(NaN);
      return;
    }
    const dp = Math.abs(P1 - P2) * PSI_TO_PA;
    const denom = 1 - Math.pow(beta, 4);
    const val = cda * Math.sqrt(Math.max(0, 2 * dp * rho / denom));
    out.push(Number.isFinite(val) ? val : NaN);
  });
  return out;
}

function getFilteredRows(startId, endId) {
  if (!state.dataset) return [];
  const tStart = toNumber($(startId).value);
  const tEnd = toNumber($(endId).value);
  const lo = Number.isFinite(tStart) ? tStart : state.dataset.tMin;
  const hi = Number.isFinite(tEnd) ? tEnd : state.dataset.tMax;
  return state.dataset.rows.filter((r) => r["Time (s)"] >= lo && r["Time (s)"] <= hi);
}

function drawTimeseries() {
  if (!state.dataset) return;
  const rows = downsample(getFilteredRows("time-start", "time-end"));
  const selected = state.selectedChannels;
  const showRegression = $("analysis-regression").checked;
  const showBurn = $("analysis-show-burn").checked;
  $("timeseries-burn-time-message").textContent = "";
  if (!selected.length) {
    Plotly.newPlot("data-graph", [], darkLayout({ title: "Select channels in the checklist" }), PLOT_CONFIG);
    return;
  }
  const x = rows.map((r) => r["Time (s)"]);
  const traces = [];
  selected.forEach((col) => {
    const y = rows.map((r) => toNumber(r[col]));
    traces.push({ x, y, type: "scatter", mode: "lines", name: col });
    if (showRegression) {
      const pts = x.map((v, i) => [v, y[i]]).filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
      if (pts.length > 1) {
        const slope = computeRegressionSlope(rows, "Time (s)", col, x[0], x[x.length - 1]);
        const meanY = pts.reduce((a, p) => a + p[1], 0) / pts.length;
        const meanX = pts.reduce((a, p) => a + p[0], 0) / pts.length;
        const intercept = meanY - slope * meanX;
        traces.push({ x: pts.map((p) => p[0]), y: pts.map((p) => slope * p[0] + intercept), type: "scatter", mode: "lines", name: `${col} (fit)`, line: { dash: "dash", width: 1.5, color: "red" } });
      }
    }
  });
  const layout = darkLayout({ title: selected.join(", "), xaxis: { title: "Time (s)" }, yaxis: { title: yAxisLabel(selected) }, shapes: [] });
  if (showBurn) {
    const weightCol = numericColumns(rows).find((c) => /tank|weight/i.test(c));
    if (weightCol) {
      const [b0, b1] = detectBurnWindowFromWeight(rows, weightCol);
      if (Number.isFinite(b0) && Number.isFinite(b1) && b1 > b0) {
        layout.shapes.push({ type: "rect", x0: b0, x1: b1, y0: 0, y1: 1, yref: "paper", fillcolor: "rgba(100,149,237,0.25)", line: { width: 0 } });
      } else {
        $("timeseries-burn-time-message").textContent = "Burn time cannot be detected.";
      }
    }
  }
  Plotly.newPlot("data-graph", traces, layout, PLOT_CONFIG);
}

function updateMdotDisplays(meta) {
  const dash = "—";
  if (!meta) {
    ["analysis-burn-time-display", "analysis-fuel-flow-time-display", "analysis-ox-flow-time-display"].forEach(
      (id) => { const el = $(id); if (el) el.textContent = dash; },
    );
    return;
  }
  const spanS = (t0, t1) => (Number.isFinite(t0) && Number.isFinite(t1) && t1 >= t0 ? (t1 - t0).toFixed(3) : dash);
  $("analysis-burn-time-display").textContent = Number.isFinite(meta.burnStart) && Number.isFinite(meta.burnEnd) ? (meta.burnEnd - meta.burnStart).toFixed(3) : dash;
  $("analysis-fuel-flow-time-display").textContent = spanS(meta.venturiFuelFlowStart, meta.venturiFuelFlowEnd);
  $("analysis-ox-flow-time-display").textContent = spanS(meta.venturiOxFlowStart, meta.venturiOxFlowEnd);
}

function getAnalysisHintEl() {
  return $("analysis-calculate-hint");
}

/**
 * Re-run performance math when data + thrust are ready (e.g. venturi / A* / Pc change).
 * Does nothing if those prerequisites are not met. Uses silent recompute (no inline hints).
 */
function maybeRecomputeAnalysis() {
  if (!state.dataset?.rows?.length) return;
  if (!state.selectedThrustChannels?.length) return;
  computePerformance({ silent: true });
}

/**
 * @param {{ silent?: boolean }} [opts] - if silent, do not set analysis-hint (for auto recompute)
 */
function computePerformance(opts = {}) {
  const silent = Boolean(opts.silent);
  const hint = getAnalysisHintEl();
  if (hint) hint.textContent = "";
  const rows = state.dataset?.rows || [];
  if (!rows.length) {
    if (hint && !silent) hint.textContent = "Load CSV data first.";
    return;
  }
  const thrustCols = state.selectedThrustChannels.slice();
  if (!thrustCols.length) {
    if (hint && !silent) hint.textContent = "Select at least one thrust channel (opens under Thrust channels).";
    return;
  }
  const chamber = $("chamber-pressure-select").value;
  const fuelW = $("fuel-weight-select").value;
  const oxW = $("ox-weight-select").value;
  const Astar = toNumber($("input-throat-area").value);

  const totalThrust = rows.map((r) => thrustCols.reduce((a, c) => a + (toNumber(r[c]) || 0), 0));
  const burnPeak = totalThrust.reduce((m, v) => Number.isFinite(v) && v > m ? v : m, -Infinity);
  const burnMaskIdx = totalThrust.map((v, i) => ({ i, v })).filter((o) => Number.isFinite(o.v) && o.v >= 0.1 * burnPeak).map((o) => o.i);
  const burnStart = burnMaskIdx.length ? rows[burnMaskIdx[0]]["Time (s)"] : NaN;
  const burnEnd = burnMaskIdx.length ? rows[burnMaskIdx[burnMaskIdx.length - 1]]["Time (s)"] : NaN;
  const burnDurationS = Number.isFinite(burnStart) && Number.isFinite(burnEnd) ? burnEnd - burnStart : NaN;

  let [fuelStart, fuelEnd] = fuelW ? detectBurnWindowFromWeight(rows, fuelW) : [NaN, NaN];
  let [oxStart, oxEnd] = oxW ? detectBurnWindowFromWeight(rows, oxW) : [NaN, NaN];
  const sFuel = fuelW && Number.isFinite(fuelStart) && Number.isFinite(fuelEnd)
    ? computeRegressionSlope(rows, "Time (s)", fuelW, fuelStart, fuelEnd)
    : NaN;
  const sOx = oxW && Number.isFinite(oxStart) && Number.isFinite(oxEnd)
    ? computeRegressionSlope(rows, "Time (s)", oxW, oxStart, oxEnd)
    : NaN;
  const mDotFuel = Number.isFinite(sFuel) ? Math.abs(sFuel) : NaN;
  const mDotOx = Number.isFinite(sOx) ? Math.abs(sOx) : NaN;
  const mDotFuelKg = Number.isFinite(mDotFuel) ? (mDotFuel / G0_FT_S2) * LBM_TO_KG : 0;
  const mDotOxKg = Number.isFinite(mDotOx) ? (mDotOx / G0_FT_S2) * LBM_TO_KG : 0;

  const vf1 = $("venturi-fuel-inlet-select").value;
  const vf2 = $("venturi-fuel-throat-select").value;
  const vo1 = $("venturi-ox-inlet-select").value;
  const vo2 = $("venturi-ox-throat-select").value;
  const vfRho = toNumber($("venturi-fuel-rho-constant").value);
  const vfCda = toNumber($("venturi-fuel-cda").value);
  const vfBeta = toNumber($("venturi-fuel-beta").value);
  const voRho = toNumber($("venturi-ox-rho-constant").value);
  const voCda = toNumber($("venturi-ox-cda").value);
  const voBeta = toNumber($("venturi-ox-beta").value);
  // Fuel line: fuel inlet+throat pressures, fuel rho (kg/m³), fuel C_dA, fuel β only — no ox values
  const ventFuel = computeVenturiMdot(rows, vf1, vf2, vfRho, vfCda, vfBeta);
  // Oxidizer line: ox channels, ox rho, ox C_dA, ox β only — no fuel values
  const ventOx = computeVenturiMdot(rows, vo1, vo2, voRho, voCda, voBeta);
  const tAll = rows.map((r) => r["Time (s)"]);
  const [venturiFuelFlowStart, venturiFuelFlowEnd] = detectVenturiMdotActiveWindow(ventFuel, tAll);
  const [venturiOxFlowStart, venturiOxFlowEnd] = detectVenturiMdotActiveWindow(ventOx, tAll);
  /** Isp/C* use total ṁ = fuel venturi + ox venturi (kg/s); missing side treated as 0. */
  const totalVenturiMdotKg = (i) => {
    const f = Number.isFinite(ventFuel[i]) ? ventFuel[i] : 0;
    const o = Number.isFinite(ventOx[i]) ? ventOx[i] : 0;
    return f + o;
  };
  /** Inst. ṁ_ox/ṁ_fuel: venturi value when available for that stream, else tank-based kg/s. */
  const ofRatio = (i) => {
    const mf = Number.isFinite(ventFuel[i]) ? ventFuel[i] : mDotFuelKg;
    const mo = Number.isFinite(ventOx[i]) ? ventOx[i] : mDotOxKg;
    if (Number.isFinite(mf) && Number.isFinite(mo) && mf > 0) return mo / mf;
    return NaN;
  };

  state.perf = rows.map((r, i) => {
    const thrustLbf = totalThrust[i];
    const thrustN = thrustLbf * LBF_TO_N;
    const pcPsi = chamber ? toNumber(r[chamber]) : NaN;
    const pcPa = Number.isFinite(pcPsi) ? pcPsi * PSI_TO_PA : NaN;
    const mdotTot = totalVenturiMdotKg(i);
    return {
      "Time (s)": r["Time (s)"],
      "Total thrust (lbf)": thrustLbf,
      "Isp (s)": mdotTot > 0 ? thrustN / (mdotTot * G0_M_S2) : NaN,
      "C* (m/s)": mdotTot > 0 && Number.isFinite(pcPa) && Astar > 0 ? (pcPa * Astar) / mdotTot : NaN,
      "Cf": Number.isFinite(pcPa) && Astar > 0 && pcPa * Astar > 0 ? thrustN / (pcPa * Astar) : NaN,
      "Venturi fuel mdot (kg/s)": ventFuel[i],
      "Venturi ox mdot (kg/s)": ventOx[i],
      "O/F": ofRatio(i),
      "Burn time": burnDurationS,
    };
  });
  state.perfMeta = {
    mDotFuel, mDotOx, burnStart, burnEnd,
    venturiFuelFlowStart, venturiFuelFlowEnd, venturiOxFlowStart, venturiOxFlowEnd,
  };
  updateMdotDisplays(state.perfMeta);
  drawAnalysisGraph();
}

function selectedAnalysisMetrics() {
  return Array.from(document.querySelectorAll("#analysis-metrics-checklist input:checked"))
    .map((i) => String(i.value).trim());
}

function optionListContains(select, val) {
  if (val == null || val === "") return false;
  return Array.from(select.options).some((o) => o.value === String(val));
}

function getMetricsInitialSelected(cfg) {
  if (cfg?.analysisMetrics?.length) {
    const s = cfg.analysisMetrics.filter((m) => METRICS.includes(m));
    if (s.length) return s;
  }
  return [...METRICS];
}

function applyDashboardConfigFields(cfg) {
  if (!cfg?.e) return;
  for (const id of DASH_CONFIG_INPUT_IDS) {
    const n = $(id);
    if (!n) continue;
    if (cfg.e[id] === undefined) continue;
    n.value = cfg.e[id] == null ? "" : String(cfg.e[id]);
  }
  for (const id of DASH_CONFIG_CHECKBOX_IDS) {
    const n = $(id);
    if (!n) continue;
    if (cfg.e[id] === undefined) continue;
    n.checked = Boolean(cfg.e[id]);
  }
  for (const id of DASH_CONFIG_SELECT_IDS) {
    const n = $(id);
    if (!n) continue;
    const v = cfg.e[id];
    if (v == null || v === "") {
      n.value = "";
      continue;
    }
    if (optionListContains(n, v)) n.value = String(v);
  }
}

function getDashboardConfigObject() {
  const e = {};
  DASH_CONFIG_INPUT_IDS.forEach((id) => {
    const n = $(id);
    if (n) e[id] = n.value;
  });
  DASH_CONFIG_CHECKBOX_IDS.forEach((id) => {
    const n = $(id);
    if (n) e[id] = n.checked;
  });
  DASH_CONFIG_SELECT_IDS.forEach((id) => {
    const n = $(id);
    if (n) e[id] = n.value;
  });
  const dataFromChecklist = Array.from(document.querySelectorAll("#data-checklist input:checked")).map((i) => i.value);
  const dataChannels = dataFromChecklist.length
    ? dataFromChecklist
    : (state.selectedChannels && state.selectedChannels.length ? state.selectedChannels.slice() : (state.pendingDashConfig?.dataChannels || []));
  const metricsPicked = selectedAnalysisMetrics();
  return {
    v: 1,
    e,
    thrust: (state.selectedThrustChannels && state.selectedThrustChannels.length)
      ? state.selectedThrustChannels.slice()
      : (Array.isArray(state.pendingDashConfig?.thrust) ? state.pendingDashConfig.thrust.slice() : []),
    dataChannels,
    analysisMetrics: metricsPicked.length
      ? metricsPicked
      : (Array.isArray(state.pendingDashConfig?.analysisMetrics) ? state.pendingDashConfig.analysisMetrics : []),
  };
}

let dashSaveTimer;
function scheduleConfigSave() {
  if (dashSaveTimer) clearTimeout(dashSaveTimer);
  dashSaveTimer = setTimeout(() => {
    try {
      const o = getDashboardConfigObject();
      localStorage.setItem(DASH_CONFIG_KEY, JSON.stringify(o));
      state.pendingDashConfig = o;
    } catch (err) {
      console.warn("Could not save dashboard config", err);
    }
  }, 400);
}

function loadSavedDashboardConfig() {
  try {
    const t = localStorage.getItem(DASH_CONFIG_KEY);
    if (!t) return null;
    const o = JSON.parse(t);
    if (o && o.v === 1 && o.e && typeof o.e === "object") return o;
    return null;
  } catch (err) {
    return null;
  }
}

function drawAnalysisGraph() {
  if (!state.perf?.length) {
    Plotly.newPlot("analysis-graph", [], darkLayout({ title: "Click Calculate (Inputs) to compute performance metrics" }), PLOT_CONFIG);
    return;
  }
  const metrics = selectedAnalysisMetrics();
  if (!metrics.length) {
    Plotly.newPlot("analysis-graph", [], darkLayout({ title: "Check at least one item under Plot Metrics" }), PLOT_CONFIG);
    return;
  }
  const rows = state.perf.filter((r) => {
    const lo = toNumber($("analysis-time-start").value);
    const hi = toNumber($("analysis-time-end").value);
    const t = r["Time (s)"];
    return t >= (Number.isFinite(lo) ? lo : -Infinity) && t <= (Number.isFinite(hi) ? hi : Infinity);
  });
  const ds = downsample(rows);
  if (!ds.length) {
    Plotly.newPlot("analysis-graph", [], darkLayout({ title: "No samples in the selected analysis time window" }), PLOT_CONFIG);
    return;
  }
  const x = ds.map((r) => r["Time (s)"]);
  const first = ds[0] || {};
  const hasThrust = metrics.includes("Total thrust (lbf)");
  const useDualY = hasThrust && metrics.some((m) => m !== "Total thrust (lbf)");
  const yLeft = "y";
  const yRight = "y2";
  const annotations = [];
  const traces = [];
  let annIdx = 0;
  metrics
    .filter((m) => m in first)
    .forEach((m) => {
      const y = ds.map((r) => toNumber(r[m]));
      if (!y.some(Number.isFinite) && annIdx < 5) {
        annotations.push({
          text: `All NaN: ${m} — see diagnostics below the Calculate button`,
          xref: "paper",
          yref: "paper",
          x: 0.01,
          y: 0.98 - annIdx * 0.04,
          showarrow: false,
          font: { color: "#f59e0b", size: 11 },
        });
        annIdx += 1;
      }
      const t = { x, y, type: "scatter", mode: "lines", name: m, connectgaps: true };
      if (useDualY) {
        t.yaxis = m === "Total thrust (lbf)" ? yLeft : yRight;
      }
      traces.push(t);
    });
  const title = metrics.length
    ? (metrics.length > 4 ? `Performance (${metrics.length} series)` : metrics.join(" · "))
    : "Select metrics in Plot Metrics";
  const layout = darkLayout({
    title,
    xaxis: { title: "Time (s)" },
    yaxis: { title: hasThrust ? "Thrust (lbf) — left" : "Value" },
    showlegend: true,
    shapes: [],
    ...(annotations.length && { annotations }),
    ...(useDualY && {
      yaxis2: {
        title: { text: "Isp, C*, venturi, burn (right scale)", font: { color: "#94a3b8" } },
        overlaying: "y",
        side: "right",
        showgrid: true,
        gridcolor: "rgba(42, 42, 42, 0.6)",
        color: "#94a3b8",
        tickfont: { color: "#94a3b8" },
      },
    }),
  });
  if (metrics.includes("Burn time") && state.perfMeta && Number.isFinite(state.perfMeta.burnStart) && Number.isFinite(state.perfMeta.burnEnd)) {
    layout.shapes.push({ type: "rect", x0: state.perfMeta.burnStart, x1: state.perfMeta.burnEnd, y0: 0, y1: 1, yref: "paper", fillcolor: "rgba(100,149,237,0.25)", line: { width: 0 } });
  }
  if (!traces.length) {
    Plotly.newPlot("analysis-graph", [], darkLayout({ title: "No plottable series (check selected metrics)" }), PLOT_CONFIG);
    return;
  }
  Plotly.newPlot("analysis-graph", traces, layout, PLOT_CONFIG);
}

function downloadPlot(divId, filename) {
  Plotly.downloadImage(divId, { format: "png", filename, scale: 2 });
}

function bindEvents() {
  $("upload-data").addEventListener("change", async (e) => {
    const pre = getDashboardConfigObject();
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    const datasets = [];
    for (const file of files) {
      const text = await file.text();
      const parsed = Papa.parse(text, { header: true, dynamicTyping: false, skipEmptyLines: true });
      const raw = (parsed.data || []).map(stripBomFromRowKeys);
      const rows = parseTimeSeconds(raw);
      datasets.push(rows);
    }
    const merged = mergeDatasets(datasets);
    state.dataset = merged;
    state.perf = null;
    state.perfMeta = null;
    if (getAnalysisHintEl()) getAnalysisHintEl().textContent = "";
    updateMdotDisplays(null);
    const { tMin, tMax } = merged;
    const tPair = mergeSavedTimeOnUpload(pre, "time-start", "time-end", tMin, tMax);
    const aPair = mergeSavedTimeOnUpload(pre, "analysis-time-start", "analysis-time-end", tMin, tMax);
    $("time-start").value = tPair.lo;
    $("time-end").value = tPair.hi;
    $("analysis-time-start").value = aPair.lo;
    $("analysis-time-end").value = aPair.hi;
    initTimeseriesNoui(merged);
    initAnalysisNoui(merged);
    const cols = numericColumns(merged.rows);
    const preData = (pre.dataChannels || []).filter((c) => cols.includes(c));
    state.selectedChannels = preData.length ? preData.slice() : [];
    makeCheckboxList($("data-checklist"), cols, state.selectedChannels, () => {
      state.selectedChannels = Array.from(document.querySelectorAll("#data-checklist input:checked")).map((i) => i.value);
      drawTimeseries();
      scheduleConfigSave();
    });
    initThrustChannelPicker(cols, pre.thrust);
    const selectIds = [
      "chamber-pressure-select", "fuel-weight-select", "ox-weight-select",
      "venturi-fuel-inlet-select", "venturi-fuel-throat-select", "venturi-ox-inlet-select", "venturi-ox-throat-select",
    ];
    selectIds.forEach((id) => {
      setSelectOptions($(id), cols);
      if (pre?.e?.[id] && optionListContains($(id), pre.e[id])) $(id).value = String(pre.e[id]);
    });
    makeCheckboxList($("analysis-metrics-checklist"), METRICS, getMetricsInitialSelected(pre), () => {
      drawAnalysisGraph();
      scheduleConfigSave();
    });
    $("upload-filenames").textContent = `Loaded: ${files.map((f) => f.name).join(", ")}`;
    drawTimeseries();
    drawAnalysisGraph();
    scheduleConfigSave();
  });

  $("clear-channels-button").addEventListener("click", () => {
    state.selectedChannels = [];
    document.querySelectorAll("#data-checklist input").forEach((i) => { i.checked = false; });
    drawTimeseries();
    scheduleConfigSave();
  });
  $("reset-button").addEventListener("click", () => {
    if (!state.dataset) return;
    const { tMin, tMax } = state.dataset;
    const el = $("time-range-noui");
    if (el?.noUiSlider) {
      const { startLo, startHi } = nudgeTimeRange(tMin, tMax);
      el.noUiSlider.set([startLo, startHi]);
    } else {
      $("time-start").value = tMin;
      $("time-end").value = tMax;
    }
    drawTimeseries();
    scheduleConfigSave();
  });
  $("analysis-reset-button").addEventListener("click", () => {
    if (!state.dataset) return;
    const { tMin, tMax } = state.dataset;
    const el = $("analysis-time-range-noui");
    if (el?.noUiSlider) {
      const { startLo, startHi } = nudgeTimeRange(tMin, tMax);
      el.noUiSlider.set([startLo, startHi]);
    } else {
      $("analysis-time-start").value = tMin;
      $("analysis-time-end").value = tMax;
    }
    drawAnalysisGraph();
    scheduleConfigSave();
  });
  ["time-start", "time-end"].forEach((id) => $(id).addEventListener("input", () => {
    drawTimeseries();
    syncTimeseriesNouiFromInputs();
    scheduleConfigSave();
  }));
  ["analysis-regression", "analysis-show-burn"].forEach((id) => $(id).addEventListener("input", () => {
    drawTimeseries();
    scheduleConfigSave();
  }));
  ["analysis-time-start", "analysis-time-end"].forEach((id) => $(id).addEventListener("input", () => {
    drawAnalysisGraph();
    syncAnalysisNouiFromInputs();
    scheduleConfigSave();
  }));
  $("analysis-calculate-button").addEventListener("click", computePerformance);
  $("save-data-graph-btn").addEventListener("click", () => downloadPlot("data-graph", "timeseries"));
  $("save-analysis-graph-btn").addEventListener("click", () => downloadPlot("analysis-graph", "performance_analysis"));

  [
    "input-throat-area",
    "chamber-pressure-select",
    "fuel-weight-select",
    "ox-weight-select",
    "venturi-fuel-rho-constant",
    "venturi-ox-rho-constant",
    "venturi-fuel-cda",
    "venturi-fuel-beta",
    "venturi-ox-cda",
    "venturi-ox-beta",
  ].forEach((id) => { $(id).addEventListener("change", () => { maybeRecomputeAnalysis(); scheduleConfigSave(); }); });
  [
    "venturi-fuel-inlet-select", "venturi-fuel-throat-select",
    "venturi-ox-inlet-select", "venturi-ox-throat-select",
  ].forEach((id) => $(id).addEventListener("change", () => { maybeRecomputeAnalysis(); scheduleConfigSave(); }));
  const _cfg0 = loadSavedDashboardConfig();
  if (_cfg0) {
    state.pendingDashConfig = _cfg0;
    applyDashboardConfigFields(_cfg0);
    if (Array.isArray(_cfg0.dataChannels)) state.selectedChannels = _cfg0.dataChannels.slice();
    if (Array.isArray(_cfg0.thrust)) state.selectedThrustChannels = _cfg0.thrust.slice();
  }
  makeCheckboxList($("analysis-metrics-checklist"), METRICS, getMetricsInitialSelected(_cfg0), () => {
    drawAnalysisGraph();
    scheduleConfigSave();
  });
}

bindEvents();

Plotly.newPlot("data-graph", [], darkLayout({ title: "Select channels in the checklist" }), PLOT_CONFIG);
Plotly.newPlot("analysis-graph", [], darkLayout({ title: "Click Calculate (Inputs) to compute performance metrics" }), PLOT_CONFIG);
