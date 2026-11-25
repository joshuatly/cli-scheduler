# CLI Scheduler Sender (Chrome extension)

Right-click a **link** to send that link, or right-click anywhere on a **page** to send the page's address, to your CLI Scheduler. If you run more than one scheduler (say, a desktop and a NAS), add each one as an **instance**. The instance and preset are chosen by rules based on the link's domain. When no rule matches, the link goes to a default preset, or nowhere if you prefer. You can also pick a preset by hand from a submenu.

Works in Chrome 116+ and other Chromium browsers (Edge, Brave). No changes to the scheduler are needed. It uses the existing `GET /api/presets` and `POST /api/jobs` endpoints.

## Install

1. Download `cli-scheduler-sender-<version>.zip` from the [Releases](https://github.com/joshuatly/cli-scheduler/releases) page and unzip it, or use `browser-extension/src/` from a checkout.
2. Open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**, and choose the unzipped folder (the one containing `manifest.json`).
3. The settings page opens. Enter the scheduler address (e.g. `http://192.168.1.10:5000`), click **Test connection**, allow the permission prompt, choose what happens when no rule matches (a default preset, or **Do nothing**), and click **Save**.
4. To add another scheduler, click **Add instance**, give it a name and an address, and click **Save** again. Chrome asks once for permission to reach each new address.

Once an instance is saved and connected, it folds to one line showing its name, address and how many presets it has (or **Can't connect** in red). Click the line to edit it.

The computer running Chrome must be allowed by each scheduler's `allowed_ips` in `config.json`, otherwise sending fails with a 403 error.

The settings page links to this repository, its issues and its releases.

### Upgrading from 0.1.x

Your existing server, working directory, default preset and rules become a single instance automatically. Nothing needs to be re-entered. If you had no default preset, **When no rule matches** is set to **Do nothing**. The old settings keys are left in place, so another computer whose Chrome is still on 0.1.x keeps working.

## Use

| Right-click on | Menu item | Sends |
|---|---|---|
| A link | **Send link to CLI Scheduler** | The link's URL |
| Empty space on a page | **Send page to CLI Scheduler** | The page's URL |

With the preset submenu on (the default), each item opens a submenu: **Auto (domain rules)** or any preset by name. With it off, clicking the item sends straight away using the rules.

With several instances, the submenu lists every instance's presets, grouped by instance and separated by lines. A preset name that exists on more than one instance is shown with the instance name, e.g. **Echo Test (Home)** and **Echo Test (NAS)**. Names that exist on one instance only are shown as they are.

A notification confirms the job was queued and, with several instances, says which one (`Queued with "Audio" on NAS`); clicking it opens the job on that scheduler. While a link is being sent, the toolbar icon shows **…**. Errors (server unreachable, preset not found, IP not allowed) are always shown. A scheduler that doesn't answer within 8 seconds (5 seconds when loading presets or testing the connection) is treated as unreachable, so a switched-off or unreachable instance fails quickly instead of hanging. If a send times out, the request may still have arrived, so check that scheduler's job list before sending again. Only `http://` and `https://` URLs are sent.

Clicking the toolbar icon opens the settings.

## Domain rules

| Pattern | Matches |
|---|---|
| `youtube.com` | youtube.com and every subdomain: `www.`, `m.`, `music.` |
| `music.youtube.com` | that subdomain and below only |
| `youtube.com/playlist` | `/playlist` and paths below it on youtube.com and its subdomains |

`https://`, `*.` and `www.` in a pattern are ignored, so pasting a URL works. When several rules match, the longest host wins, then the longest path. If nothing matches, **When no rule matches** decides:

| Setting | What happens to an unmatched link |
|---|---|
| **Send to a default preset** | It's sent to the default preset on the chosen instance. |
| **Do nothing** | Nothing is sent. A notification says no rule matched and offers two buttons (see below). |

With the submenu off, **Do nothing** makes the menu item act only on links that a rule covers. With it on, **Auto (domain rules)** behaves the same way, and you can still pick any preset by hand.

When a link isn't sent because nothing matched, the notification **Not sent: no rule for example.org** has two buttons:

- **Add a rule for example.org** opens the settings with a new rule for that site already filled in. The cursor is in its preset box, so you only pick the preset (and the instance, with several) and press **Save**. Clicking the notification itself does the same.
- **Set a default preset** opens the settings with **When no rule matches** switched to **Send to a default preset** and the cursor in the preset box.

Nothing changes until you press **Save**. If the settings page is already open, it's reused, with any unsaved edits kept. Use **Check which preset a URL gets** on the settings page to try it out. It also warns when the chosen instance has no preset with that name.

Each rule, and the default, sends to **one preset on one instance**: with several instances, every rule has an instance picker next to its preset picker, and the preset picker lists only that instance's presets. If a saved preset is no longer on its instance (it was renamed, say), it stays selected and is marked **(not on …)** until you pick another. Two rules for the same address (`youtube.com` and `https://www.youtube.com/`, for example) can't be saved, so a domain never goes to two places. A different path (`youtube.com/playlist`) is a different address and can point at another instance. Removing an instance also removes the rules that send to it, after asking.

Settings are stored in `chrome.storage.sync`, so they follow your Chrome profile across computers. Each instance has its own optional working directory, since paths differ between machines.

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
| `src/lib.js` | Settings migration and validation, rule matching, menu labels and API calls (unit-tested, no `chrome.*`) |
| `src/options.*` | Settings page |

## Release

The `Browser extension` workflow (`.github/workflows/browser-extension.yml`) runs the tests and builds the zip on every pull request and push to `main` that touches `browser-extension/`. The zip is attached to the run as an artifact.

To publish a release:

1. Bump `version` in `src/manifest.json` and merge it to `main`.
2. Tag that commit and push the tag:
   ```bash
   git tag extension-v0.2.0
   git push origin extension-v0.2.0
   ```

The workflow checks that the tag matches the manifest version, builds the zip and creates a GitHub release named **Browser extension 0.2.0** with the zip attached. You can also run the workflow by hand from the Actions tab to get a build without releasing.
