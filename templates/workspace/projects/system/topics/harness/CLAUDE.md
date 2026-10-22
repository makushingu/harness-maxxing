# Topic harness

Harness Maxxing itself: say "update" (or "is there a new version?"), "make a widget showing my
site's visitors" or "add the freelance pack". Claude updates the product after your confirmation
and adapts your workspace to the new version, builds your own dashboard widgets, pages and
extensions, and installs starter packs.

@memory.md

## Updates (follow this procedure in order)

1. **Check** - run `maxxing update --check`, then `maxxing update --preflight`: the update simulated on
   a throw-away copy of the code - each customization carries over, needs adapting (conflict), or is now
   included in the product; unsaved edits, edits of the web UI and extensions the new version no longer
   supports are listed too. Neither command changes anything. Exit code 0 = check done (an update
   may or may not be available), non-zero = the check itself failed (show the error, suggest
   `maxxing doctor`, stop).
2. **Explain** - if an update is available, summarise the changelog in plain language for a
   non-developer: what is new, what changes for them, anything they must do. Mention that running
   conversations are not interrupted but the web page reloads after the restart. If the check
   lists customizations ("will be carried over"), say they are kept, and whether the changelog
   touches the same area (`{{WORKSPACE}}/CUSTOMIZATIONS.md` says what each one does).
3. **Ask for confirmation** - never update without an explicit yes.
4. **Update** - run `maxxing update` (code, dependencies, skills, workspace templates, service
   restart + health check). The restart cuts this page's connection for a few seconds; the
   command itself keeps running. Exit codes:
   - `0` done (customizations, if any, carried over - check they still work);
   - `3` **customizations conflict** with the new version: nothing changed, the current version
     keeps running. Adapt them with the skill `maxxing-customize` (section "During an update"),
     then `maxxing update --resume`. Explain to the user what you adapted;
   - `4` **rolled back**: the new version did not start, the previous one was restored. Read the
     service log, fix (skill `maxxing-customize` if a customization is the cause, otherwise
     `maxxing-doctor`) and try again;
   - `1` other failure: report the last lines, suggest `maxxing doctor`, do not retry blindly.
   `maxxing update --rollback` goes back to the code that ran before the last update.
5. **Apply the workspace upgrade notes** - the folder `{{CODE_DIR}}/docs/upgrade/` holds one file
   per version, `<version>.md` (e.g. `2.0.0a3.md`): instructions written for you about what to
   create, rename or adjust in the user's workspace. Apply, in version order, every file whose
   version is greater than "Last applied upgrade notes" below (in memory.md) and lower than or equal
   to the installed version (`maxxing status`). The notes are idempotent: check before changing.
   Never delete or overwrite user content without asking first.
6. **Verify** - `maxxing update --verify`: every extension loads, every widget answers, every
   customization's check passes. Fix what fails (skills `maxxing-extension` / `maxxing-customize`).
7. **Record** - update "Last applied upgrade notes" in this topic's memory.md to the installed
   version, with the date and one line per note applied. Then give a short report.

The Update button (Settings -> System) runs the same preflight first. When it is simple it updates by
itself, then the server verifies and opens a session here to apply the upgrade notes (steps 5-7). When
something must be adapted, "Update with Harness" opens a session here with the preflight and the steps: adapt
each customization to its INTENT on the new code, never just pick a side.

If the user says "update" and no new version exists, still check that every upgrade note up to
the installed version was applied (step 5), then say they are up to date. Also run
`maxxing custom status`: a pending update or unsaved changes in the code directory are handled
with the skill `maxxing-customize`.

Telegram: a weekly job "Check for updates" (`maxxing update --check --notify`, Mondays 09:00)
sends a message when a new version exists - it only checks, it never updates.

## Widgets, pages and extensions

"Make a widget showing my site's visitors", "a mini snake game on my dashboard", "a page to manage
my reading list": you write the extension and the user sees it in the UI. Extensions survive every
update: nothing to ask the product's authors.
- Use the `maxxing-extension` skill: it knows the format (manifest, `api.py` card or handler,
  `page.js`), the Card blocks and the pitfalls. Reference docs:
  `{{CODE_DIR}}/docs/user/12-dashboard-widgets.md` and `{{CODE_DIR}}/docs/user/13-page-extensions.md`;
  working examples: `{{CODE_DIR}}/examples/extensions/` (`hello-widget`, `snake-widget`, `notes-page`).
- Extensions live in `{{WORKSPACE}}/extensions/<id>/` (outside the product code: updates never
  touch them, the memory backup includes them). Kinds: Card widget (`api.py` card), **HTML widget**
  (`widget.html`: games, canvas, anything free-form), page (`page.js`). Example of each in
  `{{CODE_DIR}}/examples/extensions/`.
- Never answer "this needs the authors" or "it would be erased by the next update": an extension
  can do it, or, for a change of the product itself, follow the `maxxing-customize` skill
  (customizations are recorded and carried over by updates). Never edit `{{CODE_DIR}}` otherwise.
- Clarify what the user wants to see (data source, refresh rate, size) in one or two questions,
  then build the smallest version that works, test it (`curl` the widget/API through
  `maxxing status` URL or call `api.py` directly with Python), and tell the user where to look
  (Dashboard, or the page in the sidebar). Reload: Settings -> Extensions -> Reload (automatic on
  file change).
- Secrets the extension needs (API keys) go to Settings -> Keys and are read with `ctx.secret(name)`,
  never hard-coded.
- List the extensions you built and what they do in memory.md.

## Starter packs

Ready-made projects with their topics, instructions and memory: `ecommerce`, `affiliate`,
`creator`, `apps`, `second-brain`, `freelance` (also in Settings -> Starter pack).
- "Add the e-commerce pack": run `maxxing packs list` (ids and what each one contains), then
  `maxxing packs add <id>` with the matching id. If the request is vague, show the list and ask.
- Adding a pack always creates a new project (`ecommerce-2` when `ecommerce` exists); nothing is
  overwritten. Say which project was created and which topic to open first; note it in memory.md.
- "Put back the default projects / the tutorial": `maxxing packs add basics` (re-creates the missing
  default projects and topics, never overwrites).
