"use strict";

// Fixed band order, matching the backend.
const BAND_META = [
  { name: "delta", label: "delta", range: "1-4 Hz" },
  { name: "theta", label: "theta", range: "4-8 Hz" },
  { name: "alpha", label: "alpha", range: "8-13 Hz" },
  { name: "beta", label: "beta", range: "13-30 Hz" },
  { name: "gamma", label: "gamma", range: "30-50 Hz" },
];

const ACCENT = "#a4f30b";
const MUTED = "#646669";
const TARGET_RATIO = 10; // peak theta-gamma coupling

// --- Elements ---
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const ratioEl = document.getElementById("ratio");
const cogFill = document.getElementById("cognition-fill");
const cogPct = document.getElementById("cognition-pct");
const dominantEl = document.getElementById("dominant");
const dominantBandEl = document.getElementById("dominant-band");
const dominantMeaningEl = document.getElementById("dominant-meaning");
const updatedEl = document.getElementById("updated");
const bandList = document.getElementById("band-list");

const durationInput = document.getElementById("duration");
const sessionBtn = document.getElementById("session-btn");
const shotBtn = document.getElementById("shot-btn");
const sessionProgress = document.getElementById("session-progress");
const sessionProgressFill = document.getElementById("session-progress-fill");
const sessionReadout = document.getElementById("session-readout");
const avgRatioEl = document.getElementById("avg-ratio");
const avgCogEl = document.getElementById("avg-cog");
const sampleCountEl = document.getElementById("sample-count");
const elapsedEl = document.getElementById("elapsed");
const captureCard = document.getElementById("capture-card");
const thetaFreqEl = document.getElementById("theta-freq");
const gammaFreqEl = document.getElementById("gamma-freq");
const testEnabledInput = document.getElementById("test-enabled");
const testFrequencyInput = document.getElementById("test-frequency");
const testNoiseInput = document.getElementById("test-noise");
const testAmplitudeInput = document.getElementById("test-amplitude");
const applyTestSignalBtn = document.getElementById("apply-test-signal");
const testSummaryEl = document.getElementById("test-summary");

// PAC panel
const pacVerdict = document.getElementById("pac-verdict");
const pacSupporting = document.getElementById("pac-supporting");
const pacMedianZ = document.getElementById("pac-medianz");
const pacWindowEl = document.getElementById("pac-window");
const pacHarmonic = document.getElementById("pac-harmonic");
const pacTbody = document.getElementById("pac-tbody");
const pacEstimator = document.getElementById("pac-estimator");

// Criticality panel (separate metric from PAC)
const critVerdict = document.getElementById("crit-verdict");
const critMarker = document.getElementById("crit-marker");
const critState = document.getElementById("crit-state");
const critConfidence = document.getElementById("crit-confidence");
const critExponent = document.getElementById("crit-exponent");
const critArousal = document.getElementById("crit-arousal");
const critTrident = document.getElementById("crit-trident");
const critEstimator = document.getElementById("crit-estimator");

// --- Coupling strength: 0 at ratio 0, full (100%) at ratio 10 and above ---
function cognitionScore(ratio) {
  const score = ratio / TARGET_RATIO;
  return Math.max(0, Math.min(1, score)) * 100;
}

// --- PAC panel rendering -------------------------------------------------
function fmt(v, d = 2) {
  return v === null || v === undefined ? "\u2014" : Number(v).toFixed(d);
}

function riskClass(level) {
  if (level === "high") return "risk-bad";
  if (level === "medium") return "risk-warn";
  if (level === "low") return "risk-good";
  return "";
}

function verdictClass(verdict) {
  const v = (verdict || "").toLowerCase();
  if (v.includes("significant theta-gamma pac")) return "good";
  if (v.includes("rejected") || v.includes("not interpretable")) return "bad";
  if (v.includes("harmonic")) return "warn";
  return "neutral";
}

function channelStatusLabel(c) {
  if (c.status === "excluded") return "excluded";
  if (c.status === "theta_unreliable") return "\u03b8 unreliable";
  if (c.status === "fit_poor") return "fit poor";
  if (c.valid && c.pac) return c.pac.significant ? "PAC" : "n.s.";
  return c.status || "\u2014";
}

