import { test } from "node:test";
import assert from "node:assert/strict";

import {
  LEGACY_INSTANCE_ID,
  defaultInstanceName,
  describeFailure,
  describeTarget,
  effectiveDefault,
  fetchPresets,
  instanceLabel,
  isSendableUrl,
  migrateSettings,
  newInstanceId,
  normalizePresetCache,
  normalizeServerUrl,
  originPattern,
  originPatterns,
  parsePattern,
  presetMenuEntries,
  resolveTarget,
  submitJob,
  validateSettings,
} from "../src/lib.js";

test("normalizeServerUrl adds a scheme and strips trailing slashes", () => {
  assert.equal(normalizeServerUrl("192.168.1.5:5000"), "http://192.168.1.5:5000");
  assert.equal(normalizeServerUrl(" http://host:5000/ "), "http://host:5000");
  assert.equal(normalizeServerUrl("https://proxy.lan/scheduler/"), "https://proxy.lan/scheduler");
  assert.throws(() => normalizeServerUrl(""), /empty/);
  assert.throws(() => normalizeServerUrl("ftp://host"), /http/);
});

test("originPattern drops the port", () => {
  assert.equal(originPattern("http://192.168.1.5:5000"), "http://192.168.1.5/*");
});

test("isSendableUrl only allows web URLs", () => {
  assert.ok(isSendableUrl("https://example.com/a"));
  assert.ok(isSendableUrl("http://example.com"));
  for (const bad of ["javascript:alert(1)", "file:///etc/passwd", "chrome://settings", "data:text/html,x", "nope", undefined]) {
    assert.equal(isSendableUrl(bad), false, String(bad));
  }
});

test("parsePattern accepts common spellings", () => {
  const yt = { host: "youtube.com", path: "" };
  for (const p of ["youtube.com", "*.youtube.com", "www.youtube.com", "https://www.youtube.com/", "YouTube.com:443"]) {
    assert.deepEqual(parsePattern(p), yt, p);
  }
  assert.deepEqual(parsePattern("youtube.com/Playlist/"), { host: "youtube.com", path: "/playlist" });
  assert.equal(parsePattern(""), null);
  assert.equal(parsePattern("foo bar.com"), null);
  assert.equal(parsePattern("*"), null);
});

const RULES = [
  { pattern: "youtube.com", instanceId: "home", preset: "YT video" },
  { pattern: "youtube.com/playlist", instanceId: "home", preset: "YT playlist" },
  { pattern: "music.youtube.com", instanceId: "nas", preset: "YT audio" },
  { pattern: "soundcloud.com", instanceId: "nas", preset: "Audio" },
];
const DEFAULT = { instanceId: "home", preset: "Default" };

test("resolveTarget picks the most specific rule", () => {
  const r = (url) => resolveTarget(url, RULES, DEFAULT).preset;
  assert.equal(r("https://www.youtube.com/watch?v=1"), "YT video");
  assert.equal(r("https://m.youtube.com/watch?v=1"), "YT video");
  assert.equal(r("https://youtube.com/playlist?list=1"), "YT playlist");
  assert.equal(r("https://music.youtube.com/playlist?list=1"), "YT audio");
  assert.equal(r("https://soundcloud.com/a/b"), "Audio");
  assert.equal(r("https://example.com/"), "Default");
});

test("resolveTarget sends each match to the rule's single instance", () => {
  const t = (url) => {
    const { instanceId, preset } = resolveTarget(url, RULES, DEFAULT);
    return `${instanceId}/${preset}`;
  };
  assert.equal(t("https://youtube.com/watch"), "home/YT video");
  assert.equal(t("https://music.youtube.com/watch"), "nas/YT audio");
  assert.equal(t("https://soundcloud.com/x"), "nas/Audio");
  assert.equal(t("https://example.com/"), "home/Default");
});

test("resolveTarget does not match look-alike hosts or partial path segments", () => {
  const r = (url) => resolveTarget(url, RULES, DEFAULT).preset;
  assert.equal(r("https://notyoutube.com/watch"), "Default");
  assert.equal(r("https://youtube.com.evil.example/watch"), "Default");
  assert.equal(r("https://youtube.com/playlists"), "YT video");
});

