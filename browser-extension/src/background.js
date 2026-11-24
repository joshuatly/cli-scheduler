import {
  SCHEMA_VERSION,
  describeTarget,
  effectiveDefault,
  fetchPresets,
  isSendableUrl,
  migrateSettings,
  setupHash,
  suggestPattern,
  normalizePresetCache,
  originPattern,
  presetMenuEntries,
  resolveTarget,
  submitJob,
} from "./lib.js";

const AUTO = "auto";
const SEP = "::";
const ICON = "icons/icon128.png";

// --- Settings ---------------------------------------------------------------

async function getSettings() {
  return migrateSettings(await chrome.storage.sync.get(null));
}

/** Write 0.1.x settings back in the current shape, once, after an update. */
async function persistMigration() {
  const stored = await chrome.storage.sync.get(null);
  if (stored.schemaVersion === SCHEMA_VERSION) return;
  const { instances, defaultTarget, defaultAction, rules } = migrateSettings(stored);
  // The 0.1.x keys (serverUrl, cwd, defaultPreset) are left in place, so a
  // synced Chrome still on 0.1.x keeps working.
  await chrome.storage.sync.set({ schemaVersion: SCHEMA_VERSION, instances, defaultTarget, defaultAction, rules });
}

async function hasServerPermission(serverUrl) {
  try {
    return await chrome.permissions.contains({ origins: [originPattern(serverUrl)] });
  } catch {
    return false;
  }
}

/** Preset names per instance id from the last successful fetch. */
async function readPresetCache() {
  const { presetCache } = await chrome.storage.local.get("presetCache");
  return normalizePresetCache(presetCache);
}

/** Fetch presets from every instance, falling back to the last good list for any that are offline. */
async function loadAllPresets(settings) {
  const cache = await readPresetCache();
  const result = {};
  await Promise.all(
    settings.instances.map(async (inst) => {
      result[inst.id] = cache[inst.id] || [];
      if (!(await hasServerPermission(inst.serverUrl))) return;
      try {
        result[inst.id] = await fetchPresets(inst.serverUrl);
      } catch {
        // Offline: keep the cached list.
      }
    }),
  );
  await chrome.storage.local.set({ presetCache: result }); // also drops removed instances
  return result;
}

// --- Context menus ----------------------------------------------------------

const TARGETS = [
  { kind: "link", contexts: ["link"], title: "Send link to CLI Scheduler" },
  { kind: "page", contexts: ["page", "frame"], title: "Send page to CLI Scheduler" },
];

function create(props) {
  return new Promise((resolve) => {
    chrome.contextMenus.create(props, () => {
      void chrome.runtime.lastError; // ignore duplicate-id races
      resolve();
    });
  });
}

let rebuilding = Promise.resolve();

/** Rebuild menus; calls are serialised so overlapping rebuilds can't collide. */
function rebuildMenus() {
  rebuilding = rebuilding.then(doRebuild, doRebuild);
  return rebuilding;
}

async function doRebuild() {
  const settings = await getSettings();
  const presets = settings.presetSubmenu ? await loadAllPresets(settings) : {};
  const entries = presetMenuEntries(settings.instances, presets);
  await chrome.contextMenus.removeAll();

  for (const target of TARGETS) {
    if (!settings.presetSubmenu) {
      await create({ id: target.kind + SEP + AUTO, title: target.title, contexts: target.contexts });
      continue;
    }
    await create({ id: target.kind, title: target.title, contexts: target.contexts });
    await create({
      id: target.kind + SEP + AUTO,
      parentId: target.kind,
      title: "Auto (domain rules)",
      contexts: target.contexts,
    });
    let sep = 0;
    for (const [i, entry] of entries.entries()) {
      if (i === 0 || entry.groupStart) {
        await create({
          id: target.kind + SEP + "sep" + sep++,
          parentId: target.kind,
          type: "separator",
          contexts: target.contexts,
        });
      }
      await create({
        // Instance ids never contain SEP, so everything after the id is the preset name.
        id: [target.kind, "preset", entry.instanceId, entry.preset].join(SEP),
        parentId: target.kind,
        title: entry.title.replace(/&/g, "&&"), // a single & marks an access key in menus
        contexts: target.contexts,
      });
    }
  }
}

chrome.runtime.onInstalled.addListener(async (details) => {
  await persistMigration();
  await rebuildMenus();
  if (details.reason === "install") chrome.runtime.openOptionsPage();
});
chrome.runtime.onStartup.addListener(rebuildMenus);
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "sync") rebuildMenus();
});
chrome.permissions.onAdded.addListener(rebuildMenus);

