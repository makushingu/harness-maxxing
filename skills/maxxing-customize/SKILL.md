---
name: maxxing-customize
description: Customize Harness Maxxing itself and keep the change through updates. Use when the user wants the product to behave differently (a server rule, a limit, a CLI command, a default, a Telegram message format...) and no extension can do it; when `maxxing update` reports that customizations conflict (exit code 3) or rolled back (exit code 4); when doctor shows unsaved changes in the code directory; when restoring customizations on a new server; or to list, explain or remove customizations.
---

# Customizations of the product code

The user owns this server and may change anything - including Harness Maxxing itself. Never answer
"ask the authors" or "it would be erased by the next update". Changes are recorded as
**customizations**: local git commits in the code directory, listed in `<workspace>/CUSTOMIZATIONS.md`
and carried over by every `maxxing update`.

Paths: code directory = `maxxing status` -> Code (here `{{CODE_DIR}}`), workspace =
`maxxing status` -> Workspace (here `{{WORKSPACE}}`).

## 0. Extension first
| The user wants... | Do |
|---|---|
| a widget, a mini-game, a canvas, a page, an integration shown in the UI | an **extension** (skill `maxxing-extension`): survives updates with nothing to adapt |
| a new scheduled job, task, memory rule, topic behaviour | crons / tasks / the topic's `CLAUDE.md` - not the code |
| the interface to look or work differently, and no setting does it (Settings -> Appearance, Features) | a **customization of the web UI** (section 1b) |
| the product to behave differently and nothing above can do it | a **customization** (this skill) |

## 1. Make a customization
1. Read the relevant code first (`<code>/server/maxxing/...`, `docs/dev/INTERNALS.md` explains the
   modules). Make the **smallest** change that does what the user asked; one customization = one
   purpose. Never put secrets in code (Settings -> Keys).
2. Check it: `cd <code>/server && .venv/bin/python -m compileall -q maxxing` (syntax), then restart
   (say so first, the page reconnects in seconds): `systemctl restart claude-maxxing`, and verify
   `maxxing doctor` + the behaviour itself.
3. Record it - mandatory, right away:
   ```bash
   maxxing custom save "Short title of what it does" --why "why the user wanted it (their words)" \
     --check "a shell command that exits 0 while it works"
   ```
   The `--why` is what lets a future Claude adapt it to a new version: write the intent, not the diff.
   Without `--files` every unsaved change goes in: with changes for different purposes pending, save each
   with `--files`. A fix of an existing customization: save it with the same title plus "(fix)" and a `--why`
   that says what it adapts.
   The `--check` is run after every update (`maxxing update --verify`, from the workspace, `$MAXXING_CODE` =
   code directory): e.g. `grep -q 'LIMIT = 50' $MAXXING_CODE/server/maxxing/rules.py`, or a `curl -fsS` of the
   endpoint it adds. Add or change it later with `maxxing custom check <id> "<command>"`.
4. Tell the user it is recorded and will be kept by updates; note it in this topic's memory.md.

## 1b. Change the interface (web UI)
The UI is React + TypeScript under `<code>/web/src` (`docs/dev/DESIGN.md` = its rules). This server builds
its own copy into the state directory; the shipped build `<code>/web/dist` is **never** edited (`custom save`
refuses it, an update sets such edits aside).
1. Ask what the user wants to see, then read the page or component first (`web/src/pages/`, `web/src/features/`,
   shared parts in `web/src/components/`). Make the **smallest** change; prefer a new file (a component, a hook)
   plus a one-line hook into the existing code over rewriting a big file - the less of our code you touch, the
   less an update has to adapt. Every visible text goes in **both** `web/src/i18n/en.ts` and `fr.ts`.
   Never run prettier or reformat a file. Ask before adding an npm dependency.
2. Build and look: `maxxing custom build` (typecheck + build, ~30 s, the first time also installs the build
   tools - about 450 MB in `<code>/web/node_modules`). It is served at once (no restart): ask the user to reload
   the page. A type error = fix it, never silence it. Phone layout too (`max-md:` classes = touch screens).