test("resolveTarget reports the rule used and handles bad input", () => {
  assert.equal(resolveTarget("https://soundcloud.com", RULES, null).rule.pattern, "soundcloud.com");
  assert.deepEqual(resolveTarget("https://x.org", RULES, null), { instanceId: "", preset: "", rule: null });
  assert.deepEqual(resolveTarget("not a url", RULES, DEFAULT), { ...DEFAULT, rule: null });
  // Rules missing a preset or an instance are skipped.
  assert.equal(resolveTarget("https://a.com", [{ pattern: "a.com", instanceId: "home", preset: "" }], DEFAULT).preset, "Default");
  assert.equal(resolveTarget("https://a.com", [{ pattern: "a.com", instanceId: "", preset: "P" }], DEFAULT).preset, "Default");
});

// --- Settings migration and validation ---------------------------------------

test("migrateSettings turns 0.1.x settings into one instance", () => {
  const old = {
    serverUrl: "http://192.168.1.5:5000",
    cwd: "/data",
    defaultPreset: "Echo",
    rules: [{ pattern: "youtube.com", preset: "yt-dlp" }],
    presetSubmenu: false,
    notifyOnSuccess: true,
  };
  const s = migrateSettings(old);
  assert.equal(s.schemaVersion, 2);
  assert.deepEqual(s.instances, [{ id: LEGACY_INSTANCE_ID, name: "", serverUrl: "http://192.168.1.5:5000", cwd: "/data" }]);
  assert.deepEqual(s.defaultTarget, { instanceId: LEGACY_INSTANCE_ID, preset: "Echo" });
  assert.equal(s.defaultAction, "preset");
  assert.deepEqual(s.rules, [{ pattern: "youtube.com", instanceId: LEGACY_INSTANCE_ID, preset: "yt-dlp" }]);
  assert.equal(s.presetSubmenu, false);
  // Repeatable: the same input always gives the same ids.
  assert.deepEqual(migrateSettings(old), s);
});

test("migrateSettings gives a fresh install one localhost instance", () => {
  const s = migrateSettings({});
  assert.equal(s.instances.length, 1);
  assert.equal(s.instances[0].serverUrl, "http://localhost:5000");
  assert.deepEqual(s.rules, []);
  assert.equal(s.presetSubmenu, true);
  assert.equal(s.notifyOnSuccess, true);
  // No default preset yet, so unmatched links aren't sent until one is chosen.
  assert.equal(s.defaultAction, "none");
});

test("migrateSettings maps an empty 0.1.x default preset to Do nothing", () => {
  assert.equal(migrateSettings({ serverUrl: "http://h", defaultPreset: "" }).defaultAction, "none");
});

test("migrateSettings keeps an explicit default action", () => {
  const base = { instances: [{ id: "a", serverUrl: "http://a" }], defaultTarget: { instanceId: "a", preset: "P" } };
  assert.equal(migrateSettings({ ...base, defaultAction: "none" }).defaultAction, "none");
  assert.equal(migrateSettings({ ...base, defaultAction: "preset" }).defaultAction, "preset");
  assert.equal(migrateSettings(base).defaultAction, "preset");
  assert.equal(migrateSettings({ ...base, defaultAction: "bogus" }).defaultAction, "preset");
  // The default preset is kept while Do nothing is on, so switching back restores it.
  assert.deepEqual(migrateSettings({ ...base, defaultAction: "none" }).defaultTarget, base.defaultTarget);
});

test("Do nothing: unmatched URLs resolve to no preset, matched ones still go to their rule", () => {
  const settings = { defaultAction: "none", defaultTarget: { instanceId: "home", preset: "Default" } };
  assert.equal(effectiveDefault(settings), null);
  assert.equal(resolveTarget("https://example.com/", RULES, effectiveDefault(settings)).preset, "");
  assert.equal(resolveTarget("https://soundcloud.com/x", RULES, effectiveDefault(settings)).preset, "Audio");
  const send = { ...settings, defaultAction: "preset" };
  assert.equal(resolveTarget("https://example.com/", RULES, effectiveDefault(send)).preset, "Default");
});

test("migrateSettings keeps 0.2 settings and ignores stale 0.1 keys", () => {
  const stored = {
    schemaVersion: 2,
    serverUrl: "http://old:5000",
    defaultPreset: "Old",
    instances: [
      { id: "a", name: "Home", serverUrl: "http://a:5000", cwd: "" },
      { id: "b", name: "NAS", serverUrl: "http://b:5000", cwd: "/x" },
    ],
    defaultTarget: { instanceId: "b", preset: "Audio" },
    rules: [{ pattern: "a.com", instanceId: "a", preset: "P" }],
  };
  const s = migrateSettings(stored);
  assert.deepEqual(s.instances, stored.instances);
  assert.deepEqual(s.defaultTarget, stored.defaultTarget);
  assert.deepEqual(s.rules, stored.rules);
});

