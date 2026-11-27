#!/bin/sh
# UI check: a real browser clicks through the built interface (web/dist) on the mock backend. See web/e2e/check.py.
#   scripts/ui-check.sh [--only a,b] [--list] [--shots DIR]
# Playwright comes through uv (the version of the Chromium Harness installs); nothing is added to the repository.
set -eu
cd "$(dirname "$0")/.."
# The translations first (complete, made from the current English text, nothing smuggled in): scripts/i18n_check.py.
if [ -f scripts/i18n_check.py ] && [ -d server/maxxing ]; then python3 scripts/i18n_check.py --quiet; fi
exec env -u PYTHONPATH uv run -q --no-project --with playwright==1.56.0 python web/e2e/check.py "$@"
