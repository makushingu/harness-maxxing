# Harness Maxxing v2 - development rules

Product & architecture: docs/dev/PLAN.md · HTTP contract: docs/dev/API.md · module interfaces:
docs/dev/INTERNALS.md · UI rules: docs/dev/DESIGN.md. Change the contract docs first, then the code.

- Repo is 100 % English, product-neutral: no personal data, names, domains, tokens or paths of the author's
  own server. Examples use `ui.example.com`, `acme`, `blog`.
- Server: Python >= 3.11, FastAPI, managed with uv (`cd server && uv sync && uv run pytest`). The turn
  runner (`maxxing/sessions/runner.py`) is stdlib-only.
- Web: React + TypeScript + Vite + Tailwind (`cd web && npm ci && npm run build`); the build output
  `web/dist` IS committed (servers do not need Node). Node lives in /root/.hermes/node/bin on the dev box.
- State writes are atomic (`config.write_json`). Never block the event loop with long work (use
  `asyncio.to_thread`).
- Tests never touch the real system: use MAXXING_STATE=/tmp/..., MAXXING_CLAUDE_BIN=fake claude,
  MAXXING_SPAWN=direct, MAXXING_CRONTAB_FILE, MAXXING_TELEGRAM_API / MAXXING_GITHUB_API mocks.
  NEVER edit the real root crontab, NEVER poll a real Telegram bot (getUpdates), NEVER touch
  /root/claude-code (that is the author's production v1) or the services claude-code-ui / claude-telegram-bot.
- Dev servers: each contributor uses its own port (8801-8809) and its own MAXXING_STATE.
- Every release: `CHANGELOG.md` entry (shown in the app in Settings -> Updates, in "What's new" after an update,
  and as the page "All updates" of the member area), `docs/dev/CHANGES.md` entry,
  `docs/upgrade/<version>.md` ("Nothing to do" when nothing to do), and the user docs page of each visible change.
  `tests/test_docs.py::test_every_version_is_documented` fails when one is missing.
- Two changelogs, both updated with every change: `CHANGELOG.md` is PUBLIC (shown in the app's "What's new"
  and by `maxxing update`): what changes for the user, plain language, no internals. `docs/dev/CHANGES.md`
  is for maintainers: API, data formats, migrations, internals.
- An important new feature (one the user would not find alone) ends its CHANGELOG.md bullet with
  `[Show me](#show:<id>)` and gets a showcase `<id>` in `web/src/features/whatsnew/showcases.ts` (route + `data-tour`
  target, or a centered card with a "Try it" action) with its `show.<id>.*` texts in both languages: What's new turns
  the link into a button that spotlights the feature. Terminal and Telegram drop the link.
