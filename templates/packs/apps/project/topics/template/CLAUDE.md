# Topic template

The shared starter all apps copy from: "set up the starter with Next.js and Postgres", "add a test
command to the template", "start a new app from the template".

@memory.md

## Your role

- Keep a working starter in `starter/` (this topic folder, its own git repo): stack, folder layout,
  lint, format, tests, env vars example, README, deploy files.
- Keep the conventions in `memory.md` short and true; every app topic reads them.
- When the user says "new app": take the next app slot (`app-1`, `app-2`, `app-3`) whose memory has no
  name yet, copy `starter/` into `../<slot>/repo/` (without `.git`), `git init`, first commit, then fill
  the slot's `memory.md` with the user. If all slots are used, say so and offer to create a new topic.
- When the starter improves, note it in `Decisions`; offer to port the change to existing apps, never
  do it silently.

## First session

- If this topic's `memory.md` still has empty fields, ask their questions one short batch at a time,
  write the answers into `memory.md`.
- Then propose 2-3 first actions, e.g. "create the starter with your stack and a hello page", "add lint,
  tests and a single `make check`", "write the README every app will start with".

## Playbook

- Pick boring, well-documented tools the builder already knows; one language end to end when possible.
- Layout: `README.md` (what, how to run, how to deploy), `.env.example` (every variable, no values),
  `src/`, `tests/`, one command each for dev, test, lint, build (`make dev|test|lint|build` or npm scripts).
- Config only through environment variables; the app refuses to start when a required one is missing,
  with a clear message.
- Tests: a smoke test that boots the app and hits the health route, plus unit tests for business logic;
  `make check` = lint + tests, must pass before every commit.
- Health route `/health` returning 200 and the version; the hosting topic monitors it.
- Logs to stdout, one line per event, no secrets or personal data in logs.
- Database: migrations in the repo, never edit the schema by hand in production; seed script for dev.
- Auth, payments, email: use a proven library or provider, never hand-rolled crypto.
- Pin versions (lock file committed); `.gitignore` covers `.env`, build output, dependencies.
- Dockerfile or systemd unit example kept in `deploy/`, matching the hosting topic's default.
- Node.js 22, Python 3, git, jq and ripgrep are installed on this server; check `node -v` / `python3 -V`.
- Common mistakes: secrets in the repo, a template that does not run from a fresh clone, apps that drift
  from the template without a note in their memory.

## Connect

- Git host token (e.g. `GITHUB_TOKEN`) to create private repos and push; stored in Settings -> Keys
  and exposed to sessions as an environment variable. Never ask the user to paste a secret in the chat.

## Automations

- None by default. A monthly "dependency check" (outdated or vulnerable packages in the starter and
  each app, report only) can be created with the `maxxing-cron` skill if the user asks.
