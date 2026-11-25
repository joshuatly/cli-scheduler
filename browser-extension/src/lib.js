// Pure helpers shared by the service worker and the options page.
// No chrome.* APIs here, so this file can be unit-tested with `node --test`.

export const REPO_URL = "https://github.com/joshuatly/cli-scheduler";

export const SCHEMA_VERSION = 2;

/** Id given to the single instance created from 0.1.x settings. Fixed, so migration is repeatable. */
export const LEGACY_INSTANCE_ID = "i0";

export const DEFAULT_SETTINGS = {
  schemaVersion: SCHEMA_VERSION,
  // [{ id: "i0", name: "Home server", serverUrl: "http://192.168.1.10:5000", cwd: "" }]
  instances: [],
  // What happens when no rule matches: "preset" sends to defaultTarget,
  // "none" sends nothing. A fresh install has no default preset yet.
  defaultAction: "none",
  // The instance and preset used when no rule matches and defaultAction is "preset".
  defaultTarget: { instanceId: "", preset: "" },
  // Each rule sends to exactly one preset on exactly one instance.
  // [{ pattern: "youtube.com/playlist", instanceId: "i0", preset: "yt-dlp Audio" }]
  rules: [],
  presetSubmenu: true,
  notifyOnSuccess: true,
};

const SENDABLE_PROTOCOLS = new Set(["http:", "https:"]);

/** Normalise a user-typed server address to an origin-like base URL, or throw. */
export function normalizeServerUrl(raw) {
  let text = String(raw || "").trim();
  if (!text) throw new Error("Server URL is empty");
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(text)) text = "http://" + text;
  const url = new URL(text);
  if (!SENDABLE_PROTOCOLS.has(url.protocol)) {
    throw new Error("Server URL must start with http:// or https://");
  }
  // Keep a sub-path if the scheduler sits behind a reverse proxy.
  const path = url.pathname.replace(/\/+$/, "");
  return url.origin + path;
}

/** Host-permission match pattern for the server, e.g. "http://192.168.1.5/*". */
export function originPattern(serverUrl) {
  const url = new URL(serverUrl);
  // Match patterns don't take ports; the host pattern covers every port.
  return `${url.protocol}//${url.hostname}/*`;
}

/** Distinct host-permission patterns for every instance with a usable address. */
export function originPatterns(instances) {
  const out = new Set();
  for (const inst of instances || []) {
    try {
      out.add(originPattern(inst.serverUrl));
    } catch {
      // Skip malformed addresses; validation reports them.
    }
  }
  return [...out];
}

/** Only web URLs are sent; this blocks javascript:, file:, chrome:, data: etc. */
export function isSendableUrl(raw) {
  try {
    return SENDABLE_PROTOCOLS.has(new URL(raw).protocol);
  } catch {
    return false;
  }
}

// --- Instances and settings -------------------------------------------------

/** A short random id that never contains the menu-id separator. */
export function newInstanceId(existingIds = [], random = () => Math.random()) {
  const taken = new Set(existingIds);
  for (;;) {
    const id = "i" + Math.floor(random() * 36 ** 6).toString(36).padStart(6, "0");
    if (!taken.has(id)) return id;
  }
}

/** A readable fallback name for an instance: the host and port of its address. */
export function defaultInstanceName(serverUrl) {
  try {
    const url = new URL(serverUrl);
    return url.host + url.pathname.replace(/\/+$/, "");
  } catch {
    return String(serverUrl || "").trim() || "Scheduler";
  }
}

/** The name shown for an instance, falling back to its address. */
export function instanceLabel(instance) {
  if (!instance) return "(removed instance)";
  return (instance.name || "").trim() || defaultInstanceName(instance.serverUrl);
}

/**
 * Turn whatever is in storage into the current settings shape.
 * 0.1.x stored a single serverUrl/cwd/defaultPreset and rules without an
 * instance; those become one instance with the fixed id LEGACY_INSTANCE_ID.
 */
