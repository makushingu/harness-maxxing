---
section: Using Harness Maxxing
---
# Git & GitHub

Harness Maxxing shows git as pictures: the branches, the commits, what is not pushed yet. Two places:

- **In a conversation**, for everyone: when Claude talks about a repository, it adds a small `git` block and the
  app draws the real graph of that repository, read live from the server (or from GitHub).
- **The Git page** (sidebar -> **Git**): every repository of the server and of your GitHub account, with your
  rights on each; click one to see all its branches and commits. Turn it on in Settings -> Features.

Everything is read-only: nothing is ever committed, pushed or changed from these views.

## Graphs in the chat

Ask "where are we on the acme repository?", "what is not pushed?", "show me the branches": Claude answers with a
block like this one, drawn as a graph (Telegram shows the text):

````
```git
repo: /root/sites/acme
branches: main, feat-login
limit: 20
highlight: 3f2a9c1
```
````

| Line | Meaning |
|---|---|
| `repo:` | the folder of the clone on the server (absolute path), or `github:owner/name` for a GitHub repository |
| `branches:` | optional: only these branches (otherwise all of them) |
| `limit:` | optional: how many commits (30 by default, 300 at most) |
| `highlight:` | optional: commits to point out (the ones Claude is talking about) |

Click a commit to see its full message, author, date and the files it changed (+/- lines). **Code** shows the block's
text; **Open in Git** opens the full page (when the Git page is on).

Right click a branch label or a commit (long press on a phone), in the chat or on the Git page: **Open on GitHub**
opens that branch or commit on github.com in a new tab, **Copy the GitHub link** copies its address, and the last item
copies the branch name or the commit SHA. A branch or commit of a clone opens once it is pushed to `origin` on GitHub
(before that the item says "not on GitHub yet"); a graph read from GitHub opens everything.

The repository must be inside the files root (`/root` by default): the same folders the Files page shows.

## The Git page

**Git** in the sidebar (shortcut `G` then `B`), once **Git & GitHub page** is turned on in **Settings -> Features**
(off by default; the graphs in conversations work either way).

- **On this server**: every git repository found under the files root, once (folders like `node_modules` are
  skipped), with the commits not pushed yet (↑) or not pulled (↓), the changed files, its last commit and its
  GitHub repository. Branches are not listed here: they are in the repository's graph (a card only names the
  checked-out branch when it is not `main`/`master`, or says *detached*). The extra working folders
  of a clone (`git worktree add`, one folder per branch) are not shown as repositories of their own: the clone says
  how many it has (*+3 worktrees*).
- **GitHub**: every repository of your account (yours, your organisations', the ones you collaborate on) with
  your right on it (admin, maintain, write, triage, read), private or public, and "cloned here" when the server
  has a copy.
- Click a repository: the graph of its branches and commits (the 200 most recent, **Show more** for up to 1,000),
  the details of a commit (in a sheet from the bottom on a phone or a tablet), and for GitHub the open pull
  requests. A clone linked to GitHub has a button to switch between the server's copy and GitHub (which shows every
  branch, even those not fetched on the server). With many branches, the lines of the graph squeeze on a narrow
  screen and long branch names end with "…" (full name on hover).

### Connect GitHub

The server's clones need nothing. For your GitHub account, add a token:

1. On GitHub: Settings -> Developer settings -> **Fine-grained tokens** -> Generate new token
   (github.com/settings/personal-access-tokens). Repository access: all repositories; permissions: **Contents**,
   **Metadata** and **Pull requests**, read-only.
2. In Harness Maxxing: **Settings -> Keys** -> add it, for example as `GITHUB_TOKEN`.

**Every GitHub token of the vault is used, whatever its name** (`GITHUB_TOKEN`, `GITHUB_PAT_BLOG`...), plus the one of
the memory backup: add one per account to see several accounts, or tokens limited to a few repositories. The page
lists the connected accounts at the top (click one to filter), merges their repositories (each once, with your best
right), shows which keys see each repository, and warns about a key GitHub refuses (expired, revoked) while still
showing the others. To open a repository, the server uses a key that has access to it. Tokens stay on the server:
the page only ever sees their names.

### Safety

The page only reads repositories: it never fetches, pulls or pushes. A repository found on the server may come
from anywhere (an extracted archive, a clone made by Claude), so the settings of a repository that would make git
run a program while reading it (file monitor, signature check, clean filters, external diff, hooks) are switched
off, and a repository owned by another system user is not opened (git's own ownership check). When GitHub's rate
limit is reached, the page says so instead of showing repositories as missing.
