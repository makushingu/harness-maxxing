# Contributing to Harness Maxxing

Thank you for helping. Harness Maxxing is [fair source](LICENSE): the code is public and free to use, and
contributions are welcome under the [Contributor License Agreement](CLA.md). This guide walks you from an idea to
a merged pull request.

## 1. Open an issue first

- **Bug**: open a [bug report](https://github.com/makushingu/harness-maxxing/issues/new?template=bug.yml) with the
  version (`maxxing status`), what you did, what you expected and what happened (`maxxing doctor` output helps).
- **Feature or bigger change**: open a [feature request](https://github.com/makushingu/harness-maxxing/issues/new?template=feature.yml)
  and wait for a go from a maintainer **before** writing code. It saves you a pull request that cannot be merged.
- Small fixes (typo, obvious bug, a test) can go straight to a pull request.
- **Security issue**: never a public issue - see [SECURITY.md](SECURITY.md).

## 2. Fork and branch

1. Fork the repository on GitHub, then clone your fork:
   `git clone https://github.com/<you>/harness-maxxing.git && cd harness-maxxing`
2. Create a branch from `main` named after the change:
   - `feat/<short-name>` for a feature (`feat/telegram-reactions`);
   - `fix/<short-name>` for a bug fix (`fix/cron-timezone`).
3. Keep one topic per branch and per pull request.

## 3. Development setup

Read [CLAUDE.md](CLAUDE.md) (development rules) and [docs/dev/PLAN.md](docs/dev/PLAN.md) (architecture). The HTTP
contract is [docs/dev/API.md](docs/dev/API.md), the module interfaces [docs/dev/INTERNALS.md](docs/dev/INTERNALS.md),
the UI rules [docs/dev/DESIGN.md](docs/dev/DESIGN.md): change the contract docs first, then the code.

- **Server** (Python >= 3.11, 3.12 recommended, FastAPI, [uv](https://docs.astral.sh/uv/)):
  ```bash
  cd server && uv sync && uv run pytest
  ```
  Tests never touch the real system: they use `MAXXING_STATE=/tmp/...`, a fake `claude` (`MAXXING_CLAUDE_BIN`),
  `MAXXING_SPAWN=direct`, `MAXXING_CRONTAB_FILE` and mocks for Telegram and GitHub (`MAXXING_TELEGRAM_API`,
  `MAXXING_GITHUB_API`). Never point a test at your real crontab, a real Telegram bot or a real install. Unset a
  `PYTHONPATH` that points at an installed copy before running the tests.
- **Web UI** (React, TypeScript, Vite, Tailwind, Node 22 or newer):
  ```bash
  cd web && npm ci && npm run typecheck && npm run build
  ```
- **PC agent** (Go), only if you touched `pc-agent/`:
  ```bash
  cd pc-agent && go test ./...
  ```
- A dev server: `MAXXING_STATE=/tmp/hm-dev uv run maxxing serve --port 8801` (each contributor its own port
  8801-8809 and its own state folder).

### The `web/dist` rule

The built UI, `web/dist`, **is committed**: servers install and update without Node. So when your change touches
`web/` (sources, i18n, styles), run `npm run build` in `web/` and commit the resulting `web/dist` in the same pull
request. When it does not touch `web/`, do not commit a rebuilt `web/dist`.

## 4. Write the change

- Code, comments and docs are in **English**; the UI texts exist in English and French (`web/src/i18n/en.ts`,
  `fr.ts`): add both.
- Stay product-neutral: no personal data, names, domains, tokens or server paths. Examples use `ui.example.com`,
  `acme`, `blog`.
- State writes are atomic (`config.write_json`); never block the event loop (`asyncio.to_thread`).
- Add or update tests for what you change. A bug fix comes with a test that fails without it.
- Update the user docs page (`docs/user/`) of every visible change.

## 5. Changelogs

Every change updates **both** changelogs, under the top section (`## Unreleased` when there is one; maintainers
set the version at release time):

- `CHANGELOG.md` is **public**: shown in the app ("What's new") and by `maxxing update`. Write for users: what
  changes for them, in plain language, no internals. One bullet, a bold first sentence, then one or two short
  sentences. Example:
  `- **Voice messages sent after a quiet minute are always transcribed.** One sent at that exact moment could wait forever.`
- `docs/dev/CHANGES.md` is for maintainers: API, data formats, migrations, internals, tests added.

## 6. Open the pull request

1. Run the checks of step 3 for the parts you touched; they must pass.
2. Push your branch and open a pull request to `main`. Fill in the template (tests, changelogs, `web/dist`, CLA).
3. **Sign the CLA**: on your first pull request the CLA bot asks you to post this comment once, exactly and alone:
   `I have read the CLA Document and I hereby sign the CLA`. Contributing for a company? Sign it on behalf of that
   entity (see [CLA.md](CLA.md)). The pull request cannot be merged before (its **CLA** check stays red).
4. CI (`.github/workflows/ci.yml`) runs the server tests, the web typecheck and build, and the pc-agent tests;
   every check must be green.

## 7. Review

A maintainer, **FEU** or **Romain**, reviews the pull request. Expect questions and change requests; push new
commits to the same branch. A maintainer merges once it is approved and green. A large pull request may be
adapted at integration (version numbers, `web/dist` rebuilt) - your authorship is kept.

## What gets refused

- a feature without a prior issue agreed by a maintainer, or that does not fit the product (see the non-goals in
  [docs/dev/PLAN.md](docs/dev/PLAN.md));
- changes without tests, failing CI, or without changelog entries;
- a `web/dist` that does not match the sources (or a rebuilt `web/dist` with no web change);
- personal data, secrets, real domains or server paths in code, docs or tests;
- tests that touch the real system (crontab, Telegram, a real install);
- code you do not have the right to submit, or under a license incompatible with the [CLA](CLA.md);
- changes that weaken security defaults (binding to a public interface, disabling checks of downloads or
  signatures) without a strong reason agreed in an issue;
- pull requests without a signed CLA.

By contributing you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
