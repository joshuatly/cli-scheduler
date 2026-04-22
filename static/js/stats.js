"use strict";

// ---- Helpers ----------------------------------------------------------------

function fmtDuration(secs) {
  if (secs == null || isNaN(secs)) return "—";
  secs = Math.round(secs);
  if (secs < 60) return secs + "s";
  if (secs < 3600) return Math.floor(secs / 60) + "m " + (secs % 60) + "s";
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return h + "h " + m + "m";
}

function fmtTimeSaved(secs) {
  if (!secs || secs < 60) return Math.round(secs || 0) + "s";
  if (secs < 3600) return Math.round(secs / 60) + " min";
  return (secs / 3600).toFixed(1) + " hr";
}

function pct(a, b) {
  if (!b) return 0;
  return Math.round((a / b) * 100);
}

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return "—";
  }
}

// ISO week label → short date for the Monday of that week
function weekLabel(weekStr) {
  const [year, wNum] = weekStr.split("-W").map(Number);
  // Find the Monday of ISO week wNum in year
  const jan4 = new Date(year, 0, 4);
  const mon = new Date(jan4);
  mon.setDate(jan4.getDate() - ((jan4.getDay() + 6) % 7) + (wNum - 1) * 7);
  return mon.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

const CHART_COLORS = {
  finished: "#22c55e",
  failed:   "#ef4444",
  cancelled:"#eab308",
  accent:   "#3b82f6",
  muted:    "#475569",
};

const CHART_DEFAULTS = {
  color: "#94a3b8",
  borderColor: "#94a3b8",
  plugins: { legend: { labels: { color: "#94a3b8" } } },
  scales: {
    x: { ticks: { color: "#94a3b8" }, grid: { color: "#1e293b" } },
    y: { ticks: { color: "#94a3b8" }, grid: { color: "#1e293b" } },
  },
};

// ---- Chart builders ---------------------------------------------------------

function buildWeeklyChart(canvas, weekly) {
  const labels = weekly.map(w => weekLabel(w.week));
  return new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Finished",  data: weekly.map(w => w.finished  || 0), backgroundColor: CHART_COLORS.finished,  stack: "s" },
        { label: "Failed",    data: weekly.map(w => w.failed    || 0), backgroundColor: CHART_COLORS.failed,    stack: "s" },
        { label: "Cancelled", data: weekly.map(w => w.cancelled || 0), backgroundColor: CHART_COLORS.cancelled, stack: "s" },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { labels: { color: "#94a3b8" } } },
      scales: {
        x: { stacked: true, ticks: { color: "#94a3b8" }, grid: { color: "#1e293b" } },
        y: { stacked: true, ticks: { color: "#94a3b8", precision: 0 }, grid: { color: "#1e293b" }, beginAtZero: true },
      },
    },
  });
}

function buildOutcomeChart(canvas, at) {
  return new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: ["Finished", "Failed", "Cancelled"],
      datasets: [{
        data: [at.finished || 0, at.failed || 0, at.cancelled || 0],
        backgroundColor: [CHART_COLORS.finished, CHART_COLORS.failed, CHART_COLORS.cancelled],
        borderWidth: 0,
      }],
    },
    options: {
      responsive: true,
      cutout: "65%",
      plugins: { legend: { position: "bottom", labels: { color: "#94a3b8", padding: 12 } } },
    },
  });
}

