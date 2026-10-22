# Workspace upgrade notes (for maintainers)

`maxxing update` replaces the product code, dependencies and skills, and `maxxing init` adds the
**missing** template files of the workspace - but it never edits a file the user already has
(their `CLAUDE.md`, `memory.md`, projects...). When a release needs the user's workspace to change
(a new section in the root `CLAUDE.md`, a renamed topic, a setting to adjust), write it here as
instructions **for Claude**. The topic `system/update` applies them after an update, with the
user in the loop.

## One file per release

`docs/upgrade/<version>.md`, the version exactly as in `server/maxxing/__init__.py`
(`2.0.0a2.md`, `2.0.0.md`, `2.1.0rc1.md`). Only releases that need workspace changes have a file.
Claude applies, in version order, every file with *last applied* < version <= *installed*
("last applied" is recorded in `<workspace>/projects/system/topics/update/memory.md`; the first
value is the version installed initially). `maxxing update` also prints the list of notes between
the old and the new version.

## Format

```markdown
# Upgrade notes 2.1.0

Summary: one line the user will read ("adds the topic system/backups").

## 1. <short title>
- Check: how to tell whether it is already done (the notes must be idempotent).
- Do: the change, as precise as possible (paths relative to the workspace, exact text to add).
- Ask first if: the change touches user content (rename, delete, rewrite) - say what and why.

## 2. ...
```

Rules:
- Written to Claude, in English, imperative. Paths relative to the workspace; product files as
  `<CODE>/...` (Claude knows the code directory from the `system` project CLAUDE.md).
- **Idempotent**: every step starts with a check; applying a note twice changes nothing.
- **Never destructive without asking**: no deletion, overwrite or rename of user content without an
  explicit yes; prefer adding to replacing; move to `.trash`-like folders rather than deleting.
- Tolerate a customised workspace: if the user renamed or deleted something on purpose (e.g. the
  `tutorial` project), do not re-create it - mention it in the report instead.
- Keep each note short (a few steps); everything else belongs in `CHANGELOG.md`.
