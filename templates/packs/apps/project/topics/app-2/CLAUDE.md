# Topic app-2

One app slot: its code, roadmap, bugs and releases. "this slot is for a booking app for my salon",
"fix the bug where the signup email never arrives", "what is left before the 1.0 release?".

@memory.md

## Your role

- Own this one app: its repo in `repo/` (this topic folder), its roadmap, bugs and releases.
- Keep `memory.md` current: what the app is, stack, repo, where it runs, what is next.
- Follow the shared starter and conventions of the `template` topic unless this app's memory says
  otherwise; deploys and servers are documented in the `hosting` topic.

## First session

- If this topic's `memory.md` still has empty fields, ask their questions one short batch at a time,
  write the answers into `memory.md`: what the app is and for whom, which stack (default: copy from
  `template`), where the code is (existing repo to clone, or new), where it is or will be hosted.
- New app: copy `../template/starter/` into `repo/` (without `.git`), `git init`, first commit,
  push to a new private repo if a git token is set. Existing app: clone it into `repo/`.
- Then propose 2-3 first actions, e.g. "write a one-page spec and a first roadmap", "run the app
  locally and the tests", "list the open bugs".

## Playbook

- Spec first: who the user is, the 3-5 things they must be able to do, what is out of scope. Write it
  to `repo/docs/spec.md` and keep it short.
- Roadmap in `memory.md`: Now / Next / Later, small items that ship in a day or two each.
- Before changing code: read the relevant files, run the tests, reproduce the bug. After: `make check`
  (or the app's test command) must pass, then commit with a clear message.
- Bugs: steps to reproduce, expected vs actual, logs; write a failing test, then the fix.
- One change per commit, one feature per branch if the user works with pull requests.
- Releases: bump the version, write the changelog in plain words for users, tag (`vX.Y.Z`), deploy
  through the hosting runbook, check `/health` and the main user flow after.
- Data safety: never run a destructive migration or delete user data without a backup and a "yes".
- Security basics: validate input, parameterized queries, hashed passwords, rate-limit login, keep
  dependencies updated, no secrets in the repo or logs.
- When the app is down or a deploy fails, post it to the feed:
  `maxxing feed post "app-2 deploy failed" --level error --source app-2`.
- Common mistakes: building features before the core flow works, skipping tests on a "small" fix,
  deploying without a way back, drifting from the template without a note.

## Connect

- A git host token (e.g. `GITHUB_TOKEN`) to push and open pull requests; the app's own service keys
  (database URL, payment, email) for local tests, named like the app's `.env.example`.
- Keys are stored in Settings -> Keys and exposed to sessions as environment variables. Never ask the
  user to paste a secret in the chat, never write one into `.env` files that are committed.

## Automations

- Uptime is covered by the "Uptime check" job of the `hosting` topic (add this app's URL there).
- An app-specific job (e.g. nightly test run, weekly dependency report) can be created here with the
  `maxxing-cron` skill if the user asks.
