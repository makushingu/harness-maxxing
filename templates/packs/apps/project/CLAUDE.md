# Project apps

Your apps, side by side, built from one shared starter: "start a new app for booking appointments",
"fix the login bug in app-2", "is everything up?".

## Topics

- `template`: the shared starter every app copies from (stack, folder layout, lint/test, env vars).
- `hosting`: servers, domains, DNS, TLS, deploys, backups and monitoring for all apps.
- `app-1`, `app-2`, `app-3`: one app each: its repo, roadmap, bugs and releases. Empty until used.

## Shared conventions

- Shared facts (who builds, languages, default stack, git host, budget) live in this project's
  `memory.md`. Read it before any work; fill it in during the first session of any topic.
- Each app keeps its own facts (name, repo, stack, URL, roadmap) in its topic `memory.md`; hosting facts
  for all apps live in `hosting/memory.md`.
- "New app" = take the next app slot whose memory has no name yet, copy the starter from
  `template/starter/` into its `repo/` folder, rename the topic in the Sessions page if the user wants.
- Code lives in git; commit small, with clear messages, after tests pass. Never force-push, never
  rewrite a shared branch, never commit `.env` files or secrets.
- Keys and tokens are stored in Settings -> Keys and reach sessions as environment variables. Never
  ask the user to paste a secret in the chat, never write one into a file.
- Never deploy to production, change DNS, delete data or spend money without an explicit "yes" from the
  user in the current conversation.
- Follow-ups go to the task board (`maxxing-tasks` skill); alerts go to the feed (`maxxing-feed` skill,
  e.g. `maxxing feed post "Deploy failed" --level error --source app-1`).

@memory.md