test("normalizePresetCache reads the 0.1.x array cache", () => {
  assert.deepEqual(normalizePresetCache(["A"]), { [LEGACY_INSTANCE_ID]: ["A"] });
  assert.deepEqual(normalizePresetCache({ a: ["A"] }), { a: ["A"] });
  assert.deepEqual(normalizePresetCache(undefined), {});
});

const TWO = [
  { id: "home", name: "Home", serverUrl: "http://192.168.1.10:5000", cwd: "" },
  { id: "nas", name: "NAS", serverUrl: "http://nas.lan:5000", cwd: "" },
];
const valid = (over = {}) => ({
  instances: TWO,
  defaultAction: "preset",
  defaultTarget: { instanceId: "home", preset: "Echo" },
  rules: [
    { pattern: "youtube.com", instanceId: "home", preset: "Video" },
    { pattern: "music.youtube.com", instanceId: "nas", preset: "Audio" },
  ],
  ...over,
});

test("validateSettings accepts a good multi-instance setup", () => {
  assert.equal(validateSettings(valid()), null);
});

test("validateSettings: a default preset is required unless Do nothing is chosen", () => {
  const empty = { defaultTarget: { instanceId: "home", preset: "" } };
  assert.match(validateSettings(valid(empty)), /Do nothing/);
  assert.equal(validateSettings(valid({ ...empty, defaultAction: "none" })), null);
  // A leftover default pointing at a removed instance doesn't matter with Do nothing.
  assert.equal(validateSettings(valid({ defaultAction: "none", defaultTarget: { instanceId: "gone", preset: "P" } })), null);
});

test("validateSettings rejects a domain that would go to two places", () => {
  for (const pattern of ["youtube.com", "www.youtube.com", "https://YouTube.com/", "*.youtube.com"]) {
    const rules = [
      { pattern: "youtube.com", instanceId: "home", preset: "Video" },
      { pattern, instanceId: "nas", preset: "Video" },
    ];
    assert.match(validateSettings(valid({ rules })), /same address/, pattern);
  }
  // Same host with a different path is a different rule.
  const rules = [
    { pattern: "youtube.com", instanceId: "home", preset: "Video" },
    { pattern: "youtube.com/playlist", instanceId: "nas", preset: "Video" },
  ];
  assert.equal(validateSettings(valid({ rules })), null);
});

test("validateSettings requires each rule to name an existing instance and a preset", () => {
  assert.match(validateSettings(valid({ rules: [{ pattern: "a.com", instanceId: "gone", preset: "P" }] })), /choose which instance/);
  assert.match(validateSettings(valid({ rules: [{ pattern: "a.com", instanceId: "home", preset: "" }] })), /needs a preset/);
  assert.match(validateSettings(valid({ rules: [{ pattern: "a b", instanceId: "home", preset: "P" }] })), /valid domain/);
  assert.match(validateSettings(valid({ defaultTarget: { instanceId: "gone", preset: "P" } })), /default preset/);
});

test("validateSettings requires distinct instance names and valid addresses", () => {
  assert.match(validateSettings(valid({ instances: [] })), /at least one/);
  const sameName = [TWO[0], { ...TWO[1], name: "home" }];
  assert.match(validateSettings(valid({ instances: sameName })), /Two instances are called/);
  // Unnamed instances fall back to their address, which must also differ.
  const unnamed = [
    { id: "x", name: "", serverUrl: "http://h:5000" },
    { id: "y", name: "", serverUrl: "http://h:5000" },
  ];
  assert.match(validateSettings({ instances: unnamed, rules: [], defaultAction: "none" }), /Two instances are called "h:5000"/);
  const bad = [{ id: "x", name: "X", serverUrl: "ftp://h" }];
  assert.match(validateSettings({ instances: bad, rules: [], defaultAction: "none" }), /Instance "X".*http/);
});

// --- Labels -------------------------------------------------------------------

test("presetMenuEntries disambiguates only names shared by several instances", () => {
  const entries = presetMenuEntries(TWO, { home: ["Echo", "Video"], nas: ["Echo", "Audio"] });
  assert.deepEqual(
    entries.map((e) => [e.instanceId, e.preset, e.title, e.groupStart]),
    [
      ["home", "Echo", "Echo (Home)", false],
      ["home", "Video", "Video", false],
      ["nas", "Echo", "Echo (NAS)", true],
      ["nas", "Audio", "Audio", false],
    ],
  );
});

