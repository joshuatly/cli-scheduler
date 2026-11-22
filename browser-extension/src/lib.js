// Pure helpers shared by the service worker and the options page.
// No chrome.* APIs here, so this file can be unit-tested with `node --test`.

export const DEFAULT_SETTINGS = {
  serverUrl: "http://localhost:5000",
  defaultPreset: "",
  cwd: "",
  rules: [], // [{ pattern: "youtube.com/playlist", preset: "yt-dlp Audio" }]
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

/** Only web URLs are sent; this blocks javascript:, file:, chrome:, data: etc. */
export function isSendableUrl(raw) {
  try {
    return SENDABLE_PROTOCOLS.has(new URL(raw).protocol);
  } catch {
    return false;
  }
}

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
 * Pick the preset for a URL. The most specific matching rule wins: the longest
 * host first, then the longest path. Falls back to the default preset.
 * Returns { preset, rule } where rule is null when the default was used.
 */
export function resolvePreset(rawUrl, rules, defaultPreset) {
  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    return { preset: defaultPreset || "", rule: null };
  }
  const pathname = url.pathname.toLowerCase();
  let best = null;
  let bestScore = [-1, -1];
  for (const rule of rules || []) {
    if (!rule || !rule.preset) continue;
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
  return best ? { preset: best.preset, rule: best } : { preset: defaultPreset || "", rule: null };
}

/** Turn a failed response or network error into a message a person can act on. */
export function describeFailure(status, body) {
  if (status === 403) {
    return "The scheduler refused the request. Add this computer's IP to allowed_ips in the scheduler's config.json.";
  }
  if (body && typeof body.error === "string") return body.error;
  return `The scheduler answered with HTTP ${status}.`;
}

/** POST one URL to the scheduler. Resolves to { ok, jobs } or { ok: false, error }. */
export async function submitJob({ serverUrl, preset, url, cwd }, fetchImpl = fetch) {
  const payload = { preset, urls: [url] };
  if (cwd) payload.cwd = cwd;
  let response;
  try {
    response = await fetchImpl(`${serverUrl}/api/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    return { ok: false, error: `Could not reach the scheduler at ${serverUrl}. Is it running?` };
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    // Non-JSON body (e.g. the HTML 403 page).
  }
  if (response.status === 201 && body && Array.isArray(body.jobs)) {
    return { ok: true, jobs: body.jobs };
  }
  return { ok: false, error: describeFailure(response.status, body) };
}

/** GET the preset names from the scheduler. Throws with a readable message. */
export async function fetchPresets(serverUrl, fetchImpl = fetch) {
  let response;
  try {
    response = await fetchImpl(`${serverUrl}/api/presets`);
  } catch {
    throw new Error(`Could not reach the scheduler at ${serverUrl}. Is it running?`);
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    // fall through
  }
  if (!response.ok || !body || !Array.isArray(body.presets)) {
    throw new Error(describeFailure(response.status, body));
  }
  return body.presets.map((p) => p.name).filter(Boolean);
}