export function migrateSettings(stored) {
  const s = stored || {};
  const base = {
    presetSubmenu: s.presetSubmenu ?? DEFAULT_SETTINGS.presetSubmenu,
    notifyOnSuccess: s.notifyOnSuccess ?? DEFAULT_SETTINGS.notifyOnSuccess,
  };

  if (Array.isArray(s.instances)) {
    const preset = (s.defaultTarget && s.defaultTarget.preset) || "";
    return {
      ...base,
      schemaVersion: SCHEMA_VERSION,
      instances: s.instances.map((i, n) => ({
        id: String(i.id || `i${n + 1}`),
        name: i.name || "",
        serverUrl: i.serverUrl || "",
        cwd: i.cwd || "",
      })),
      defaultTarget: {
        instanceId: (s.defaultTarget && s.defaultTarget.instanceId) || "",
        preset,
      },
      defaultAction: normalizeDefaultAction(s.defaultAction, preset),
      rules: (s.rules || []).map((r) => ({
        pattern: r.pattern || "",
        instanceId: r.instanceId || "",
        preset: r.preset || "",
      })),
    };
  }

  // 0.1.x layout, or nothing stored yet (fresh install).
  const serverUrl = s.serverUrl || "http://localhost:5000";
  const id = LEGACY_INSTANCE_ID;
  return {
    ...base,
    schemaVersion: SCHEMA_VERSION,
    instances: [{ id, name: "", serverUrl, cwd: s.cwd || "" }],
    defaultTarget: { instanceId: id, preset: s.defaultPreset || "" },
    defaultAction: normalizeDefaultAction(undefined, s.defaultPreset),
    rules: (s.rules || []).map((r) => ({ pattern: r.pattern || "", instanceId: id, preset: r.preset || "" })),
  };
}

/**
 * "preset" or "none". Settings saved before this option existed get "none"
 * when they had no default preset, since nothing could be sent for them anyway.
 */
function normalizeDefaultAction(action, preset) {
  if (action === "preset" || action === "none") return action;
  return preset ? "preset" : "none";
}

/** The default target, or null when unmatched URLs should not be sent. */
export function effectiveDefault(settings) {
  return settings.defaultAction === "none" ? null : settings.defaultTarget;
}

/**
 * Preset names per instance id, as kept in chrome.storage.local. 0.1.x kept a
 * plain array for its single server; that becomes the legacy instance's list.
 */
export function normalizePresetCache(raw) {
  if (Array.isArray(raw)) return { [LEGACY_INSTANCE_ID]: raw };
  return raw && typeof raw === "object" ? raw : {};
}

/** Same normalisation parsePattern applies, as a single comparable string. */
function patternKey(pattern) {
  const p = parsePattern(pattern);
  return p ? p.host + p.path : null;
}

/**
 * Check settings before saving. Returns a message describing the first
 * problem, or null when everything is fine.
 */
export function validateSettings(settings) {
  const { instances = [], rules = [], defaultTarget, defaultAction } = settings;
  if (!instances.length) return "Add at least one scheduler instance.";

  const ids = new Set();
  const names = new Map();
  for (const inst of instances) {
    const label = instanceLabel(inst);
    try {
      normalizeServerUrl(inst.serverUrl);
    } catch (err) {
      return `Instance "${label}": ${err.message}.`;
    }
    if (ids.has(inst.id)) return `Two instances share the id "${inst.id}".`;
    ids.add(inst.id);
    const key = label.toLowerCase();
    if (names.has(key)) {
      return `Two instances are called "${label}". Give each a different name so menus and rules can tell them apart.`;
    }
    names.set(key, inst);
  }

  if (defaultAction !== "none") {
    if (!defaultTarget || !defaultTarget.preset) {
      return 'Choose a default preset, or set "When no rule matches" to "Do nothing".';
    }
    if (!ids.has(defaultTarget.instanceId)) return "Choose which instance the default preset is on.";
  }

  const seen = new Map();
  for (const rule of rules) {
    const shown = rule.pattern || "(empty)";
    const key = patternKey(rule.pattern);
    if (!key) return `Fix the rule "${shown}": it needs a valid domain.`;
    if (!rule.preset) return `Fix the rule "${shown}": it needs a preset.`;
    if (!ids.has(rule.instanceId)) return `Fix the rule "${shown}": choose which instance it sends to.`;
    if (seen.has(key)) {
      return `The rules "${seen.get(key)}" and "${rule.pattern}" cover the same address. A domain can only send to one preset on one instance, so remove one of them.`;
    }
    seen.set(key, rule.pattern);
  }
  return null;
}

// --- Rules ------------------------------------------------------------------

