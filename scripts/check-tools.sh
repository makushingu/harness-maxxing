#!/usr/bin/env bash
# Smoke test of the pinned tools after scripts/bump-pins.sh (maintainers only - the installer never runs this):
# installs them from this checkout into a throwaway directory, the way `maxxing deps update` does, and uses them.
#   scrapling   templates/scrapling/requirements.txt (--require-hashes); Playwright and Patchright on one Chromium
#               revision; `extract get` (HTTP) and `extract fetch` (browser) of a page
#   chromium    the revision of that lock, downloaded by both drivers
#   remotion    `npm ci` of templates/remotion, a still of the template rendered with that Chromium
#   pdf         an HTML page printed to PDF with that Chromium
# Nothing outside the throwaway directory is touched. Network: PyPI, npm, Playwright's CDN, the test page.
# Usage: scripts/check-tools.sh [URL (https://example.com)]   exit 0 = every check passed
set -euo pipefail
cd "$(dirname "$0")/.."
URL=${1:-https://example.com}
W=$(mktemp -d /tmp/mx-check-tools-XXXXXX)
trap 'rm -rf "$W"' EXIT
export PLAYWRIGHT_BROWSERS_PATH="$W/browsers" UV_CACHE_DIR="$W/uvcache" npm_config_cache="$W/npmcache"
fail=0
ok() { echo "  OK    $1"; }
ko() { echo "  FAIL  $1" >&2; fail=1; }

echo "scrapling $(sed -n '/^\[scrapling\]/,/^\[/s/^version = "\(.*\)"$/\1/p' server/maxxing/deps.toml)"
uv venv -q --python 3.12 "$W/scrapling"
PY="$W/scrapling/bin/python"
uv pip install -q --python "$PY" --require-hashes -r templates/scrapling/requirements.txt
ok "lock installs with every hash checked"
revs=$("$PY" -I - <<'PY'
import json, pathlib, importlib.util
out = set()
for mod in ("playwright", "patchright"):
    spec = importlib.util.find_spec(mod)
    f = pathlib.Path(spec.origin).parent / "driver" / "package" / "browsers.json"
    out |= {b["revision"] for b in json.loads(f.read_text())["browsers"] if b["name"] == "chromium"}
print(" ".join(sorted(out)))
PY
)
[ "$(wc -w <<<"$revs")" = 1 ] && ok "Playwright and Patchright share Chromium $revs" || ko "Chromium revisions differ: $revs"
"$PY" -m playwright install --no-shell chromium >/dev/null 2>&1 && "$PY" -m patchright install --no-shell chromium >/dev/null 2>&1 \
  && ok "Chromium $revs downloaded by both drivers" || ko "Chromium download"
CHROME=$(ls "$W"/browsers/chromium-*/chrome-linux*/chrome 2>/dev/null | head -n1)
[ -x "$CHROME" ] || { ko "no Chromium binary"; exit 1; }
"$W/scrapling/bin/scrapling" extract get "$URL" "$W/get.md" >/dev/null 2>&1 && [ -s "$W/get.md" ] \
  && ok "extract get $URL" || ko "extract get $URL"
"$W/scrapling/bin/scrapling" extract fetch "$URL" "$W/fetch.md" >/dev/null 2>&1 && [ -s "$W/fetch.md" ] \
  && ok "extract fetch $URL (browser)" || ko "extract fetch $URL (browser)"
"$PY" -I -c 'from scrapling.fetchers import Fetcher, StealthyFetcher' && ok "Python imports of the skill" \
  || ko "Python imports of the skill (scrapling.fetchers)"

echo "remotion $(sed -n '/^\[remotion\]/,/^\[/s/^version = "\(.*\)"$/\1/p' server/maxxing/deps.toml)"
cp -r templates/remotion "$W/video"
(cd "$W/video" && npm ci --no-audit --no-fund --silent) && ok "npm ci of the lock" || ko "npm ci of the lock"
(cd "$W/video" && REMOTION_BROWSER_EXECUTABLE="$CHROME" npx remotion still src/index.jsx Intro out.png --frame=30 \
  >"$W/still.log" 2>&1) && [ -s "$W/video/out.png" ] && ok "still of the template rendered" \
  || { ko "still of the template"; tail -5 "$W/still.log" >&2; }

echo "pdf"
printf '<!doctype html><h1>Harness Maxxing</h1>' > "$W/p.html"
"$CHROME" --headless --no-sandbox --disable-gpu --no-pdf-header-footer --print-to-pdf="$W/p.pdf" "file://$W/p.html" \
  >/dev/null 2>&1 && [ -s "$W/p.pdf" ] && ok "HTML printed to PDF" || ko "HTML printed to PDF"

[ "$fail" = 0 ] && echo "all tools OK" || { echo "some tools FAILED" >&2; exit 1; }
