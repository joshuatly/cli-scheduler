import { test } from "node:test";
import assert from "node:assert/strict";

import {
  describeFailure,
  fetchPresets,
  isSendableUrl,
  normalizeServerUrl,
  originPattern,
  parsePattern,
  resolvePreset,
  submitJob,
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
  { pattern: "youtube.com", preset: "YT video" },
  { pattern: "youtube.com/playlist", preset: "YT playlist" },
  { pattern: "music.youtube.com", preset: "YT audio" },
  { pattern: "soundcloud.com", preset: "Audio" },
];

test("resolvePreset picks the most specific rule", () => {
  const r = (url) => resolvePreset(url, RULES, "Default").preset;
  assert.equal(r("https://www.youtube.com/watch?v=1"), "YT video");
  assert.equal(r("https://m.youtube.com/watch?v=1"), "YT video");
  assert.equal(r("https://youtube.com/playlist?list=1"), "YT playlist");
  assert.equal(r("https://music.youtube.com/playlist?list=1"), "YT audio");
  assert.equal(r("https://soundcloud.com/a/b"), "Audio");
  assert.equal(r("https://example.com/"), "Default");
});

test("resolvePreset does not match look-alike hosts or partial path segments", () => {
  const r = (url) => resolvePreset(url, RULES, "Default").preset;
  assert.equal(r("https://notyoutube.com/watch"), "Default");
  assert.equal(r("https://youtube.com.evil.example/watch"), "Default");
  assert.equal(r("https://youtube.com/playlists"), "YT video");
});

test("resolvePreset reports the rule used and handles bad input", () => {
  assert.equal(resolvePreset("https://soundcloud.com", RULES, "").rule.pattern, "soundcloud.com");
  assert.deepEqual(resolvePreset("https://x.org", RULES, ""), { preset: "", rule: null });
  assert.deepEqual(resolvePreset("not a url", RULES, "D"), { preset: "D", rule: null });
  assert.equal(resolvePreset("https://a.com", [{ pattern: "a.com", preset: "" }], "D").preset, "D");
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