/**
 * Parse a rule pattern into { host, path }.
 * "youtube.com", "*.youtube.com" and "https://www.youtube.com/" all mean the
 * youtube.com host and every subdomain. An optional path narrows the rule:
 * "youtube.com/playlist" only matches /playlist and paths below it.
 */
export function parsePattern(raw) {
  let text = String(raw || "").trim().toLowerCase();
  if (!text) return null;
  text = text.replace(/^[a-z][a-z0-9+.-]*:\/\//, "");
  text = text.replace(/^\*\./, "");
  const slash = text.indexOf("/");
  let host = slash === -1 ? text : text.slice(0, slash);
  let path = slash === -1 ? "" : text.slice(slash);
  host = host.replace(/:\d+$/, "").replace(/^www\./, "").replace(/\.$/, "");
  path = path.replace(/\/+$/, "");
  if (!host || /[\s*]/.test(host)) return null;
  return { host, path };
}

function hostMatches(hostname, ruleHost) {
  const h = hostname.toLowerCase().replace(/\.$/, "");
  return h === ruleHost || h.endsWith("." + ruleHost);
}

/**
 * Pick the instance and preset for a URL. The most specific matching rule
 * wins: the longest host first, then the longest path. Each rule names one
 * instance, so the result always points at a single instance's preset.
 * Falls back to the default target. Returns { instanceId, preset, rule },
 * where rule is null when the default was used.
 */
export function resolveTarget(rawUrl, rules, defaultTarget) {
  const fallback = {
    instanceId: (defaultTarget && defaultTarget.instanceId) || "",
    preset: (defaultTarget && defaultTarget.preset) || "",
    rule: null,
  };
  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    return fallback;
  }
  const pathname = url.pathname.toLowerCase();
  let best = null;
  let bestScore = [-1, -1];
  for (const rule of rules || []) {
    if (!rule || !rule.preset || !rule.instanceId) continue;
    const parsed = parsePattern(rule.pattern);
    if (!parsed || !hostMatches(url.hostname, parsed.host)) continue;
    // Path rules match whole segments: "/watch" matches /watch and /watch/x, not /watchlater.
    if (parsed.path && !(pathname === parsed.path || pathname.startsWith(parsed.path + "/"))) continue;
    const score = [parsed.host.length, parsed.path.length];
    if (score[0] > bestScore[0] || (score[0] === bestScore[0] && score[1] > bestScore[1])) {
      best = rule;
      bestScore = score;
    }
  }
  return best ? { instanceId: best.instanceId, preset: best.preset, rule: best } : fallback;
}

/**
 * The rule pattern to offer for a URL that nothing matched: its host without
 * "www.", e.g. "music.youtube.com". Empty for URLs that can't be parsed.
 */
export function suggestPattern(rawUrl) {
  try {
    return new URL(rawUrl).hostname.toLowerCase().replace(/\.$/, "").replace(/^www\./, "");
  } catch {
    return "";
  }
}

/** Options-page address that opens a setup step: "rule" (add a rule for url) or "default". */
export function setupHash(step, url) {
  return "#" + new URLSearchParams({ setup: step, url: url || "" }).toString();
}

