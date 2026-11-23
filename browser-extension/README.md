# CLI Scheduler Sender (Chrome extension)

Right-click a **link** to send that link, or right-click anywhere on a **page** to send the page's address, to your CLI Scheduler. The preset is chosen by rules based on the link's domain, with a default preset as fallback. You can also pick a preset by hand from a submenu.

Works in Chrome 116+ and other Chromium browsers (Edge, Brave). No changes to the scheduler are needed. It uses the existing `GET /api/presets` and `POST /api/jobs` endpoints.

## Install

1. Download `cli-scheduler-sender-<version>.zip` from the [Releases](https://github.com/joshuatly/cli-scheduler/releases) page and unzip it, or use `browser-extension/src/` from a checkout.
2. Open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**, and choose the unzipped folder (the one containing `manifest.json`).
3. The settings page opens. Enter the scheduler address (e.g. `http://192.168.1.10:5000`), click **Test connection**, allow the permission prompt, choose a default preset, and click **Save**.

The computer running Chrome must be allowed by the scheduler's `allowed_ips` in `config.json`, otherwise sending fails with a 403 error.

## Use

| Right-click on | Menu item | Sends |
|---|---|---|
| A link | **Send link to CLI Scheduler** | The link's URL |
| Empty space on a page | **Send page to CLI Scheduler** | The page's URL |

With the preset submenu on (the default), each item opens a submenu: **Auto (domain rules)** or any preset by name. With it off, clicking the item sends straight away using the rules.

A notification confirms the job was queued; clicking it opens the job in the scheduler. Errors (server unreachable, preset not found, IP not allowed) are always shown. Only `http://` and `https://` URLs are sent.

Clicking the toolbar icon opens the settings.

## Domain rules

| Pattern | Matches |
|---|---|
| `youtube.com` | youtube.com and every subdomain: `www.`, `m.`, `music.` |
| `music.youtube.com` | that subdomain and below only |
| `youtube.com/playlist` | `/playlist` and paths below it on youtube.com and its subdomains |

`https://`, `*.` and `www.` in a pattern are ignored, so pasting a URL works. When several rules match, the longest host wins, then the longest path. If nothing matches, the default preset is used. Use **Check which preset a URL gets** on the settings page to try it out.

Settings are stored in `chrome.storage.sync`, so they follow your Chrome profile across computers.

## Develop

```bash
cd browser-extension
npm test          # unit tests (Node 18+, no dependencies)
npm run build     # writes dist/cli-scheduler-sender-<version>.zip
```

Load `browser-extension/src/` unpacked while developing, and click the reload icon on `chrome://extensions` after editing.

| File | Purpose |
|---|---|
| `src/manifest.json` | Manifest V3 definition |
| `src/background.js` | Context menus, sending, notifications |
| `src/lib.js` | Rule matching and API calls (unit-tested, no `chrome.*`) |
| `src/options.*` | Settings page |

## Release

The `Browser extension` workflow (`.github/workflows/browser-extension.yml`) runs the tests and builds the zip on every pull request and push to `main` that touches `browser-extension/`.

Releases are automatic. When a push to `main` carries a `version` in `src/manifest.json` that has no release yet, the workflow tags the commit `extension-v<version>` and publishes a GitHub release named **Browser extension <version>** with the zip attached. Later pushes with the same version only build. The zip is then attached to the run as an artifact.

To publish a new release, bump `version` in `src/manifest.json` (e.g. `0.1.0` → `0.2.0`) in your PR and merge it.

You can also run the workflow by hand from the Actions tab: on `main` it releases the current version if it isn't released yet; on another branch it only builds.