test("presetMenuEntries handles one instance, empty and missing lists", () => {
  assert.deepEqual(
    presetMenuEntries([TWO[0]], { home: ["Echo", "Echo"] }).map((e) => e.title),
    ["Echo"],
  );
  const entries = presetMenuEntries(TWO, { nas: ["Audio"] });
  assert.deepEqual(entries, [{ instanceId: "nas", preset: "Audio", title: "Audio", groupStart: false }]);
});

test("describeTarget names the instance only when there are several", () => {
  assert.equal(describeTarget([TWO[0]], "home", "Echo"), '"Echo"');
  assert.equal(describeTarget(TWO, "nas", "Echo"), '"Echo" on NAS');
  assert.equal(describeTarget(TWO, "gone", "Echo"), '"Echo" on (removed instance)');
});

test("instance names fall back to the address", () => {
  assert.equal(defaultInstanceName("http://192.168.1.10:5000"), "192.168.1.10:5000");
  assert.equal(defaultInstanceName("https://proxy.lan/scheduler"), "proxy.lan/scheduler");
  assert.equal(instanceLabel({ name: "  ", serverUrl: "http://h:1" }), "h:1");
  assert.equal(instanceLabel({ name: "Home", serverUrl: "http://h:1" }), "Home");
});

test("newInstanceId avoids taken ids and the menu separator", () => {
  let n = 0;
  const seq = [0, 0, 0.5];
  const id = newInstanceId(["i000000"], () => seq[n++]);
  assert.notEqual(id, "i000000");
  assert.match(id, /^i[0-9a-z]{6}$/);
  assert.ok(!newInstanceId().includes("::"));
});

test("originPatterns dedupes hosts and skips bad addresses", () => {
  const patterns = originPatterns([
    { serverUrl: "http://h:5000" },
    { serverUrl: "http://h:6000" },
    { serverUrl: "https://nas.lan" },
    { serverUrl: "not a url" },
  ]);
  assert.deepEqual(patterns, ["http://h/*", "https://nas.lan/*"]);
});

function fakeFetch(status, body, capture = {}) {
  return async (url, init) => {
    capture.url = url;
    capture.init = init;
    return {
      status,
      ok: status >= 200 && status < 300,
      json: async () => {
        if (body === undefined) throw new Error("not json");
        return body;
      },
    };
  };
}

test("submitJob posts the API payload", async () => {
  const seen = {};
  const res = await submitJob(
    { serverUrl: "http://h:5000", preset: "P", url: "https://a.com", cwd: "/tmp" },
    fakeFetch(201, { jobs: [{ id: "1" }] }, seen),
  );
  assert.deepEqual(res, { ok: true, jobs: [{ id: "1" }] });
  assert.equal(seen.url, "http://h:5000/api/jobs");
  assert.equal(seen.init.method, "POST");
  assert.deepEqual(JSON.parse(seen.init.body), { preset: "P", urls: ["https://a.com"], cwd: "/tmp" });
});

test("submitJob omits an empty cwd", async () => {
  const seen = {};
  await submitJob({ serverUrl: "http://h", preset: "P", url: "https://a.com", cwd: "" }, fakeFetch(201, { jobs: [] }, seen));
  assert.equal("cwd" in JSON.parse(seen.init.body), false);
});

test("submitJob turns failures into readable errors", async () => {
  const args = { serverUrl: "http://h", preset: "P", url: "https://a.com" };
  assert.deepEqual(await submitJob(args, fakeFetch(400, { error: "Preset 'P' not found" })), {
    ok: false,
    error: "Preset 'P' not found",
  });
  assert.match((await submitJob(args, fakeFetch(403, undefined))).error, /allowed_ips/);
  assert.match((await submitJob(args, fakeFetch(500, undefined))).error, /HTTP 500/);
  const offline = async () => {
    throw new TypeError("Failed to fetch");
  };
  assert.match((await submitJob(args, offline)).error, /Could not reach/);
});

test("fetchPresets returns names", async () => {
  const names = await fetchPresets("http://h", fakeFetch(200, { presets: [{ name: "A" }, { name: "B" }] }));
  assert.deepEqual(names, ["A", "B"]);
  await assert.rejects(fetchPresets("http://h", fakeFetch(403, undefined)), /allowed_ips/);
});

test("describeFailure falls back to the status code", () => {
  assert.equal(describeFailure(418, null), "The scheduler answered with HTTP 418.");
});
