---
section: Extending
---
# Customizing Harness Maxxing

Your server, your product: you can change anything, and updates keep your changes. Just ask
Claude ("put a snake game on my dashboard", "allow 20 sessions per topic") - it picks the right
level below, records what it did and carries it over every update.

Many changes need no code at all: **Settings -> Appearance** (colours, layout, fonts), **Settings -> Features**
(which pages show, their order in the sidebar), the dashboard's **Edit layout**. Claude points to them first.

## Three levels

| Level | For | Where | On update |
|---|---|---|---|
| **Extensions** | widgets (Card or free HTML: games, canvas), pages, their API | `<workspace>/extensions/` | never touched |
| **Workspace** | how Claude behaves in a topic, scheduled jobs, your own skills | `CLAUDE.md` files, Settings -> Crons, `.claude/skills/` | never touched |
| **Customizations** | changing the product itself (a server rule, a limit, a CLI command, the interface…) | the code directory, recorded with `maxxing custom save` | replayed on top of the new version |

Claude always tries the first two before touching the product code. See [Dashboard widgets](dashboard-widgets) and
[Page extensions](page-extensions).

## Changing the interface

The interface can be customized too: ask Claude ("make the sidebar wider", "add a button that opens my shop").
It edits the interface's sources (`web/src` in the code directory), builds your own copy of the interface on the
server (`maxxing custom build`, about 30 seconds) and records the change like any customization. The interface that
comes with Harness Maxxing (`web/dist`) is never modified: your build lives in the state directory
(`/var/lib/claude-maxxing/web-dist`) and stays shown while Claude edits the sources again, until a new build
replaces it (a build that fails changes nothing). After an update or once you drop the change, the standard
interface is shown until your interface is built again.

- The first build installs the build tools (about 450 MB, once per version).
- Every update rebuilds your interface on the new version; Settings -> Updates says beforehand whether it still
  builds. If it no longer does, the update still happens and the standard interface is shown until Claude adapts
  your change (`maxxing doctor` says so too).
- Small changes in their own files keep well across updates; Claude works that way.
- Edits made before this was possible (set aside by an older update, or made in `web/dist`): `maxxing custom`
  lists them as "Old UI edits"; Claude can redo them properly with your OK.

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

**Before**: Settings -> Updates shows what the next update does to *your* server - tested on a throw-away
copy, nothing changed yet (`maxxing update --preflight` on the server). Each customization **carries
over**, carries over on code that changed (checked after), is **now included** in the product (Harness
offers to drop it), or **must be adapted**. Whether your customized interface still builds, unsaved edits, edits of
the shipped interface build (`web/dist`) and extensions the new version no longer supports are listed too.

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

`maxxing update` (or the topic `system/harness` (`system/update` on older servers), or Settings -> Updates) keeps you safe:

1. Unsaved edits of the code are saved as a customization first - nothing is ever lost. Edits of the
   shipped interface build (`web/dist`) cannot be customizations: they are set aside (`git stash`) instead of
   blocking the update, and Harness redoes them in the interface's sources.
2. Your customizations are replayed on top of the new version.
3. **No conflict**: the update finishes ("N customizations carried over").
4. **Conflict** (the new version changed the same lines): **nothing changes**, the current version
   keeps running, and Settings -> Updates shows "Update waits for Harness". In the topic
   `system/harness` (`system/update` on older servers), Claude reads `CUSTOMIZATIONS.md`, adapts each customization to the new code,
   and finishes the update (`maxxing update --resume`). If a customization is no longer needed
   (the product now does it), Claude tells you and drops it.
5. **The new version does not start**: it is rolled back automatically to the previous one (and to the previous
   branch after `--branch`).

`maxxing update --rollback` returns to the version (and the branch) that ran before the last update. It refuses to run while the code
directory has unsaved changes (nothing is changed): put them aside first (`git stash`), run the rollback, then put
them back (`git stash pop`). Customizations saved since the update are kept (replayed on the previous version); if
one does not fit the previous version, nothing changes and the rollback says which.

Switching branch (`--branch beta`, then back) carries the customizations that run now, never an older copy left on
the other branch: one dropped or changed meanwhile does not come back, one already included in the new branch is
simply dropped. An update cut off midway (reboot, out of memory) is finished by the next `maxxing update`, which
keeps the version to roll back to and the upgrade notes of the release.

## Automatic updates

Off by default. Settings -> Updates -> **Update by itself when nobody is here**: when a new version is out, nobody
is on the interface and nothing runs (no turn, no queued message, no scheduled job, nothing for 10 minutes), and
the update is "simple" (no customization to adapt, no unsaved change, no upgrade note asking for something),
Harness runs `maxxing update` by itself and restarts for a few seconds. Otherwise it waits and tells you in the
notifications. It never touches a server whose code is on a branch under test (detached HEAD) or an update that
already waits for you (conflict, rolled-back version), and tries a given version at most once a day.

## New server

Restore your memory backup on the new server (`RESTORE_FROM=owner/name` at install): the installer
re-applies your customizations. Otherwise run `maxxing custom restore`.

See also: `maxxing custom --help` and the skill `maxxing-customize` (what Claude follows).