3. Record it like any customization: `maxxing custom save "..." --why "..." --files <its files>` (the sources
   only; `--files` whenever other unsaved changes exist, so each purpose stays its own customization), with a
   `--check` such as `grep -q '<a unique string of the change>' $MAXXING_CODE/web/src/<file>`.
4. Undo: `maxxing custom drop <id>` then `maxxing custom build` (or the standard interface is shown).
After each update the server rebuilds it on the new version. If it no longer builds, the update still
succeeds and the standard interface is shown: adapt the sources to the new code (same rule as a conflict,
section 2: keep the new code, re-implement the intent), `maxxing custom build`, then `maxxing custom save`
the fix.

### Interface edits from before
`maxxing custom` shows "Old UI edits" when an older update set web edits aside (git stashes named
"edits of the web UI") or a local commit changed `web/dist`. With the user's OK: read them
(`git -C <code> stash show -p <ref>`, `git -C <code> show <commit>`), redo each wanted change in `web/src`
on the current code (the build files only tell what changed, never copy them), `maxxing custom build`, check
with the user, `maxxing custom save`, then remove what is no longer needed (`git -C <code> stash drop <ref>`;
a commit with `maxxing custom drop <id>`). Ask before dropping anything.

`maxxing custom` (status) lists customizations, unsaved changes, the state of the web UI and any pending update.
`maxxing custom drop <id>` removes one (ask first; restart afterwards).

## 2. During an update (topic system/harness, or system/update on older servers)
First `maxxing update --preflight` (changes nothing): per customization `carries over`, `carries over, on
code that changed` (verify it after), `now included` (check the new version really does it, then `maxxing
custom drop <id>`), `conflicts` (adapt it, below), and whether the customized web UI still builds. Edits of
the shipped build `web/dist` are set aside (`git -C <code> stash list`): redo them in `web/src` (section 1b).
Then `maxxing update`
replays the customizations on top of the new version:
- **exit 0** - carried over ("N customization(s) carried over"). Check each still works.
- **exit 3 - conflict**: nothing changed, the old version keeps running. Adapt them:
  ```bash
  cat <workspace>/CUSTOMIZATIONS.md                     # intent of each customization
  maxxing custom status                                 # conflicting files
  cd <code> && git rebase origin/main                   # stops on the first conflict
  git status ; git diff                                 # see both sides
  ```
  For each conflicted file: rewrite it so the **new version's code** is kept and the customization
  still does what its `why` says (the upstream code may have moved, been renamed or now does it
  natively - then the customization can be dropped: `git rebase --skip`, after telling the user).
  Remove every conflict marker (`grep -n '<<<<<<<\|>>>>>>>' <file>` must print nothing), then
  `git add <file>` and `GIT_EDITOR=true git rebase --continue` (no terminal: keep the message as
  is); repeat until the rebase ends. Check syntax (`compileall` above), then finish with:
  ```bash
  maxxing update --resume        # deps, skills, restart, health check, records CUSTOMIZATIONS.md
  ```
  If you cannot make it work: `git rebase --abort` (back to the running version, nothing lost),
  explain what blocks to the user, and propose dropping that customization or staying on the
  current version.
- **exit 4 - rolled back**: the new version did not start (or dependencies failed); the previous
  code was restored automatically. Read `journalctl -u claude-maxxing -n 80 --no-pager`; if a
  customization is the cause, fix it in a rebase as above or drop it, then `maxxing update` again.
- `maxxing update --rollback` returns to the code that ran before the last update.
- After any update: `maxxing update --verify` (extensions load, widgets answer, each customization's check
  passes) and fix what fails. A customization without a check: give it one.

## 3. Unsaved changes
Doctor "unsaved change(s) in the code directory" = someone edited the code without recording it.
Look (`git -C <code> diff`), ask the user what it is for, then `maxxing custom save ... --why ...`
(or discard with `git -C <code> checkout -- <file>` if they confirm it is unwanted). An update
auto-saves them as "Unsaved changes found by the update": rename by dropping and re-saving with a
real title, or just add the purpose to this topic's memory.md.

## 4. New server
The memory backup contains `CUSTOMIZATIONS.md` and `customizations/*.patch`. After a restore, the
installer re-applies them; otherwise run `maxxing custom restore`. If they do not apply to the
installed version, adapt them like a conflict (section 2) using the patch files as reference.