/** Read setupHash() back. Returns { step, url } or null. */
export function parseSetupHash(hash) {
  const params = new URLSearchParams(String(hash || "").replace(/^#/, ""));
  const step = params.get("setup");
  if (step !== "rule" && step !== "default") return null;
  return { step, url: params.get("url") || "" };
}

// --- Labels -----------------------------------------------------------------

/**
 * Menu entries for every preset on every instance, in instance order.
 * A preset name that exists on more than one instance gets the instance
 * name appended, e.g. "Audio (NAS)"; unique names are shown as they are.
 * Returns [{ instanceId, preset, title, groupStart }], where groupStart marks
 * the first entry of each instance after the first, for menu separators.
 */
export function presetMenuEntries(instances, presetsByInstance) {
  const counts = new Map();
  for (const inst of instances) {
    for (const name of new Set(presetsByInstance[inst.id] || [])) {
      counts.set(name, (counts.get(name) || 0) + 1);
    }
  }
  const entries = [];
  let groups = 0;
  for (const inst of instances) {
    const names = [...new Set(presetsByInstance[inst.id] || [])];
    if (!names.length) continue;
    names.forEach((preset, i) => {
      const title = counts.get(preset) > 1 ? `${preset} (${instanceLabel(inst)})` : preset;
      entries.push({ instanceId: inst.id, preset, title, groupStart: i === 0 && groups > 0 });
    });
    groups++;
  }
  return entries;
}

/**
 * Describe where a job goes, e.g. `"Audio"` with one instance or
 * `"Audio" on NAS` with several. The instance is named whenever more than one
 * instance is configured, so the reader never has to guess.
 */
export function describeTarget(instances, instanceId, preset) {
  const quoted = `"${preset}"`;
  if (instances.length <= 1) return quoted;
  return `${quoted} on ${instanceLabel(instances.find((i) => i.id === instanceId))}`;
}

// --- API --------------------------------------------------------------------

/** Turn a failed response or network error into a message a person can act on. */
export function describeFailure(status, body) {
  if (status === 403) {
    return "The scheduler refused the request. Add this computer's IP to allowed_ips in the scheduler's config.json.";
  }
  if (body && typeof body.error === "string") return body.error;
  return `The scheduler answered with HTTP ${status}.`;
}

/**
 * How long to wait for a scheduler before giving up, in milliseconds. A
 * scheduler on the local network answers in well under a second; one that is
 * switched off or unreachable would otherwise hang until the operating
 * system's TCP timeout, which can be minutes.
 */
export const PRESETS_TIMEOUT_MS = 5000;
export const SUBMIT_TIMEOUT_MS = 8000;

class RequestError extends Error {
  constructor(message, timedOut) {
    super(message);
    this.timedOut = timedOut;
  }
}

function seconds(ms) {
  return `${Math.round(ms / 100) / 10} s`;
}

/**
 * fetch() with a deadline that also covers reading the JSON body.
 * Resolves to { response, body } (body is null for non-JSON); rejects with a
 * RequestError whose message a person can act on.
 */
async function requestJson(fetchImpl, serverUrl, path, init, timeoutMs) {
  const controller = new AbortController();
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(
        new RequestError(
          `No answer from the scheduler at ${serverUrl} within ${seconds(timeoutMs)}. Is it running and reachable from this computer?`,
          true,
        ),
      );
    }, timeoutMs);
  });
  const attempt = (async () => {
    let response;
    try {
      response = await fetchImpl(`${serverUrl}${path}`, { ...init, signal: controller.signal });
    } catch {
      throw new RequestError(`Could not reach the scheduler at ${serverUrl}. Is it running?`, false);
    }
    let body = null;
    try {
      body = await response.json();
    } catch {
      // Non-JSON body (e.g. the HTML 403 page).
    }
    return { response, body };
  })();
  try {
    // The race also covers a fetch that ignores the abort signal.
    return await Promise.race([attempt, deadline]);
  } finally {
    clearTimeout(timer);
    attempt.catch(() => {}); // the loser of the race must not surface as unhandled
  }
}

/** POST one URL to the scheduler. Resolves to { ok, jobs } or { ok: false, error }. */
export async function submitJob({ serverUrl, preset, url, cwd }, fetchImpl = fetch, timeoutMs = SUBMIT_TIMEOUT_MS) {
  const payload = { preset, urls: [url] };
  if (cwd) payload.cwd = cwd;
  let result;
  try {
    result = await requestJson(
      fetchImpl,
      serverUrl,
      "/api/jobs",
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
      timeoutMs,
    );
  } catch (err) {
    let error = err.message;
    // The request may have arrived before the answer stalled.
    if (err.timedOut) error += " Check its job list before sending again.";
    return { ok: false, error, timedOut: !!err.timedOut };
  }
  const { response, body } = result;
  if (response.status === 201 && body && Array.isArray(body.jobs)) {
    return { ok: true, jobs: body.jobs };
  }
  return { ok: false, error: describeFailure(response.status, body) };
}

/** GET the preset names from the scheduler. Throws with a readable message. */
export async function fetchPresets(serverUrl, fetchImpl = fetch, timeoutMs = PRESETS_TIMEOUT_MS) {
  const { response, body } = await requestJson(fetchImpl, serverUrl, "/api/presets", {}, timeoutMs);
  if (!response.ok || !body || !Array.isArray(body.presets)) {
    throw new Error(describeFailure(response.status, body));
  }
  return body.presets.map((p) => p.name).filter(Boolean);
}
