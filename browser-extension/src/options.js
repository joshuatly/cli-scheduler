import {
  REPO_URL,
  SCHEMA_VERSION,
  defaultInstanceName,
  describeTarget,
  effectiveDefault,
  fetchPresets,
  instanceLabel,
  migrateSettings,
  newInstanceId,
  normalizePresetCache,
  normalizeServerUrl,
  originPattern,
  originPatterns,
  parsePattern,
  parseSetupHash,
  resolveTarget,
  suggestPattern,
  validateSettings,
} from "./lib.js";

const $ = (id) => document.getElementById(id);
const instancesEl = $("instances");
const rulesEl = $("rules");

/** Preset names per instance id: the last good fetch, or the cache. */
let presetsByInstance = {};

function setStatus(el, text, kind) {
  el.textContent = text;
  el.classList.remove("ok", "err", "warn");
  if (kind) el.classList.add(kind);
}

// --- Instances UI -----------------------------------------------------------

function readInstances() {
  return [...instancesEl.querySelectorAll(".instance-card")].map((card) => ({
    id: card.dataset.id,
    name: card.querySelector(".name").value.trim(),
    serverUrl: card.querySelector(".serverUrl").value.trim(),
    cwd: card.querySelector(".cwd").value.trim(),
  }));
}

function cardFor(id) {
  return instancesEl.querySelector(`.instance-card[data-id="${CSS.escape(id)}"]`);
}

function addInstanceCard(inst) {
  const card = $("instanceTemplate").content.firstElementChild.cloneNode(true);
  card.dataset.id = inst.id;
  for (const field of ["name", "serverUrl", "cwd"]) {
    const input = card.querySelector("." + field);
    input.value = inst[field] || "";
    input.id = `${field}-${inst.id}`;
    input.closest(".field").querySelector(".field-label").htmlFor = input.id;
  }
  // Show the fallback name as a placeholder, so an unnamed instance still reads well.
  const syncPlaceholder = () => {
    const url = card.querySelector(".serverUrl").value.trim();
    card.querySelector(".name").placeholder = url ? defaultInstanceName(safeNormalize(url)) : "e.g. Home server";
  };
  syncPlaceholder();
  card.querySelector(".serverUrl").addEventListener("input", syncPlaceholder);
  card.addEventListener("input", () => {
    refreshInstanceSelects();
    updateTry();
  });
  card.querySelector(".test").addEventListener("click", () => testInstance(card));
  card.querySelector(".remove").addEventListener("click", () => removeInstance(card));
  instancesEl.append(card);
  ensureDatalist(inst.id);
  return card;
}

function safeNormalize(url) {
  try {
    return normalizeServerUrl(url);
  } catch {
    return url;
  }
}

function removeInstance(card) {
  const id = card.dataset.id;
  const instances = readInstances();
  if (instances.length <= 1) {
    return setStatus($("saveStatus"), "Keep at least one instance. Change its address instead.", "err");
  }
  const label = instanceLabel(instances.find((i) => i.id === id));
  const ruleRows = [...rulesEl.querySelectorAll(".rule")].filter((row) => row.querySelector(".instance").value === id);
  const usedByDefault = $("defaultAction").value === "preset" && $("defaultInstance").value === id && $("defaultPreset").value.trim();
  const uses = [];
  if (ruleRows.length) {
    uses.push(ruleRows.length === 1 ? "1 rule that sends to it will be removed" : `${ruleRows.length} rules that send to it will be removed`);
  }
  if (usedByDefault) uses.push("the default preset will be cleared");
  if (uses.length && !confirm(`Remove "${label}"? ${uses.join(", and ")}.`)) return;

  ruleRows.forEach((row) => row.remove());
  if ($("defaultInstance").value === id) $("defaultPreset").value = "";
  card.remove();
  document.getElementById("presets-" + id)?.remove();
  refreshInstanceSelects();
  updateTry();
  setStatus($("saveStatus"), `Removed "${label}". Press Save to keep the change.`);
}

/** Rebuild every instance picker, keeping each one's choice. */
function refreshInstanceSelects() {
  const instances = readInstances();
  document.body.classList.toggle("multi", instances.length > 1);
  for (const select of document.querySelectorAll("select.instance")) {
    const current = select.value || select.dataset.want || "";
    select.replaceChildren(
      ...instances.map((inst) => Object.assign(document.createElement("option"), { value: inst.id, textContent: instanceLabel(inst) })),
    );
    select.value = instances.some((i) => i.id === current) ? current : instances[0]?.id || "";
    delete select.dataset.want;
    linkPresetInput(select);
  }
}

