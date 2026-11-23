import {
  DEFAULT_SETTINGS,
  fetchPresets,
  normalizeServerUrl,
  originPattern,
  parsePattern,
  resolvePreset,
} from "./lib.js";

const $ = (id) => document.getElementById(id);
const rulesEl = $("rules");

function setStatus(el, text, kind) {
  el.textContent = text;
  el.className = "status" + (kind ? " " + kind : "");
}

// --- Rules UI ---------------------------------------------------------------

function addRuleRow(rule = { pattern: "", preset: "" }) {
  const row = $("ruleTemplate").content.firstElementChild.cloneNode(true);
  row.querySelector(".pattern").value = rule.pattern;
  row.querySelector(".preset").value = rule.preset;
  row.querySelector(".remove").addEventListener("click", () => {
    row.remove();
    updateTry();
  });
  row.addEventListener("input", () => {
    validateRow(row);
    updateTry();
  });
  rulesEl.append(row);
  validateRow(row);
  return row;
}

function validateRow(row) {
  const text = row.querySelector(".pattern").value.trim();
  row.classList.toggle("invalid", text !== "" && !parsePattern(text));
}

function readRules() {
  return [...rulesEl.querySelectorAll(".rule")]
    .map((row) => ({
      pattern: row.querySelector(".pattern").value.trim(),
      preset: row.querySelector(".preset").value.trim(),
    }))
    .filter((r) => r.pattern || r.preset);
}

function updateTry() {
  const url = $("tryUrl").value.trim();
  const out = $("tryResult");
  if (!url) return setStatus(out, "");
  const { preset, rule } = resolvePreset(url, readRules(), $("defaultPreset").value.trim());
  if (!preset) return setStatus(out, "No rule matches and no default preset is set.", "err");
  setStatus(out, rule ? `→ ${preset} (rule: ${rule.pattern})` : `→ ${preset} (default)`, "ok");
}

// --- Presets ----------------------------------------------------------------

function fillPresetList(names) {
  const list = $("presetList");
  list.replaceChildren(...names.map((name) => Object.assign(document.createElement("option"), { value: name })));
}

async function loadPresetList(serverUrl, statusEl) {
  try {
    const names = await fetchPresets(serverUrl);
    fillPresetList(names);
    await chrome.storage.local.set({ presetCache: names });
    if (statusEl) {
      setStatus(statusEl, `Connected. ${names.length} preset${names.length === 1 ? "" : "s"}: ${names.join(", ")}`, "ok");
    }
    return names;
  } catch (err) {
    if (statusEl) setStatus(statusEl, err.message, "err");
    return null;
  }
}

/** Must be called synchronously from a click handler so Chrome shows the prompt. */
function requestAccess(serverUrl) {
  return chrome.permissions.request({ origins: [originPattern(serverUrl)] });
}

// --- Load / save ------------------------------------------------------------

async function load() {
  const s = { ...DEFAULT_SETTINGS, ...(await chrome.storage.sync.get(DEFAULT_SETTINGS)) };
  $("serverUrl").value = s.serverUrl;
  $("cwd").value = s.cwd;
  $("defaultPreset").value = s.defaultPreset;
  $("presetSubmenu").checked = s.presetSubmenu;
  $("notifyOnSuccess").checked = s.notifyOnSuccess;
  rulesEl.replaceChildren();
  s.rules.forEach((r) => addRuleRow(r));

  const { presetCache = [] } = await chrome.storage.local.get("presetCache");
  fillPresetList(presetCache);
  try {
    if (await chrome.permissions.contains({ origins: [originPattern(s.serverUrl)] })) {
      loadPresetList(s.serverUrl, $("testStatus"));
    }
  } catch {
    // Malformed stored URL; the user will fix it.
  }
}

$("test").addEventListener("click", async () => {
  const status = $("testStatus");
  let serverUrl;
  try {
    serverUrl = normalizeServerUrl($("serverUrl").value);
  } catch (err) {
    return setStatus(status, err.message, "err");
  }
  const granted = requestAccess(serverUrl);
  setStatus(status, "Connecting…");
  if (!(await granted)) return setStatus(status, "Chrome permission to reach the server was not granted.", "err");
  await loadPresetList(serverUrl, status);
});

$("save").addEventListener("click", async () => {
  const status = $("saveStatus");
  let serverUrl;
  try {
    serverUrl = normalizeServerUrl($("serverUrl").value);
  } catch (err) {
    return setStatus(status, err.message, "err");
  }
  const granted = requestAccess(serverUrl);

  const rules = readRules();
  const bad = rules.find((r) => !parsePattern(r.pattern) || !r.preset);
  if (bad) {
    await granted;
    return setStatus(status, `Fix the rule "${bad.pattern || "(empty)"}": it needs a valid domain and a preset.`, "err");
  }

  await chrome.storage.sync.set({
    serverUrl,
    cwd: $("cwd").value.trim(),
    defaultPreset: $("defaultPreset").value.trim(),
    rules,
    presetSubmenu: $("presetSubmenu").checked,
    notifyOnSuccess: $("notifyOnSuccess").checked,
  });
  $("serverUrl").value = serverUrl;

  if (!(await granted)) {
    return setStatus(status, "Saved, but Chrome permission to reach the server was not granted, so sending won't work.", "err");
  }
  await loadPresetList(serverUrl, $("testStatus"));
  await chrome.runtime.sendMessage({ type: "rebuild-menus" });
  setStatus(status, "Saved.", "ok");
});

$("addRule").addEventListener("click", () => addRuleRow().querySelector(".pattern").focus());
$("tryUrl").addEventListener("input", updateTry);
$("defaultPreset").addEventListener("input", updateTry);

load();
