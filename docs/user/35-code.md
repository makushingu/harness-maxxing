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
  Very long diffs show their first 2,000 lines, and very long lines (a minified file) their beginning: **Show all** for
  the rest. Binary files show no diff.
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

## Pull requests in Harness

With a GitHub token (**Settings → Keys**), a pull request opens **in Harness**, in the same panel as the changes:
from the Git page (a repository, or a clone of a GitHub repository: **Open / To review / Closed**, the ones from
outside the repository are marked), or from the pull request badge of the Changes view.

- **Conversation**: the description, the comments and the reviews. **Files**: the same list and the same diff as the
  Changes view; click a line number (Shift for several) to comment on those lines: your comments wait (**pending**)
  until you send them with your review. A file's diff is shown whole; for a file too big for GitHub to send its diff,
  a link opens it on GitHub. **Checks**: what passed, failed or still runs.
- At the bottom: **Comment**, **Approve**, **Request changes**, **Merge** (squash, merge or rebase, as the repository
  allows; refused for a draft or a conflict; a warning when checks failed). ⋯ **Close the pull request**. GitHub stays
  one click away (↗).
- **With Claude** (Code mode, the repository cloned in a topic):
  - **Work on this PR**: a session on a separate copy of the pull request's branch, in the clone's topic. A pull
    request from a fork is fetched as `pr/<number>`: it cannot be pushed back.
  - **Ask Claude to review**: a session in plan mode (it changes nothing) that reads the branch and ends its answer
    with a **review card**: the summary, the line comments, a verdict you can change, and **Publish on GitHub**. Claude
    never publishes: you read it, then click.
- A pull request from **someone outside** the repository (not owner, member or collaborator) is marked, and a session
  on it starts in **plan mode**: read the code before installing it or running its tests.

Approving, merging and closing use a token of **Settings → Keys** that can write to the repository; without one these
buttons are absent.

## Separate copy (Code mode)

With **Code mode** on, a new session in a topic that holds a git repository offers **Separate copy**: the session gets
its own folder and its own branch, so two sessions on the same repository never step on each other.

- **Where**: in the topic, `worktrees/<name>` beside the clone (visible in **Files**; `.worktrees/` when the topic
  folder is itself the repository, so that its tests and tools do not walk into it). Claude works there and still
  reads the topic's `CLAUDE.md` and memory. The search and the memory backup skip these folders.
- **Branch**: `session/<title>`, started from the default branch (or the one you pick). It follows the session's title
  until it is pushed. The prefix can be changed per repository.
- **Prepare the copy**: a copy has no `node_modules` or `.venv` (they are not in git). Give a command (`npm ci`,
  `uv sync`…) run once in each new copy, and tick **Copy the .env files** if the project needs them; both are kept for
  the repository. A failed preparation shows in the bar: one click asks Claude to look at its log. Other ignored
  files a copy needs (a local config, certificates): list them in a `.worktreeinclude` file at the root of the
  repository, with the syntax of `.gitignore` (the same file Claude Code reads); every new copy gets them.
- **Ports**: each copy has 10 ports of its own (4100-4109 for the first one, 4110-4119 for the next…), so that the dev
  servers of two copies never fight for 3000. Claude knows them; your preparation command and scripts read the first
  one in `$MAXXING_PORT`. Hover the branch in the bar to see them.
- **The bar above the composer**: the branch, `← main`, the commits of the branch, what is not committed; one main
  button: **Open a PR** on a GitHub repository, **Merge into main** otherwise. ⋯ **Bring in main** (asks Claude to
  merge the latest main and settle the conflicts), **Discard the copy**.
- **Finish** (the main button or ⋯): open a pull request, merge into the base on this server, or discard. Files not
  committed are committed first with a message Claude proposes. A merge brings the base into the branch first, in the
  copy: on a conflict nothing changes and Claude is asked to settle it. After a merge the copy and its branch go away;
  discarding deletes them too, with their commits (the window says what would be lost).
- **Open a PR**: the window shows the title and the description Claude wrote from the conversation of the session,
  its commits and its diff (filling in the repository's PR template when it has one); change them, or **Write again**.
- **Claude watches its PR**: while the PR is open, a check that fails, a conflict with main, or a comment or a review
  from someone of the repository wakes the session up: Claude reads it, fixes, commits and pushes, then says what it
  did. Once per event, never during a turn, 4 times a day at most; comments from people outside the repository and
  from bots are never passed on. The eye beside **#12** in the bar turns it off for that copy.
- **A PR merged on GitHub**: the bar says **PR #12 merged** and offers **Remove the copy**: the copy and its branch go
  (a squash or rebase merge counts too); nothing goes while files are left in it.
- The session stays: after the copy is gone it works in the topic folder again. A session sent to the trash takes its
  copy with it when nothing would be lost; otherwise the copy stays (the Git page lists the copies of a clone).
- A session on a copy cannot move to another topic. Agents never get a copy.

## Terminal

**Settings → Features → Sessions → Code mode** (off by default; your password is asked to turn it on, because a terminal runs any
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
