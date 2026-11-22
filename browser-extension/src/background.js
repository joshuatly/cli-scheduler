import {
  DEFAULT_SETTINGS,
  fetchPresets,
  isSendableUrl,
  originPattern,
  resolvePreset,
  submitJob,
} from "./lib.js";

const AUTO = "auto";
const SEP = "::";
const ICON = "icons/icon128.png";

// --- Settings ---------------------------------------------------------------

async function getSettings() {
  const stored = await chrome.storage.sync.get(DEFAULT_SETTINGS);
  return { ...DEFAULT_SETTINGS, ...stored };
}

async function hasServerPermission(serverUrl) {
  try {
    return await chrome.permissions.contains({ origins: [originPattern(serverUrl)] });
  } catch {
    return false;
  }
}

/** Fetch presets from the server, falling back to the last good list. */
async function loadPresets(settings) {
  if (await hasServerPermission(settings.serverUrl)) {
    try {
      const presets = await fetchPresets(settings.serverUrl);
      await chrome.storage.local.set({ presetCache: presets });
      return presets;
    } catch {
      // Server offline: use the cache below.
    }
  }
  const { presetCache = [] } = await chrome.storage.local.get("presetCache");
  return presetCache;
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
  const presets = settings.presetSubmenu ? await loadPresets(settings) : [];
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
    if (presets.length) {
      await create({
        id: target.kind + SEP + "sep",
        parentId: target.kind,
        type: "separator",
        contexts: target.contexts,
      });
    }
    for (const name of presets) {
      await create({
        id: target.kind + SEP + "preset" + SEP + name,
        parentId: target.kind,
        title: name.replace(/&/g, "&&"), // a single & marks an access key in menus
        contexts: target.contexts,
      });
    }
  }
}

chrome.runtime.onInstalled.addListener(async (details) => {
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
  const [kind, mode, ...rest] = String(info.menuItemId).split(SEP);
  const url = kind === "link" ? info.linkUrl : info.pageUrl || (tab && tab.url);
  const explicitPreset = mode === "preset" ? rest.join(SEP) : null;
  await send(url, explicitPreset);
});

async function send(url, explicitPreset) {
  const settings = await getSettings();

  if (!url || !isSendableUrl(url)) {
    return notifyError("Only http:// and https:// links can be sent.", url);
  }
  if (!(await hasServerPermission(settings.serverUrl))) {
    return notifyError(
      "This extension doesn't have access to the scheduler yet. Open its settings and press Save.",
      null,
      "options",
    );
  }

  let preset = explicitPreset;
  if (!preset) {
    preset = resolvePreset(url, settings.rules, settings.defaultPreset).preset;
  }
  if (!preset) {
    return notifyError("No preset matched and no default preset is set. Open settings to choose one.", null, "options");
  }

  const result = await submitJob({ serverUrl: settings.serverUrl, preset, url, cwd: settings.cwd });
  if (!result.ok) return notifyError(result.error, url);

  flashBadge("✓", "#1a7f37");
  if (settings.notifyOnSuccess) {
    const job = result.jobs[0];
    notify(
      job ? `open:${settings.serverUrl}/job/${job.id}` : "",
      `Queued with "${preset}"`,
      url,
    );
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

function flashBadge(text, color) {
  chrome.action.setBadgeBackgroundColor({ color });
  chrome.action.setBadgeText({ text });
  setTimeout(() => chrome.action.setBadgeText({ text: "" }), 4000);
}

chrome.notifications.onClicked.addListener((id) => {
  if (id.startsWith("open:")) chrome.tabs.create({ url: id.slice("open:".length) });
  else if (id.startsWith("options:")) chrome.runtime.openOptionsPage();
  chrome.notifications.clear(id);
});