function updatePac(pacData) {
  if (!pacData || !pacData.summary) return;
  const s = pacData.summary;

  pacVerdict.textContent = s.verdict || "\u2014";
  pacVerdict.className = "pac-verdict " + verdictClass(s.verdict);
  if (s.estimator) pacEstimator.textContent = s.estimator;
  pacSupporting.textContent = s.supporting_label || "\u2014";
  pacMedianZ.textContent = fmt(s.median_z, 2);
  pacWindowEl.textContent = s.window_quality || "\u2014";
  pacHarmonic.textContent = s.harmonic_risk || "\u2014";
  pacHarmonic.className = "stat-value " + riskClass(s.harmonic_risk);

  pacTbody.innerHTML = "";
  for (const c of pacData.channels || []) {
    const theta = c.theta || {};
    const gamma = c.gamma || {};
    const p = c.pac || {};
    const harm = c.harmonic || {};
    const tr = document.createElement("tr");
    tr.className = c.valid ? (p.significant ? "pac-sig" : "") : "pac-invalid";
    const gType = gamma.type ? gamma.type.replace("/none", "") : "\u2014";
    tr.innerHTML =
      `<td>${c.channel + 1}</td>` +
      `<td>${theta.accepted ? fmt(theta.center_hz, 1) : "\u2014"}</td>` +
      `<td>${gamma.accepted ? fmt(gamma.center_hz, 1) : "\u2014"}</td>` +
      `<td>${c.valid ? gType : "\u2014"}</td>` +
      `<td>${c.valid ? fmt(p.modulation_index, 4) : "\u2014"}</td>` +
      `<td>${c.valid ? fmt(p.z, 2) : "\u2014"}</td>` +
      `<td>${c.valid ? fmt(p.percentile, 1) : "\u2014"}</td>` +
      `<td>${c.valid ? fmt(p.preferred_phase_rad, 2) : "\u2014"}</td>` +
      `<td class="${riskClass(harm.level)}">${harm.level || "\u2014"}</td>` +
      `<td class="pac-status">${channelStatusLabel(c)}</td>`;
    pacTbody.appendChild(tr);
  }
}

// --- Criticality panel rendering (independent of PAC) --------------------
function critStateClass(state) {
  if (state === "near-critical") return "good";
  if (state === "subcritical" || state === "supercritical") return "warn";
  return "neutral";
}

function updateCriticality(critData) {
  if (!critData || !critData.summary) return;
  const s = critData.summary;

  critVerdict.textContent = s.label || "\u2014";
  critVerdict.className = "pac-verdict " + critStateClass(s.state);
  if (s.estimator) critEstimator.textContent = s.estimator;
  critState.textContent = s.state || "\u2014";
  critConfidence.textContent = s.confidence_label
    ? `${s.confidence_label} (${fmt(s.confidence, 2)})`
    : "\u2014";
  critExponent.textContent = s.aperiodic_exponent !== undefined
    ? fmt(s.aperiodic_exponent, 2) : "\u2014";
  critArousal.textContent = s.arousal || "\u2014";

  // Position the marker on the axis. deviation d in roughly [-2.5, 2.5];
  // map to 0-100% where 50% is exactly near-critical.
  if (typeof s.deviation === "number") {
    const pct = Math.max(0, Math.min(100, 50 + (s.deviation / 2.5) * 50));
    critMarker.style.left = pct + "%";
    critMarker.style.visibility = "visible";
  } else {
    critMarker.style.visibility = "hidden";
  }

  if (s.trident) {
    critTrident.textContent =
      `Trident remedy: entrain ${s.trident.suggested_band} ` +
      `(${s.trident.entrainment_prong}) to ${s.trident.goal}.`;
  } else {
    critTrident.textContent = "\u2014";
  }
}

// --- Build band list rows ---
const bandRows = {};
for (const band of BAND_META) {
  const li = document.createElement("li");
  li.dataset.name = band.name;
  li.innerHTML = `
    <span class="band-name">${band.label}</span>
    <span class="band-range">${band.range}</span>
    <span class="band-bar"><div></div></span>
    <span class="band-val">—</span>`;
  bandList.appendChild(li);
  bandRows[band.name] = {
    li,
    bar: li.querySelector(".band-bar > div"),
    val: li.querySelector(".band-val"),
  };
}

// --- Per-channel bandpower detail (dBµV, Unicorn-style bar graph) ---------
// A grouped horizontal bar chart: one row per frequency band, one bar per
// active channel. Rebuilt lazily so it adapts to the board's channel count.
const BAND_DETAIL_FLOOR_DB = -10;

// Distinct, readable palette cycled across channels.
const CHANNEL_COLORS = [
  "#a4f30b", "#4ea1ff", "#ff7ad9", "#ffb01f", "#2fd0c5",
  "#f5421f", "#b388ff", "#7ed957", "#ff5c8a", "#3ad1ff",
  "#ffd23f", "#9b8cff", "#62e0a1", "#ff8f4d", "#5ad0ff", "#e879f9",
];

let bandDetailChart = null;
let bandDetailLayout = null; // { bands: [...], channels: N }

function bandDetailNeedsRebuild(detail) {
  if (!bandDetailChart || !bandDetailLayout) return true;
  if (bandDetailLayout.channels !== (detail.channels || []).length) return true;
  if (bandDetailLayout.bands.length !== (detail.bands || []).length) return true;
  return false;
}

