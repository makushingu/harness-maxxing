---
section: Extending
---
# Customizing Harness Maxxing

Your server, your product: you can change anything, and updates keep your changes. Just ask
Claude ("put a snake game on my dashboard", "allow 20 sessions per topic") - it picks the right
level below, records what it did and carries it over every update.

## Three levels

| Level | For | Where | On update |
|---|---|---|---|
| **Extensions** | widgets (Card or free HTML: games, canvas), pages, their API | `<workspace>/extensions/` | never touched |
| **Workspace** | how Claude behaves in a topic, scheduled jobs, your own skills | `CLAUDE.md` files, Crons page, `.claude/skills/` | never touched |
| **Customizations** | changing the product itself (a server rule, a limit, a CLI command…) | the code directory, recorded with `maxxing custom save` | replayed on top of the new version |

Claude always tries the first two before touching the product code. The web interface itself
cannot be customized (it is shipped pre-built): visual additions are extensions. See
[Dashboard widgets](dashboard-widgets) and [Page extensions](page-extensions).

## Customizations

A customization is a change to the code directory (`/opt/claude-maxxing`) saved as a git commit
with a title and the reason:

```bash
maxxing custom save "Allow 20 sessions per topic" --why "I run many research threads in parallel"
maxxing custom                 # list, unsaved changes, pending update
maxxing custom drop <id>       # remove one
```

Every customization is listed in **`<workspace>/CUSTOMIZATIONS.md`** (title, reason, files) and
exported as a patch in `<workspace>/customizations/`. Both are part of the memory backup.

## Smart updates

**Before**: Settings -> System shows what the next update does to *your* server - tested on a throw-away
copy, nothing changed yet (`maxxing update --preflight` on the server). Each customization **carries
over**, carries over on code that changed (checked after), is **now included** in the product (Harness
offers to drop it), or **must be adapted**. Unsaved edits, edits of the interface files and extensions the
new version no longer supports are listed too.

- Everything compatible: **Update** does it all. After the restart, your extensions and customizations
  are checked automatically, and Harness applies the version's workspace novelties in a session of
  `system/harness`.
- Something to adapt: **Update with Harness** opens a session that adapts each change to the new code
  from what it is *for* (recorded with it), tests, then updates. The current version keeps running until
  everything works.

**After**: "Checked after the update: your extensions and changes work" - or what stopped working, with
**Fix with Harness**. Check any time with `maxxing update --verify` (or "Check now").

Give each customization a check - a command that succeeds while it works - and it is tested after every
update: `maxxing custom save "..." --why "..." --check "<command>"`, or later `maxxing custom check <id>
"<command>"`. Extensions declare the version of the extension contract they use (`"api": 1` in
`manifest.json`): a version that stops supporting it is announced before you update.

## Careful updates

`maxxing update` (or the topic `system/harness` (`system/update` on older servers), or Settings -> System) keeps you safe:

1. Unsaved edits of the code are saved as a customization first - nothing is ever lost. Edits of the
   pre-built interface (`web/`) cannot be customizations: they are set aside (`git stash`) instead of
   blocking the update, and Harness rebuilds what they did as an extension.
2. Your customizations are replayed on top of the new version.
3. **No conflict**: the update finishes ("N customizations carried over").
4. **Conflict** (the new version changed the same lines): **nothing changes**, the current version
   keeps running, and Settings -> System shows "Update waits for Harness". In the topic
   `system/harness` (`system/update` on older servers), Claude reads `CUSTOMIZATIONS.md`, adapts each customization to the new code,
   and finishes the update (`maxxing update --resume`). If a customization is no longer needed
   (the product now does it), Claude tells you and drops it.
5. **The new version does not start**: it is rolled back automatically to the previous one (and to the previous
   branch after `--branch`).

`maxxing update --rollback` returns to the version (and the branch) that ran before the last update. It refuses to run while the code
directory has unsaved changes (nothing is changed): put them aside first (`git stash`), run the rollback, then put
them back (`git stash pop`). A customization saved just before would be undone by the rollback.

## Automatic updates

Off by default. Settings -> System -> **Update by itself when nobody is here**: when a new version is out, nobody
is on the interface and nothing runs (no turn, no queued message, no scheduled job, nothing for 10 minutes), and
the update is "simple" (no customization to adapt, no unsaved change, no upgrade note asking for something),
Harness runs `maxxing update` by itself and restarts for a few seconds. Otherwise it waits and tells you in the
notifications. It never touches a server whose code is on a branch under test (detached HEAD) or an update that
already waits for you (conflict, rolled-back version), and tries a given version at most once a day.

## New server

Restore your memory backup on the new server (`RESTORE_FROM=owner/name` at install): the installer
re-applies your customizations. Otherwise run `maxxing custom restore`.

See also: `maxxing custom --help` and the skill `maxxing-customize` (what Claude follows).
