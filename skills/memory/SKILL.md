---
name: memory
description: Update the right memory.md at the end of a significant exchange. Use whenever a durable fact appeared - a decision, a preference or rule from the user, a change in the state of a project or topic, a reusable fact (path, URL, command, convention). Skip it for one-off questions and chit-chat.
---

# Memory

The workspace has three memory levels. Each `CLAUDE.md` imports its `memory.md` (`@memory.md`), so
whatever you write here is loaded automatically in the next session of that topic.

## When
At the end of an exchange that produced something worth knowing next time:
- a decision or a chosen direction;
- a preference or rule stated by the user ("always…", "never…", "from now on…");
- progress that changes the state of the work (done, blocked, next step);
- a reusable fact: path, URL, command, account name, convention, gotcha.

Nothing durable (a quick question, reading a file, a failed attempt with no lesson) -> write nothing.

## Where (pick the narrowest level that is true)
1. **Topic** - `<workspace>/projects/<project>/topics/<topic>/memory.md`: the current mission. Most
   common; the session's working directory tells you the topic.
2. **Project** - `<workspace>/projects/<project>/memory.md`: true for every topic of the project.
3. **Global** - `<workspace>/memory.md`: rules and preferences valid everywhere. Rare.

The workspace root is printed by `maxxing status` (here `{{WORKSPACE}}`).

## How
- Short factual bullets in the matching section; add a date when it helps: `- 2026-03-02: …`.
- **Replace** a fact that became wrong; never keep two contradictory versions.
- Merge with an existing bullet rather than adding a near-duplicate.
- No conversation logs, no step-by-step narratives: only what is reusable.
- **Never write secrets** (tokens, passwords, API keys). Store them in Settings -> Keys and write
  only the key *name* in memory ("GitHub token: key `GITHUB_TOKEN`").
- Instructions that should always apply (how to work on this project) belong to `CLAUDE.md`, not
  `memory.md`. Edit `CLAUDE.md` only when the user asks for a lasting instruction; keep its first
  paragraph (the description shown in the UI) intact.
- Keep the edit small; tell the user in one line what you recorded ("Noted in topic memory: …").
