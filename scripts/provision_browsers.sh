#!/usr/bin/env bash
# Point Playwright's browser resolution at the CloakBrowser binary (stealth) WITHOUT touching global installs.
# Creates $REPO/.pw-browsers with symlinks; crawl4ai/playwright resolve it via PLAYWRIGHT_BROWSERS_PATH.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
CLOAK_BIN="${RADAR_CLOAK_BIN:-/home/ubuntu/.cloakbrowser/chromium-146.0.7680.177.5/chrome}"
PW_REV="${1:-1243}"   # playwright revision this venv expects — check: .venv/bin/python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); print(p.chromium.executable_path); p.stop()"

mkdir -p "$REPO/.pw-browsers/chromium-$PW_REV/chrome-linux64"
mkdir -p "$REPO/.pw-browsers/chromium_headless_shell-$PW_REV/chrome-headless-shell-linux64"
ln -sf "$CLOAK_BIN" "$REPO/.pw-browsers/chromium-$PW_REV/chrome-linux64/chrome"
ln -sf "$CLOAK_BIN" "$REPO/.pw-browsers/chromium_headless_shell-$PW_REV/chrome-headless-shell-linux64/chrome-headless-shell"
touch "$REPO/.pw-browsers/chromium-$PW_REV/INSTALLATION_COMPLETE" \
      "$REPO/.pw-browsers/chromium-$PW_REV/DEPENDENCIES_VALIDATED" \
      "$REPO/.pw-browsers/chromium_headless_shell-$PW_REV/INSTALLATION_COMPLETE" \
      "$REPO/.pw-browsers/chromium_headless_shell-$PW_REV/DEPENDENCIES_VALIDATED"
test -x "$CLOAK_BIN"
echo "OK: cloak binary linked for playwright rev $PW_REV -> $CLOAK_BIN"
echo "run with: PLAYWRIGHT_BROWSERS_PATH=$REPO/.pw-browsers"