/** Point the preset box next to an instance picker at that instance's preset list. */
function linkPresetInput(select) {
  const input = select.parentElement.querySelector("input.preset");
  if (!input) return;
  input.setAttribute("list", "presets-" + select.value);
  markUnknownPreset(input, select.value);
}

/** Flag a preset that the chosen instance doesn't have (only once we know its list). */
function markUnknownPreset(input, instanceId) {
  const known = presetsByInstance[instanceId];
  const name = input.value.trim();
  const unknown = Boolean(name && known && known.length && !known.includes(name));
  input.classList.toggle("unknown", unknown);
  input.title = unknown ? `"${name}" is not a preset on ${instanceLabel(readInstances().find((i) => i.id === instanceId))}` : "";
}

function ensureDatalist(id) {
  let list = document.getElementById("presets-" + id);
  if (!list) {
    list = Object.assign(document.createElement("datalist"), { id: "presets-" + id });
    $("datalists").append(list);
  }
  return list;
}

function fillDatalist(id, names) {
  ensureDatalist(id).replaceChildren(...names.map((name) => Object.assign(document.createElement("option"), { value: name })));
}

async function rememberPresets(id, names) {
  presetsByInstance[id] = names;
  fillDatalist(id, names);
  // Write the whole map (not read-modify-write), so parallel loads can't drop each other's lists.
  const current = readInstances().map((i) => i.id);
  await chrome.storage.local.set({
    presetCache: Object.fromEntries(current.map((i) => [i, presetsByInstance[i] || []])),
  });
  document.querySelectorAll("select.instance").forEach(linkPresetInput);
  updateTry();
}

async function loadPresetsFor(card) {
  const status = card.querySelector(".testStatus");
  let serverUrl;
  try {
    serverUrl = normalizeServerUrl(card.querySelector(".serverUrl").value);
  } catch (err) {
    setStatus(status, err.message, "err");
    return null;
  }
  try {
    const names = await fetchPresets(serverUrl);
    await rememberPresets(card.dataset.id, names);
    setStatus(status, `Connected. ${names.length} preset${names.length === 1 ? "" : "s"}: ${names.join(", ")}`, "ok");
    return names;
  } catch (err) {
    setStatus(status, err.message, "err");
    return null;
  }
}

/** Must be called synchronously from a click handler so Chrome shows the prompt. */
function requestAccess(origins) {
  return chrome.permissions.request({ origins });
}

function testInstance(card) {
  const status = card.querySelector(".testStatus");
  let serverUrl;
  try {
    serverUrl = normalizeServerUrl(card.querySelector(".serverUrl").value);
  } catch (err) {
    return setStatus(status, err.message, "err");
  }
  const granted = requestAccess([originPattern(serverUrl)]);
  setStatus(status, "Connecting…");
  granted.then((ok) => {
    if (!ok) return setStatus(status, "Chrome permission to reach the server was not granted.", "err");
    return loadPresetsFor(card);
  });
}

// --- Rules UI ---------------------------------------------------------------

function addRuleRow(rule = { pattern: "", instanceId: "", preset: "" }) {
  const row = $("ruleTemplate").content.firstElementChild.cloneNode(true);
  row.querySelector(".pattern").value = rule.pattern;
  row.querySelector(".preset").value = rule.preset;
  row.querySelector(".instance").dataset.want = rule.instanceId || $("defaultInstance").value;
  row.querySelector(".remove").addEventListener("click", () => {
    row.remove();
    validateRules();
    updateTry();
  });
  row.querySelector(".instance").addEventListener("change", (e) => linkPresetInput(e.target));
  row.addEventListener("input", () => {
    markUnknownPreset(row.querySelector(".preset"), row.querySelector(".instance").value);
    validateRules();
    updateTry();
  });
  rulesEl.append(row);
  refreshInstanceSelects();
  validateRules();
  return row;
}