function buildBandDetailChart(detail) {
  const bands = detail.bands || [];
  const labels = detail.band_labels || bands;
  const channels = detail.channels || [];
  bandDetailLayout = { bands, channels: channels.length };

  const datasets = channels.map((ch, i) => ({
    label: "Ch" + (ch.channel + 1),
    data: bands.map(() => BAND_DETAIL_FLOOR_DB),
    backgroundColor: CHANNEL_COLORS[i % CHANNEL_COLORS.length],
    borderWidth: 0,
    borderRadius: 2,
    barPercentage: 0.92,
    categoryPercentage: 0.86,
  }));

  if (bandDetailChart) bandDetailChart.destroy();
  bandDetailChart = new Chart(document.getElementById("band-detail-chart"), {
    type: "bar",
    data: { labels: labels.slice(), datasets },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        x: {
          min: BAND_DETAIL_FLOOR_DB,
          suggestedMax: 30,
          grid: { color: "rgba(255,255,255,0.05)" },
          ticks: { color: MUTED },
          title: { display: true, text: "power (dBµV)", color: MUTED },
        },
        y: {
          grid: { display: false },
          ticks: { color: MUTED },
        },
      },
      plugins: {
        legend: {
          display: true,
          position: "bottom",
          labels: { color: MUTED, boxWidth: 10, boxHeight: 10, font: { size: 10 } },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${Number(ctx.parsed.x).toFixed(1)} dBµV`,
          },
        },
      },
    },
  });
}

function updateBandDetail(detail) {
  if (!detail || !Array.isArray(detail.channels)) return;
  if (bandDetailNeedsRebuild(detail)) buildBandDetailChart(detail);
  if (!bandDetailChart) return;

  const channels = detail.channels;
  channels.forEach((ch, i) => {
    const ds = bandDetailChart.data.datasets[i];
    if (!ds) return;
    const power = ch.power_db || [];
    ds.data = power.map((v) =>
      v === null || v === undefined ? BAND_DETAIL_FLOOR_DB : v
    );
    // Dim removed or bad channels so a noisy electrode never misleads.
    const dim = ch.removed || ch.quality === "bad" || ch.quality === "unknown";
    const base = CHANNEL_COLORS[i % CHANNEL_COLORS.length];
    ds.backgroundColor = dim ? withAlpha(base, 0.22) : base;
  });
  bandDetailChart.update();
}

function withAlpha(hex, alpha) {
  const m = hex.replace("#", "");
  const r = parseInt(m.slice(0, 2), 16);
  const g = parseInt(m.slice(2, 4), 16);
  const b = parseInt(m.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}


// --- Live ratio chart ---
const MAX_POINTS = 60;
const chart = new Chart(document.getElementById("chart"), {
  type: "line",
  data: {
    labels: [],
    datasets: [
      {
        label: "γ:θ ratio",
        data: [],
        borderColor: ACCENT,
        backgroundColor: "rgba(164, 243, 11, 0.12)",
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.3,
        fill: true,
      },
    ],
  },
  options: {
    responsive: true,
    animation: false,
    scales: {
      y: {
        beginAtZero: true,
        suggestedMax: 20,
        grid: { color: "rgba(255,255,255,0.05)" },
        ticks: { color: MUTED },
      },
      x: { display: false },
    },
    plugins: {
      legend: { display: false },
      annotation: false,
    },
  },
  plugins: [
    {
      // Draw the target line at ratio 10.
      id: "targetLine",
      afterDraw(c) {
        const y = c.scales.y.getPixelForValue(TARGET_RATIO);
        const { left, right } = c.chartArea;
        const ctx = c.ctx;
        ctx.save();
        ctx.strokeStyle = "rgba(209, 208, 197, 0.3)";
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(right, y);
        ctx.stroke();
        ctx.restore();
      },
    },
  ],
});

function pushRatio(ratio) {
  const data = chart.data.datasets[0].data;
  const labels = chart.data.labels;
  data.push(ratio);
  labels.push("");
  if (data.length > MAX_POINTS) {
    data.shift();
    labels.shift();
  }
  chart.update();
}

// --- Frequency band graphs ---
let currentBandChart = null;
const bandChartData = {
  delta: [],
  theta: [],
  alpha: [],
  beta: [],
  gamma: [],
};
let activeBand = "delta";

const bandChart = new Chart(document.getElementById("band-chart"), {
  type: "line",
  data: {
    labels: [],
    datasets: [
      {
        label: "Band Power",
        data: [],
        borderColor: ACCENT,
        backgroundColor: "rgba(164, 243, 11, 0.12)",
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.3,
        fill: true,
      },
    ],
  },
  options: {
    responsive: true,
    animation: false,
    scales: {
      y: {
        beginAtZero: true,
        suggestedMax: 1,
        grid: { color: "rgba(255,255,255,0.05)" },
        ticks: { color: MUTED },
      },
      x: { display: false },
    },
    plugins: {
      legend: { display: false },
    },
  },
});

// --- Overall frequency chart: real data vs test data ---
const spectrumChart = new Chart(document.getElementById("spectrum-chart"), {
  type: "line",
  data: {
    labels: [],
    datasets: [
      {
        label: "real",
        data: [],
        borderColor: "#a4f30b",
        backgroundColor: "rgba(164, 243, 11, 0.16)",
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.25,
        fill: false,
      },
      {
        label: "test",
        data: [],
        borderColor: "#4ea1ff",
        backgroundColor: "rgba(78, 161, 255, 0.16)",
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.25,
        fill: false,
      },
    ],
  },
  options: {
    responsive: true,
    animation: false,
    scales: {
      y: {
        min: 0,
        max: 1,
        grid: { color: "rgba(255,255,255,0.05)" },
        ticks: { color: MUTED },
        title: { display: true, text: "normalized power", color: MUTED },
      },
      x: {
        grid: { color: "rgba(255,255,255,0.05)" },
        ticks: { color: MUTED, maxTicksLimit: 10 },
        title: { display: true, text: "frequency (Hz)", color: MUTED },
      },
    },
    plugins: {
      legend: {
        display: true,
        labels: { color: MUTED },
      },
    },
  },
});

function updateSpectrumChart(spectrum) {
  if (!spectrum || !Array.isArray(spectrum.frequencies)) return;
  const labels = spectrum.frequencies.map((f) => Number(f).toFixed(1));
  spectrumChart.data.labels = labels;
  spectrumChart.data.datasets[0].data = Array.isArray(spectrum.real_power)
    ? spectrum.real_power
    : [];
  spectrumChart.data.datasets[1].data = Array.isArray(spectrum.test_power)
    ? spectrum.test_power
    : [];
  spectrumChart.update();
}

function renderTestSummary(cfg) {
  if (!cfg) {
    testSummaryEl.textContent = "test signal: unavailable";
    return;
  }
  const mode = cfg.enabled ? "enabled" : "disabled";
  testSummaryEl.textContent =
    `test signal: ${mode} | ${Number(cfg.frequency_hz).toFixed(1)} Hz | ` +
    `noise ${Number(cfg.noise_level).toFixed(2)} | amp ${Number(cfg.amplitude).toFixed(2)}`;
}

function populateTestSignalForm(cfg) {
  if (!cfg) return;
  testEnabledInput.checked = Boolean(cfg.enabled);
  testFrequencyInput.value = Number(cfg.frequency_hz).toFixed(1);
  testNoiseInput.value = Number(cfg.noise_level).toFixed(2);
  testAmplitudeInput.value = Number(cfg.amplitude).toFixed(2);
  renderTestSummary(cfg);
}

async function loadTestSignalSettings() {
  try {
    const res = await fetch("/test-signal", { cache: "no-store" });
    if (!res.ok) throw new Error("settings fetch failed");
    const cfg = await res.json();
    populateTestSignalForm(cfg);
  } catch (_) {
    renderTestSummary(null);
  }
}

async function applyTestSignalSettings() {
  applyTestSignalBtn.disabled = true;
  applyTestSignalBtn.textContent = "applying...";
  try {
    const payload = {
      enabled: testEnabledInput.checked,
      frequency_hz: Number(testFrequencyInput.value),
      noise_level: Number(testNoiseInput.value),
      amplitude: Number(testAmplitudeInput.value),
    };
    const res = await fetch("/test-signal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error("settings update failed");
    const cfg = await res.json();
    populateTestSignalForm(cfg);
    showToast("Test signal settings applied.", "success");
  } catch (_) {
    testSummaryEl.textContent = "test signal: failed to apply settings";
    showToast("Failed to apply test signal settings.", "error");
  } finally {
    applyTestSignalBtn.textContent = "apply";
    applyTestSignalBtn.disabled = false;
  }
}

applyTestSignalBtn.addEventListener("click", applyTestSignalSettings);
loadTestSignalSettings();

currentBandChart = bandChart;

function pushBandPower(bandName, power) {
  bandChartData[bandName].push(power);
  if (bandChartData[bandName].length > MAX_POINTS) {
    bandChartData[bandName].shift();
  }
  
  if (bandName === activeBand) {
    updateBandChartDisplay();
  }
}

function updateBandChartDisplay() {
  const data = bandChartData[activeBand];
  bandChart.data.datasets[0].data = [...data];
  bandChart.data.labels = Array(data.length).fill("");
  bandChart.update();
}

// Band tab switching
document.querySelectorAll(".band-tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".band-tab-btn").forEach((b) => {
      b.classList.remove("active");
    });
    btn.classList.add("active");
    activeBand = btn.dataset.band;
    updateBandChartDisplay();
  });
});

// --- Electrode positions: real Unicorn Hybrid Black layout (viewBox 0-200, 0-240) ---
// 4 down the midline (Fz, Cz, Pz, Oz), 2 in the centre of each hemisphere
// (C3, C4), and 3 across the back (PO7, Oz, PO8).
const ELECTRODE_POSITIONS = [
  { ch: 0, label: "Ch1", x: 100, y: 84 },   // midline, top
  { ch: 1, label: "Ch2", x: 64,  y: 120 },  // left hemisphere centre
  { ch: 2, label: "Ch3", x: 100, y: 120 },  // midline
  { ch: 3, label: "Ch4", x: 136, y: 120 },  // right hemisphere centre
  { ch: 4, label: "Ch5", x: 100, y: 150 },  // midline
  { ch: 5, label: "Ch6", x: 70,  y: 176 },  // left lower
  { ch: 6, label: "Ch7", x: 100, y: 180 },  // midline, bottom
  { ch: 7, label: "Ch8", x: 130, y: 176 },  // right lower
];

// Channels the user has manually removed by clicking their indicator.
const removedChannels = new Set();

function createElectrodeMap() {
  const container = document.getElementById("electrode-indicators");
  container.innerHTML = "";

  for (const pos of ELECTRODE_POSITIONS) {
    const dotWrapper = document.createElement("div");
    dotWrapper.className = "electrode-wrapper";
    dotWrapper.id = `electrode-${pos.ch}`;
    // Hidden until a live channel for this position is seen in a payload.
    dotWrapper.style.display = "none";

    const label = document.createElement("div");
    label.className = "electrode-label";
    label.textContent = pos.label;

    const dot = document.createElement("div");
    dot.className = "electrode-dot unknown";

    // Position using percentage of parent.
    dotWrapper.style.left = pos.x / 200 * 100 + "%";
    dotWrapper.style.top = pos.y / 240 * 100 + "%";

    dotWrapper.appendChild(label);
    dotWrapper.appendChild(dot);

    // Click (or keyboard) to remove/add the channel.
    dotWrapper.setAttribute("role", "button");
    dotWrapper.setAttribute("tabindex", "0");
    dotWrapper.setAttribute("aria-label",
      `${pos.label} electrode — activate to remove or restore this channel`);
    dotWrapper.addEventListener("click", () => toggleChannelRemoved(pos.ch));
    dotWrapper.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggleChannelRemoved(pos.ch);
      }
    });

    container.appendChild(dotWrapper);
  }
}

function toggleChannelRemoved(ch) {
  if (removedChannels.has(ch)) removedChannels.delete(ch);
  else removedChannels.add(ch);
  const wrapper = document.getElementById(`electrode-${ch}`);
  if (wrapper) {
    wrapper.setAttribute("aria-pressed", String(removedChannels.has(ch)));
    applyRemovedState(wrapper, ch);
  }
  syncRemovedChannels();
}

// Tell the server which channels to exclude from the combined signal, PAC,
// and criticality. Best-effort: UI still reflects the change if this fails.
function syncRemovedChannels() {
  fetch("/channels", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ removed: Array.from(removedChannels) }),
  })
    .then((res) => {
      if (!res.ok) throw new Error("channel update failed");
    })
    .catch(() => {
      showToast("Could not update channels on the server.", "error");
    });
}

function applyRemovedState(wrapper, ch) {
  const dot = wrapper.querySelector(".electrode-dot");
  if (removedChannels.has(ch)) {
    dot.className = "electrode-dot removed";
    wrapper.classList.add("is-removed");
    wrapper.title = `${ELECTRODE_POSITIONS[ch]?.label || "Ch"} removed — click to add back`;
  } else {
    wrapper.classList.remove("is-removed");
  }
}

function updateElectrodeQuality(electrodes) {
  // Channels that are actually present in this payload (seen/active).
  const active = new Set((electrodes || []).map((e) => e.channel));

  // Hide any electrode position that has no live channel behind it, so the
  // head map only shows electrodes that are actually there.
  for (const pos of ELECTRODE_POSITIONS) {
    const wrapper = document.getElementById(`electrode-${pos.ch}`);
    if (wrapper) wrapper.style.display = active.has(pos.ch) ? "" : "none";
  }

  for (const elec of electrodes) {
    const wrapper = document.getElementById(`electrode-${elec.channel}`);
    if (!wrapper) continue;

    const dot = wrapper.querySelector(".electrode-dot");

    // Manually removed channels stay black regardless of incoming quality.
    if (removedChannels.has(elec.channel)) {
      applyRemovedState(wrapper, elec.channel);
      continue;
    }

    // Update class for color.
    dot.className = `electrode-dot ${elec.quality}`;
    wrapper.className = `electrode-wrapper quality-${elec.quality}`;

    // Keep the relative noise (channel amplitude vs the median) on hover.
    const noise = Number(elec.noise ?? 0).toFixed(1);
    wrapper.title = `${ELECTRODE_POSITIONS[elec.channel]?.label || "Ch"} · relative noise ${noise}× · ${elec.quality}`;
  }
}

createElectrodeMap();

// Restore any server-side disabled channels so a page refresh stays in sync.
fetch("/channels", { cache: "no-store" })
  .then((r) => r.json())
  .then((d) => {
    for (const ch of d.removed || []) {
      removedChannels.add(ch);
      const wrapper = document.getElementById(`electrode-${ch}`);
      if (wrapper) applyRemovedState(wrapper, ch);
    }
  })
  .catch(() => {});

// --- Collapsible panels (reduce visual overwhelm) ---
// Wrap each panel's content under its head in a body element, make the head a
// toggle, and start every panel collapsed except the primary coupling panel.
function setupCollapsiblePanels() {
  const panels = document.querySelectorAll("main .panel");
  panels.forEach((panel, index) => {
    const head = panel.querySelector(".panel-head");
    if (!head) return;

    // Move everything after the head into a .panel-body wrapper.
    const body = document.createElement("div");
    body.className = "panel-body";
    let node = head.nextSibling;
    while (node) {
      const next = node.nextSibling;
      body.appendChild(node);
      node = next;
    }
    panel.appendChild(body);
    panel.classList.add("collapsible");

    // Keep the device picker and the primary theta-gamma panel open; collapse
    // the rest to reduce visual overwhelm.
    const keepOpen = panel.id === "device-card" || panel.id === "capture-card";
    if (!keepOpen) panel.classList.add("collapsed");

    head.addEventListener("click", () => {
      panel.classList.toggle("collapsed");
      // Charts created while hidden need a resize once revealed.
      if (!panel.classList.contains("collapsed")) {
        window.dispatchEvent(new Event("resize"));
      }
    });
    head.setAttribute("role", "button");
    head.setAttribute("tabindex", "0");
    head.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        panel.classList.toggle("collapsed");
        if (!panel.classList.contains("collapsed")) {
          window.dispatchEvent(new Event("resize"));
        }
      }
    });
  });
}

setupCollapsiblePanels();

function setStatus(connected, text) {
  statusDot.className = "dot " + (connected ? "on" : "off");
  statusText.textContent = text || (connected ? "live" : "disconnected");
}

// When no live data is flowing, ask the backend why (device/error info).
async function refreshDeviceStatus() {
  try {
    const res = await fetch("/status", { cache: "no-store" });
    const s = await res.json();
    applyConnectionStatus(s);
    if (s.has_data) return; // stream is healthy; leave "live" status alone
    if (s.connecting) {
      setStatus(false, "connecting to " + (s.device || "device") + "…");
    } else if (!s.connected) {
      setStatus(false, "not connected — select a headset above");
    } else if (s.error) {
      setStatus(false, "device error: " + s.error);
    } else {
      setStatus(false, "waiting for " + (s.device || "device") + "…");
    }
  } catch (_) {
    setStatus(false, "server unreachable");
  }
}
setInterval(refreshDeviceStatus, 2000);
refreshDeviceStatus();

// --- Session state ---
const session = {
  active: false,
  ratios: [],
  startMs: 0,
  durationMs: 0,
  timer: null,
};

function startSession() {
  const seconds = Math.max(5, Math.min(600, Number(durationInput.value) || 30));
  session.active = true;
  session.ratios = [];
  session.startMs = Date.now();
  session.durationMs = seconds * 1000;

  sessionBtn.textContent = "stop";
  sessionBtn.classList.add("recording");
  shotBtn.disabled = true;
  sessionReadout.classList.add("hidden");
  sessionProgress.classList.remove("hidden");
  sessionProgressFill.style.width = "0%";

  session.timer = setInterval(() => {
    const elapsed = Date.now() - session.startMs;
    const pct = Math.min(100, (elapsed / session.durationMs) * 100);
    sessionProgressFill.style.width = pct + "%";
    if (elapsed >= session.durationMs) finishSession();
  }, 100);
}

function finishSession() {
  if (!session.active) return;
  session.active = false;
  clearInterval(session.timer);

  sessionBtn.textContent = "start";
  sessionBtn.classList.remove("recording");
  sessionProgress.classList.add("hidden");

  const n = session.ratios.length;
  const avgRatio = n ? session.ratios.reduce((a, b) => a + b, 0) / n : 0;
  const avgCog = cognitionScore(avgRatio);
  const elapsedSec = Math.round((Date.now() - session.startMs) / 1000);

  avgRatioEl.textContent = avgRatio.toFixed(2);
  avgCogEl.textContent = avgCog.toFixed(0) + "%";
  sampleCountEl.textContent = String(n);
  elapsedEl.textContent = elapsedSec + "s";
  sessionReadout.classList.remove("hidden");
  shotBtn.disabled = false;
}

sessionBtn.addEventListener("click", () => {
  if (session.active) finishSession();
  else startSession();
});

// --- Screenshot: capture the coupling + session result as a PNG ---
shotBtn.addEventListener("click", async () => {
  shotBtn.disabled = true;
  shotBtn.textContent = "saving…";
  try {
    const canvas = await html2canvas(document.body, {
      backgroundColor: "#0d151c",
      scale: 2,
    });
    const link = document.createElement("a");
    const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    link.download = `coupling-${stamp}.png`;
    link.href = canvas.toDataURL("image/png");
    link.click();
    showToast("Screenshot saved.", "success");
  } catch (err) {
    console.error("Screenshot failed", err);
    showToast("Screenshot failed.", "error");
  } finally {
    shotBtn.textContent = "screenshot";
    shotBtn.disabled = false;
  }
});

// --- Update on each payload ---
function update(payload) {
  // If the headset stopped delivering new samples, the backend marks the frame
  // as not-live. Don't redraw stale numbers as if real — flag it instead so the
  // display can't silently "freeze" on old values.
  if (payload.live === false) {
    setStatus(false, "signal lost — check the headset is on and in range");
    document.body.classList.remove("has-data");
    return;
  }
  document.body.classList.add("has-data");
  const ratio = payload.ratio ?? 0;
  ratioEl.textContent = ratio.toFixed(2);

  const cog = cognitionScore(ratio);
  cogFill.style.width = cog.toFixed(0) + "%";
  cogPct.textContent = cog.toFixed(0) + "%";

  // Display detected frequencies
  const thetaFreq = payload.theta_freq ?? 0;
  const gammaFreq = payload.gamma_freq ?? 0;
  thetaFreqEl.textContent = thetaFreq.toFixed(1);
  gammaFreqEl.textContent = gammaFreq.toFixed(1);

  pushRatio(ratio);

  if (session.active) session.ratios.push(ratio);

  // Bands.
  const byName = {};
  let max = 0;
  for (const b of payload.bands) {
    byName[b.name] = b.power;
    pushBandPower(b.name, b.power);
    if (b.power > max) max = b.power;
  }
  for (const b of BAND_META) {
    const row = bandRows[b.name];
    const power = byName[b.name] ?? 0;
    row.bar.style.width = max > 0 ? (power / max) * 100 + "%" : "0%";
    row.val.textContent = power.toFixed(3);
    row.li.classList.toggle("dominant", b.name === payload.dominant);
  }
  dominantEl.textContent = "dominant: " + payload.dominant;
  if (dominantBandEl) dominantBandEl.textContent = payload.dominant || "\u2014";
  if (dominantMeaningEl) {
    dominantMeaningEl.textContent = payload.dominant_meaning || "";
  }

  // Per-channel fine-grained bandpower (Unicorn-style detail).
  if (payload.band_detail) {
    updateBandDetail(payload.band_detail);
  }

  // Update electrode quality indicators
  if (payload.electrodes) {
    updateElectrodeQuality(payload.electrodes);
  }

  if (payload.spectrum) {
    updateSpectrumChart(payload.spectrum);
  }

  if (payload.test_signal) {
    renderTestSummary(payload.test_signal);
  }

  if (payload.pac) {
    updatePac(payload.pac);
  }

  if (payload.criticality) {
    updateCriticality(payload.criticality);
  }

  updatedEl.textContent = new Date(payload.timestamp * 1000).toLocaleTimeString();
}

// --- Toast notifications -------------------------------------------------
const toastContainer = document.getElementById("toast-container");

function showToast(message, type = "info", timeout = 4000) {
  if (!toastContainer) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.setAttribute("role", type === "error" ? "alert" : "status");
  toast.textContent = message;
  toastContainer.appendChild(toast);
  // Force reflow so the entrance transition runs.
  void toast.offsetWidth;
  toast.classList.add("show");
  const remove = () => {
    toast.classList.remove("show");
    setTimeout(() => toast.remove(), 250);
  };
  if (timeout > 0) setTimeout(remove, timeout);
  toast.addEventListener("click", remove);
}

// --- Device connection ---------------------------------------------------
const deviceSelect = document.getElementById("device-select");
const deviceFields = document.getElementById("device-fields");
const deviceNote = document.getElementById("device-note");
const deviceStatusEl = document.getElementById("device-status");
const connectBtn = document.getElementById("connect-btn");
const disconnectBtn = document.getElementById("disconnect-btn");

let deviceCatalog = [];
let isConnected = false;
let lastStatus = null;
let lastNoticeId = null;

function selectedDevice() {
  return deviceCatalog.find((d) => d.key === deviceSelect.value) || null;
}

function renderDeviceFields() {
  const dev = selectedDevice();
  deviceFields.innerHTML = "";
  deviceNote.textContent = dev ? dev.note || "" : "";
  connectBtn.disabled = !dev || isConnected;
  if (!dev) return;
  for (const field of dev.fields || []) {
    const label = document.createElement("label");
    label.className = "field device-field";
    const span = document.createElement("span");
    span.className = "muted small";
    span.textContent = field.label;
    const input = document.createElement("input");
    input.type = "text";
    input.id = `device-field-${field.key}`;
    input.dataset.key = field.key;
    input.placeholder = field.placeholder || "";
    input.setAttribute("aria-label", field.label);
    input.autocomplete = "off";
    input.spellcheck = false;
    label.appendChild(span);
    label.appendChild(input);
    deviceFields.appendChild(label);
  }
}

function collectDeviceParams() {
  const params = {};
  deviceFields.querySelectorAll("input[data-key]").forEach((input) => {
    const value = input.value.trim();
    if (value) params[input.dataset.key] = value;
  });
  return params;
}

function applyConnectionStatus(status) {
  if (!status) return;
  lastStatus = status;
  isConnected = Boolean(status.connected);
  const connecting = Boolean(status.connecting);

  // One-shot server notices (e.g. auto-disconnect on signal loss). Dedupe by
  // id so the toast shows exactly once even though /status is polled.
  if (status.notice && status.notice.id !== lastNoticeId) {
    lastNoticeId = status.notice.id;
    showToast(status.notice.message, status.notice.type || "info", 8000);
    setReadoutsIdle();
  }

  // Only force the dropdown to match the server while we're actually
  // connected or mid-connect. When idle, respect whatever the user has
  // picked so a stale "last device" from the backend can't snap the
  // selection back (e.g. to Unicorn) while they're choosing Synthetic.
  if ((isConnected || connecting) && status.device_key &&
      deviceSelect.value !== status.device_key) {
    deviceSelect.value = status.device_key;
    renderDeviceFields();
  }

  if (connecting) {
    deviceStatusEl.textContent = "connecting…";
  } else if (isConnected) {
    const rate = status.sampling_rate ? ` · ${status.sampling_rate} Hz` : "";
    const chans = status.channel_count ? ` · ${status.channel_count} ch` : "";
    deviceStatusEl.textContent = `connected: ${status.device}${rate}${chans}`;
  } else if (status.error) {
    deviceStatusEl.textContent = "connection failed";
  } else {
    deviceStatusEl.textContent = "not connected";
  }

  deviceSelect.disabled = connecting || isConnected;
  connectBtn.disabled = connecting || isConnected || !selectedDevice();
  disconnectBtn.disabled = connecting || !isConnected;
  deviceFields.querySelectorAll("input").forEach((i) => {
    i.disabled = connecting || isConnected;
  });
}

async function loadDevices() {
  try {
    const res = await fetch("/devices", { cache: "no-store" });
    if (!res.ok) throw new Error("device list unavailable");
    const data = await res.json();
    deviceCatalog = Array.isArray(data.devices) ? data.devices : [];
    deviceSelect.innerHTML = "";
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "select a headset…";
    deviceSelect.appendChild(placeholder);
    for (const dev of deviceCatalog) {
      const opt = document.createElement("option");
      opt.value = dev.key;
      opt.textContent = dev.name;
      deviceSelect.appendChild(opt);
    }
    if (data.status && data.status.connected && data.status.device_key) {
      deviceSelect.value = data.status.device_key;
    }
    renderDeviceFields();
    if (data.status) applyConnectionStatus(data.status);
  } catch (err) {
    deviceSelect.innerHTML = '<option value="">device list unavailable</option>';
    showToast("Could not load the device list from the server.", "error");
  }
}

async function connectDevice() {
  const dev = selectedDevice();
  if (!dev) return;
  connectBtn.disabled = true;
  connectBtn.textContent = "connecting…";
  deviceStatusEl.textContent = "connecting…";
  try {
    const res = await fetch("/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device: dev.key, params: collectDeviceParams() }),
    });
    const data = await res.json();
    applyConnectionStatus(data.status);
    if (data.ok) {
      showToast(`Connected to ${data.status.device}.`, "success");
    } else {
      const reason = (data.status && data.status.error) || "unknown error";
      showToast(`Could not connect: ${reason}`, "error", 7000);
    }
  } catch (err) {
    showToast("Connection request failed. Is the server running?", "error");
    deviceStatusEl.textContent = "connection failed";
  } finally {
    connectBtn.textContent = "connect";
    if (lastStatus) applyConnectionStatus(lastStatus);
    else connectBtn.disabled = false;
  }
}

async function disconnectDevice() {
  disconnectBtn.disabled = true;
  disconnectBtn.textContent = "disconnecting…";
  try {
    const res = await fetch("/disconnect", { method: "POST" });
    const data = await res.json();
    applyConnectionStatus(data.status);
    setReadoutsIdle();
    showToast("Headset disconnected.", "info");
  } catch (err) {
    showToast("Disconnect request failed.", "error");
  } finally {
    disconnectBtn.textContent = "disconnect";
  }
}

deviceSelect.addEventListener("change", renderDeviceFields);
connectBtn.addEventListener("click", connectDevice);
disconnectBtn.addEventListener("click", disconnectDevice);
loadDevices();

// --- Responsive charts: resize on viewport changes (debounced) -----------
let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    [chart, bandChart, spectrumChart].forEach((c) => {
      try { c.resize(); } catch (_) {}
    });
  }, 150);
});

// --- SSE connection with resilient reconnect -----------------------------
let eventSource = null;
let reconnectDelay = 1000;
let lastMessageMs = 0;

function setReadoutsIdle() {
  // Clear live values when the stream stops so stale numbers aren't trusted.
  document.body.classList.remove("has-data");
  ratioEl.textContent = "0.00";
  cogFill.style.width = "0%";
  cogPct.textContent = "0%";
  if (dominantBandEl) dominantBandEl.textContent = "\u2014";
  if (dominantMeaningEl) dominantMeaningEl.textContent = "waiting for data\u2026";
}

function connectStream() {
  if (eventSource) {
    try { eventSource.close(); } catch (_) {}
  }
  const source = new EventSource("/stream");
  eventSource = source;

  source.onopen = () => {
    reconnectDelay = 1000; // reset backoff on a healthy connection
  };

  source.onmessage = (e) => {
    lastMessageMs = Date.now();
    setStatus(true);
    try {
      update(JSON.parse(e.data));
    } catch (err) {
      console.error("Bad payload", err);
    }
  };

  source.onerror = () => {
    setStatus(false, "reconnecting…");
    document.body.classList.remove("has-data");
    // Stop a running session so its average isn't skewed by the gap.
    if (session.active) {
      finishSession();
      showToast("Connection lost — session stopped.", "error");
    }
    try { source.close(); } catch (_) {}
    eventSource = null;
    const delay = reconnectDelay;
    reconnectDelay = Math.min(reconnectDelay * 2, 15000); // exponential backoff
    setTimeout(connectStream, delay);
  };
}

// Stall detector: the stream can stay open while data stops flowing (e.g. the
// headset dropped). If we've heard nothing for a while, reflect that in the UI.
setInterval(() => {
  if (!isConnected) return;
  if (lastMessageMs && Date.now() - lastMessageMs > 3500) {
    setStatus(false, "no data — check the headset is on and in range");
  }
}, 1500);

connectStream();