function buildDurationChart(canvas, buckets) {
  return new Chart(canvas, {
    type: "bar",
    data: {
      labels: buckets.map(b => b.label),
      datasets: [{
        label: "Jobs",
        data: buckets.map(b => b.count),
        backgroundColor: CHART_COLORS.accent,
        borderRadius: 4,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#94a3b8", precision: 0 }, grid: { color: "#1e293b" }, beginAtZero: true },
        y: { ticks: { color: "#94a3b8" }, grid: { color: "#1e293b" } },
      },
    },
  });
}

function buildPresetChart(canvas, perPreset) {
  const top = perPreset.slice(0, 10);
  return new Chart(canvas, {
    type: "bar",
    data: {
      labels: top.map(p => p.name),
      datasets: [{
        label: "Runs",
        data: top.map(p => p.total),
        backgroundColor: CHART_COLORS.accent,
        borderRadius: 4,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#94a3b8", precision: 0 }, grid: { color: "#1e293b" }, beginAtZero: true },
        y: { ticks: { color: "#94a3b8" }, grid: { color: "#1e293b" } },
      },
    },
  });
}

// ---- Preset drill-down table ------------------------------------------------

function buildPresetTable(perPreset) {
  if (!perPreset.length) return '<p class="text-muted">No preset data yet.</p>';

  const rows = perPreset.map(p => {
    const total = p.total || 0;
    const successRate = pct(p.finished || 0, total);
    const barWidth = Math.max(2, successRate);
    return `<tr>
      <td><strong>${escapeHtml(p.name)}</strong></td>
      <td>${total}</td>
      <td>
        <span class="rate-bar" style="width:${barWidth}px"></span>
        ${successRate}%
      </td>
      <td>${fmtDuration(p.avg_run_seconds)}</td>
      <td>${p.min_run_seconds != null ? fmtDuration(p.min_run_seconds) : "—"}</td>
      <td>${p.max_run_seconds != null ? fmtDuration(p.max_run_seconds) : "—"}</td>
      <td class="text-muted">${fmtDate(p.last_run)}</td>
    </tr>`;
  }).join("");

  return `<div class="preset-table-wrap">
    <table class="preset-table">
      <thead><tr>
        <th>Preset</th>
        <th>Runs</th>
        <th>Success Rate</th>
        <th>Avg Duration</th>
        <th>Min</th>
        <th>Max</th>
        <th>Last Run</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

// ---- Render -----------------------------------------------------------------

function render(data) {
  const { all_time: at, weekly, run_duration_buckets: buckets, per_preset } = data;

  if (!at || at.total === 0) {
    document.getElementById("stats-root").innerHTML = `
      <div class="empty-stats">
        <p>No job history yet.</p>
        <p class="text-muted">Stats will appear here once jobs have been run.</p>
      </div>`;
    return;
  }

  const successRate = pct(at.finished || 0, at.total);
  const timeSaved = at.time_saved_seconds || 0;

  document.getElementById("stats-root").innerHTML = `
    <div class="stats-grid">
      <div class="stat-card">
        <div class="label">Total Jobs</div>
        <div class="value">${at.total}</div>
      </div>
      <div class="stat-card">
        <div class="label">Success Rate</div>
        <div class="value text-success">${successRate}%</div>
        <div class="sub">${at.finished || 0} finished</div>
      </div>
      <div class="stat-card">
        <div class="label">Avg Run Time</div>
        <div class="value">${fmtDuration(at.avg_run_seconds)}</div>
      </div>
      <div class="stat-card">
        <div class="label">Time Saved</div>
        <div class="value text-accent">${fmtTimeSaved(timeSaved)}</div>
        <div class="sub">from batching</div>
      </div>
    </div>

    <div class="time-saved-card">
      <div class="big">${fmtTimeSaved(timeSaved)}</div>
      <div class="explain">
        <strong>How time saved is calculated:</strong> When multiple jobs are queued together,
        you don't have to watch each one finish to manually start the next.
        For every job that waited in queue, we count its full run time as "saved" —
        that's time you reclaimed because the scheduler chained them automatically.
        Solo jobs (no queue wait) contribute zero.
      </div>
    </div>

    <div class="charts-row">
      <div class="chart-card">
        <h3>Jobs per Week</h3>
        <div class="chart-wrap"><canvas id="weeklyChart"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>Outcomes</h3>
        <div class="chart-wrap"><canvas id="outcomeChart"></canvas></div>
      </div>
    </div>

    <div class="charts-row-equal">
      <div class="chart-card">
        <h3>Run Duration Distribution</h3>
        <div class="chart-wrap"><canvas id="durationChart"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>Preset Usage</h3>
        <div class="chart-wrap"><canvas id="presetChart"></canvas></div>
      </div>
    </div>

    <div class="chart-card" style="margin-bottom:1rem">
      <h3>Preset Drill-down</h3>
      <div id="presetTable"></div>
    </div>
  `;

  if (weekly.length) buildWeeklyChart(document.getElementById("weeklyChart"), weekly);
  buildOutcomeChart(document.getElementById("outcomeChart"), at);
  if (buckets.some(b => b.count)) buildDurationChart(document.getElementById("durationChart"), buckets);
  if (per_preset.length) buildPresetChart(document.getElementById("presetChart"), per_preset);

  document.getElementById("presetTable").innerHTML = buildPresetTable(per_preset);
}

// ---- Boot -------------------------------------------------------------------

async function loadStats() {
  try {
    const resp = await fetch("/api/stats");
    if (!resp.ok) throw new Error("Failed to load stats");
    const data = await resp.json();
    render(data);
  } catch (err) {
    document.getElementById("stats-root").innerHTML =
      `<p class="text-error">Failed to load stats: ${escapeHtml(String(err))}</p>`;
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

loadStats();