/** Mark bad patterns, and patterns that repeat an earlier rule's address. */
function validateRules() {
  const seen = new Set();
  for (const row of rulesEl.querySelectorAll(".rule")) {
    const input = row.querySelector(".pattern");
    const text = input.value.trim();
    const parsed = text ? parsePattern(text) : null;
    const key = parsed ? parsed.host + parsed.path : null;
    const duplicate = Boolean(key && seen.has(key));
    if (key) seen.add(key);
    row.classList.toggle("invalid", text !== "" && !parsed);
    row.classList.toggle("duplicate", duplicate);
    input.title = duplicate ? "Another rule already covers this address. Each domain sends to one preset on one instance." : "";
  }
}

function readRules() {
  return [...rulesEl.querySelectorAll(".rule")]
    .map((row) => ({
      pattern: row.querySelector(".pattern").value.trim(),
      instanceId: row.querySelector(".instance").value,
      preset: row.querySelector(".preset").value.trim(),
    }))
    .filter((r) => r.pattern || r.preset);
}

function readDefaultTarget() {
  return { instanceId: $("defaultInstance").value, preset: $("defaultPreset").value.trim() };
}

/** Show the default preset fields only when unmatched links go to one. */
function syncDefaultAction() {
  const none = $("defaultAction").value === "none";
  $("defaultPresetField").hidden = none;
  $("noneHint").hidden = !none;
}

function updateTry() {
  const url = $("tryUrl").value.trim();
  const out = $("tryResult");
  if (!url) return setStatus(out, "");
  const instances = readInstances();
  const action = $("defaultAction").value;
  const { instanceId, preset, rule } = resolveTarget(
    url,
    readRules(),
    effectiveDefault({ defaultAction: action, defaultTarget: readDefaultTarget() }),
  );
  if (!preset && action === "none") return setStatus(out, "→ Nothing is sent: no rule matches.");
  if (!preset) return setStatus(out, "No rule matches and no default preset is set.", "err");
  const where = describeTarget(instances, instanceId, preset);
  const known = presetsByInstance[instanceId];
  const missing = known && known.length && !known.includes(preset);
  const why = rule ? `rule: ${rule.pattern}` : "default";
  setStatus(
    out,
    `→ ${where} (${why})` + (missing ? `. That instance has no preset with this name.` : ""),
    missing ? "warn" : "ok",
  );
}

// --- Load / save ------------------------------------------------------------

async function load() {
  const s = migrateSettings(await chrome.storage.sync.get(null));
  const { presetCache } = await chrome.storage.local.get("presetCache");
  presetsByInstance = normalizePresetCache(presetCache);

  instancesEl.replaceChildren();
  rulesEl.replaceChildren();
  s.instances.forEach((inst) => {
    addInstanceCard(inst);
    fillDatalist(inst.id, presetsByInstance[inst.id] || []);
  });
  $("defaultInstance").dataset.want = s.defaultTarget.instanceId;
  $("defaultPreset").value = s.defaultTarget.preset;
  $("defaultAction").value = s.defaultAction;
  syncDefaultAction();
  refreshInstanceSelects();
  s.rules.forEach((r) => addRuleRow(r));
  $("presetSubmenu").checked = s.presetSubmenu;
  $("notifyOnSuccess").checked = s.notifyOnSuccess;

  for (const inst of s.instances) {
    try {
      if (await chrome.permissions.contains({ origins: [originPattern(inst.serverUrl)] })) {
        loadPresetsFor(cardFor(inst.id));
      }
    } catch {
      // Malformed stored URL; the user will fix it.
    }
  }
}

$("save").addEventListener("click", () => {
  const status = $("saveStatus");

  // Normalise addresses first, without awaiting, so the permission prompt
  // still counts as a response to this click.
  const instances = readInstances();
  for (const inst of instances) {
    try {
      inst.serverUrl = normalizeServerUrl(inst.serverUrl);
    } catch (err) {
      return setStatus(status, `Instance "${instanceLabel(inst)}": ${err.message}.`, "err");
    }
    if (!inst.name) inst.name = defaultInstanceName(inst.serverUrl);
  }
  const granted = requestAccess(originPatterns(instances));

  const settings = {
    schemaVersion: SCHEMA_VERSION,
    instances,
    defaultAction: $("defaultAction").value,
    defaultTarget: readDefaultTarget(),
    rules: readRules(),
    presetSubmenu: $("presetSubmenu").checked,
    notifyOnSuccess: $("notifyOnSuccess").checked,
  };
  const problem = validateSettings(settings);
  if (problem) {
    granted.catch(() => {});
    return setStatus(status, problem, "err");
  }

  save(settings, granted);
});

