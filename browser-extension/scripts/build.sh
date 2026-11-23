#!/usr/bin/env bash
# Package src/ into dist/cli-scheduler-sender-<version>.zip, ready to load
# in Chrome or upload to the Chrome Web Store.
# If EXPECTED_VERSION is set (CI on a release tag), it must equal the manifest version.
set -euo pipefail

cd "$(dirname "$0")/.."

version=$(node -e 'process.stdout.write(JSON.parse(require("fs").readFileSync("src/manifest.json","utf8")).version)')
if [[ ! "$version" =~ ^[0-9]+(\.[0-9]+){0,3}$ ]]; then
  echo "manifest.json version '$version' is not a valid Chrome extension version" >&2
  exit 1
fi
if [[ -n "${EXPECTED_VERSION:-}" && "$EXPECTED_VERSION" != "$version" ]]; then
  echo "Tag version '$EXPECTED_VERSION' does not match manifest.json version '$version'" >&2
  exit 1
fi

# Every file the manifest points at must exist.
node -e '
  const fs = require("fs");
  const m = JSON.parse(fs.readFileSync("src/manifest.json", "utf8"));
  const files = [m.background.service_worker, m.options_ui.page,
    ...Object.values(m.icons), ...Object.values(m.action.default_icon)];
  const missing = files.filter((f) => !fs.existsSync("src/" + f));
  if (missing.length) { console.error("Missing files:", missing.join(", ")); process.exit(1); }
'

mkdir -p dist
out="dist/cli-scheduler-sender-${version}.zip"
rm -f "$out"
(cd src && zip -qr -X "../$out" . -x '.*')
echo "$out"
