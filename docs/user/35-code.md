---
section: Using Harness Maxxing
---
# Code in a session

There is no "code mode": when Claude changes files of a **git repository** during a session, the tools to review,
commit and push those changes appear by themselves. A session that never touches a repository looks as before.

## The changes of an answer

Under an answer whose turn changed a repository, next to the model and the cost, a button sums it up:
**app · 3 files · +12 −4** (or **2 repositories · 5 files · …** when Claude worked in several). Click it: the file
viewer opens on the **Changes** of that turn.

- One block per repository: its name, its **branch** (with ↑ commits to push and ↓ commits behind), the
  **pull request** of the branch on GitHub with its checks (✓ passed, ● running, ! failed), then the changed files
  with their status (**A** added, **M** modified, **D** deleted, **R** renamed) and their +/− lines.
- **Which changes** (top right): **This turn**, **Whole session** (since Claude first touched the repository in this
  session), **Not committed** (everything since the last commit, whoever made it) or **Whole branch** (since the
  branch left `main`).
- Click a file for its **diff**: line numbers on both sides, ← / → to the previous / next file, ↑ back to the list.
  Very long diffs show their first 2,000 lines (**Show all** for the rest); binary files show no diff.
- **Ask Claude**: click a line number (Shift+click for several), then **Ask Claude**: the lines, with the file and
  their numbers, go into your next message as a quote.

How it knows: before and after each turn Harness takes a silent snapshot of each repository the session works in
(a hidden git ref, `refs/maxxing/…`, never pushed). Your files, your index and your branch are never touched by it.
Ignored files (`.gitignore`) are not part of it. Snapshots are cleaned up after 30 days. A repository Claude touches
for the first time during a turn has no "before" snapshot: that turn is compared with the last commit (the view says
so).

## Undo

- **Undo this file** (in its diff, or on hover in the list) puts the file back as it was before the changes shown,
  **Undo all** (the ↶ of a repository) does it for every file of the list.
- No confirmation: a bar **Undone · Restore** stays 10 seconds to put everything back.

## Revert to before a message

Right click (long press on a phone) one of your messages whose turn changed a repository: **Revert to before this
message** puts every repository Claude changed since that message back as it was just before it. Only files go back:
commits made since stay (the notice says so). **Restore** (10 seconds) undoes it. Not possible while a turn is
running: wait for its end or stop it.

## Commit, push, pull request

At the bottom of each repository block:

- **Commit**: type a message, or leave it empty and click **Commit…**: Claude proposes one (from the diff and the
  style of the last commits, never with an AI credit), you read it and click **Commit** again. ✨ proposes a message
  at any time. **Ctrl/⌘+Enter** commits. The ▾ menu: **Commit and push**, **Commit, push and open a pull request**,
  **New branch**.
- **Push** sends the branch (the first push of a branch sets its upstream on `origin`).
- **Open a pull request** (GitHub only): pushes first if needed, then opens it against the default branch, titled
  after the commits; it then shows as the repository's badge with its checks.
- Your repository's hooks run as usual (a `commit-msg` or `pre-push` hook can refuse). Push and pull requests use
  the repository's own credentials, else a GitHub token of **Settings → Keys** that can write.

Claude never commits or pushes through these buttons: they only run when you click them.

## Terminal

**Settings → Features → Terminal** (off by default; your password is asked to turn it on, because a terminal runs any
command on the server). Then:

- **Ctrl+J** in a session, **/terminal** in the composer or **Open a terminal** in the session's options opens a
  drawer under the conversation: a terminal in the session's repository (or its topic folder).
- **+** opens another one, in any repository of the session; one tab per terminal; drag the top edge to resize.
- Select text, then **Send the selection to Claude**: it goes into your next message as a quote.
- A page reload finds the terminals again with what they printed. They close when you close them, after 30 minutes
  without activity, or when the Harness service restarts. 4 at most at a time.
- On a phone the drawer takes most of the screen, with a row of keys a phone keyboard lacks (Esc, Tab, Ctrl+C,
  arrows).
- Agents never get a terminal.

`maxxing doctor` also lists programs started by hand (`systemd-run`) that have been running for more than a week:
forgotten test servers or previews that keep memory and ports.