// The options page asks for a refresh after "Test connection".
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message && message.type === "rebuild-menus") {
    rebuildMenus().then(() => sendResponse({ ok: true }));
    return true;
  }
  return false;
});

chrome.action.onClicked.addListener(() => chrome.runtime.openOptionsPage());

// --- Sending ----------------------------------------------------------------

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const [kind, mode, instanceId, ...rest] = String(info.menuItemId).split(SEP);
  const url = kind === "link" ? info.linkUrl : info.pageUrl || (tab && tab.url);
  const explicit = mode === "preset" ? { instanceId, preset: rest.join(SEP) } : null;
  await send(url, explicit);
});

async function send(url, explicit) {
  const settings = await getSettings();

  if (!url || !isSendableUrl(url)) {
    return notifyError("Only http:// and https:// links can be sent.", url);
  }

  const target = explicit || resolveTarget(url, settings.rules, effectiveDefault(settings));
  if (!target.preset) return notifyUnmatched(url);
  const instance = settings.instances.find((i) => i.id === target.instanceId);
  if (!instance) {
    return notifyError("The preset points at a scheduler instance that was removed. Open settings to fix it.", null, "options");
  }
  if (!(await hasServerPermission(instance.serverUrl))) {
    return notifyError(
      `This extension doesn't have access to ${instance.serverUrl} yet. Open its settings and press Save.`,
      null,
      "options",
    );
  }

  const where = describeTarget(settings.instances, instance.id, target.preset);
  const result = await submitJob({ serverUrl: instance.serverUrl, preset: target.preset, url, cwd: instance.cwd });
  if (!result.ok) {
    return notifyError(settings.instances.length > 1 ? `${where}: ${result.error}` : result.error, url);
  }

  flashBadge("✓", "#1a7f37");
  if (settings.notifyOnSuccess) {
    const job = result.jobs[0];
    notify(job ? `open:${instance.serverUrl}/job/${job.id}` : "", `Queued with ${where}`, url);
  }
}

// --- Feedback ---------------------------------------------------------------

function notify(id, title, message) {
  chrome.notifications.create(id || "", {
    type: "basic",
    iconUrl: ICON,
    title,
    message: String(message || "").slice(0, 300),
  });
}

function notifyError(message, url, action) {
  flashBadge("!", "#cf222e");
  notify(action === "options" ? "options:" + Date.now() : "", "CLI Scheduler: not sent", url ? `${message}\n${url}` : message);
}

/**
 * Nothing matched and there is no default: send nothing, and say how to fix
 * that next time. The id carries the URL, so the buttons still work after the
 * service worker has been stopped and restarted.
 */
function notifyUnmatched(url) {
  const site = suggestPattern(url);
  flashBadge("–", "#6e7781");
  chrome.notifications.create("unmatched:" + url, {
    type: "basic",
    iconUrl: ICON,
    title: `Not sent: no rule for ${site}`,
    message: `Add a rule to send ${site} links to a preset, or set a default preset for links that have no rule.`,
    contextMessage: url.slice(0, 200),
    buttons: [{ title: `Add a rule for ${site}` }, { title: "Set a default preset" }],
  });
}

/**
 * Show the settings page at a setup step. An open settings tab handles the
 * step itself (keeping any unsaved edits); otherwise a new tab opens.
 */
async function openSetup(step, url) {
  try {
    const reply = await chrome.runtime.sendMessage({ type: "setup", step, url });
    if (reply && reply.ok) return;
  } catch {
    // No settings page is open.
  }
  const page = chrome.runtime.getURL("options.html" + setupHash(step, url));
  try {
    await chrome.tabs.create({ url: page });
  } catch {
    // No browser window is open (e.g. all windows closed on macOS).
    await chrome.windows.create({ url: page, focused: true });
  }
}

function flashBadge(text, color) {
  chrome.action.setBadgeBackgroundColor({ color });
  chrome.action.setBadgeText({ text });
  setTimeout(() => chrome.action.setBadgeText({ text: "" }), 4000);
}

chrome.notifications.onClicked.addListener((id) => {
  if (id.startsWith("open:")) chrome.tabs.create({ url: id.slice("open:".length) });
  else if (id.startsWith("unmatched:")) openSetup("rule", id.slice("unmatched:".length));
  else if (id.startsWith("options:")) chrome.runtime.openOptionsPage();
  chrome.notifications.clear(id);
});

chrome.notifications.onButtonClicked.addListener((id, index) => {
  if (!id.startsWith("unmatched:")) return;
  openSetup(index === 0 ? "rule" : "default", id.slice("unmatched:".length));
  chrome.notifications.clear(id);
});