async function save(settings, granted) {
  const status = $("saveStatus");
  await chrome.storage.sync.set(settings);
  for (const inst of settings.instances) {
    const card = cardFor(inst.id);
    card.querySelector(".serverUrl").value = inst.serverUrl;
    card.querySelector(".name").value = inst.name;
  }
  refreshInstanceSelects();

  let ok = false;
  try {
    ok = await granted;
  } catch {
    // The request itself failed (e.g. an address Chrome can't make a pattern for).
  }
  if (!ok) {
    return setStatus(status, "Saved, but Chrome permission to reach the schedulers was not granted, so sending won't work.", "err");
  }
  await Promise.all(settings.instances.map((inst) => loadPresetsFor(cardFor(inst.id))));
  await chrome.runtime.sendMessage({ type: "rebuild-menus" });
  setStatus(status, "Saved.", "ok");
}

$("addInstance").addEventListener("click", () => {
  const id = newInstanceId(readInstances().map((i) => i.id));
  const card = addInstanceCard({ id, name: "", serverUrl: "", cwd: "" });
  fillDatalist(id, []);
  refreshInstanceSelects();
  card.querySelector(".name").focus();
});
$("addRule").addEventListener("click", () => addRuleRow().querySelector(".pattern").focus());
$("tryUrl").addEventListener("input", updateTry);
$("defaultPreset").addEventListener("input", () => {
  markUnknownPreset($("defaultPreset"), $("defaultInstance").value);
  updateTry();
});
$("defaultAction").addEventListener("change", () => {
  syncDefaultAction();
  updateTry();
});
$("defaultInstance").addEventListener("change", (e) => {
  linkPresetInput(e.target);
  updateTry();
});

// --- Setup steps from the "Not sent: no rule" notification --------------------

function highlight(el) {
  el.scrollIntoView({ block: "center", behavior: "smooth" });
  el.classList.add("highlight");
  setTimeout(() => el.classList.remove("highlight"), 2500);
}

/**
 * "rule": add a rule for the URL's site (or reuse one already on the page)
 * and put the cursor in its preset box. "default": switch to sending
 * unmatched links to a default preset and put the cursor there.
 * Nothing is saved until the user presses Save.
 */
function applySetup(step, url) {
  const status = $("saveStatus");
  if (url) $("tryUrl").value = url;
  if (step === "default") {
    $("defaultAction").value = "preset";
    syncDefaultAction();
    updateTry();
    highlight($("defaultPresetField"));
    $("defaultPreset").focus({ preventScroll: true });
    const kept = $("defaultPreset").value.trim();
    return setStatus(status, kept ? `Check the default preset ("${kept}"), then press Save.` : "Choose a default preset, then press Save.");
  }
  const site = suggestPattern(url);
  const parsed = parsePattern(site);
  const key = parsed && parsed.host + parsed.path;
  let row = [...rulesEl.querySelectorAll(".rule")].find((r) => {
    const p = parsePattern(r.querySelector(".pattern").value);
    return p && p.host + p.path === key;
  });
  if (!row) row = addRuleRow({ pattern: site, instanceId: $("defaultInstance").value, preset: "" });
  updateTry();
  highlight(row);
  row.querySelector(".preset").focus({ preventScroll: true });
  setStatus(status, `Choose ${document.body.classList.contains("multi") ? "an instance and a preset" : "a preset"} for ${site}, then press Save.`);
}

/** Bring this settings tab to the front. */
async function focusThisTab() {
  const tab = await chrome.tabs.getCurrent();
  if (!tab) return;
  await chrome.tabs.update(tab.id, { active: true });
  await chrome.windows.update(tab.windowId, { focused: true });
}

$("version").textContent = `Version ${chrome.runtime.getManifest().version}`;
$("repoLink").href = REPO_URL;

const ready = load();

// Opened from a notification: options.html#setup=rule&url=…
ready.then(() => {
  const setup = parseSetupHash(location.hash);
  if (!setup) return;
  history.replaceState(null, "", location.pathname); // so a reload doesn't repeat it
  applySetup(setup.step, setup.url);
});

// Already open when a notification is clicked: the service worker asks this tab.
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.type !== "setup") return false;
  ready.then(() => {
    applySetup(message.step, message.url);
    focusThisTab();
    sendResponse({ ok: true });
  });
  return true;
});
