---
section: Extending
---
# Skills

Skills are instructions Claude Code loads on its own when a task matches their description. Claude
Maxxing installs its skills in `~/.claude/skills/`, so they are available in **every** session.
The copies name the real folders of your install (code, workspace, state), so they stay right when the
installer used other paths than the defaults; `maxxing init` (run by every update) writes them again.

## Shipped skills

| Skill | Claude uses it when |
|---|---|
| `memory` | an exchange produced something durable: it records it in the right memory.md |
| `memory-compaction` | memory files grew too long or contradictory (also run daily by a job) |
| `maxxing-setup` | you say "set up Harness Maxxing", or want to finish/verify an installation |
| `maxxing-doctor` | something does not work: UI down, sessions failing, jobs not running |
| `maxxing-telegram` | you configure or troubleshoot the Telegram bridge |
| `maxxing-backup` | you configure, run or restore the backup, or move to a new server |
| `maxxing-cron` | you want something to happen on a schedule |
| `maxxing-tasks` | you talk about your tasks or the board |
| `maxxing-feed` | you say "notify me when…", or want sales, orders, deployments, e-mails or a script's results reported (webhooks, `maxxing feed post`) |
| `maxxing-mcp` | you want Claude to use a service through MCP ("connect the Google Ads MCP"), an MCP tool is missing or needs a sign-in |
| `maxxing-extension` | you want a dashboard widget (Card, or HTML: a game, a canvas) or a custom page |
| `maxxing-customize` | you want to change the product itself, or an update reports that your customizations need adapting |
| `video-motion-design` | you ask for a video, an animation, a short / reel or a trailer (Remotion, see [Videos, PDFs and images](tools)) |
| `pdf-document` | you ask for a PDF: a quote, an invoice, a report, a guide |
| `image-edit` | you want images resized, converted, compressed or batch-processed |
| `seo-audit` | you ask for an SEO audit or why a site does not rank |
| `web-scraping` | you want data collected from a website (prices, catalogue, listings…) or a page watched for changes |

You can also name a skill explicitly: "use the maxxing-doctor skill".

`maxxing init` and `maxxing update` keep these up to date. They overwrite only the product skills
(names starting with `maxxing-`, plus `memory`, `memory-compaction`, `video-motion-design`,
`pdf-document`, `image-edit`, `seo-audit` and `web-scraping`). If a skill with one of
those names already existed, it is moved to `/var/lib/claude-maxxing/trash/skills/` first.

## Adding your own skills

Create a folder with a `SKILL.md`:

```
~/.claude/skills/blog-article/SKILL.md            user level: available in every session
/root/maxxing/.claude/skills/blog-article/SKILL.md  workspace level: included in the memory backup
```

```markdown
---
name: blog-article
description: Write and publish a blog article for the Acme blog. Use when asked for a new article, a draft, or the next subject of the editorial plan.
---

# Blog article

1. Pick the next subject in projects/acme/topics/blog/plan.md ...
2. ...
```

Tips:
- The **description** decides when Claude uses the skill: say *what* it does and *when* to use it.
- Keep the body a precise procedure: steps, paths, commands, checks, what never to do.
- Every skill's name and description is sent with **every** prompt of every session. Past Claude Code's budget
  (about 8,000 characters), the descriptions of the least used skills are dropped and Claude picks them less
  reliably - `maxxing doctor` shows the total. Keep a skill that only one project uses in that project
  (`projects/<p>/.claude/skills/`: loaded only in its topics), or add `disable-model-invocation: true` to its
  frontmatter so only you can call it (`/name`).
- Put helper scripts next to `SKILL.md` and reference them by path.
- Ask Claude to write the skill for you after you have done a task together once: "turn what we
  just did into a skill".
- Custom skills are never overwritten by updates. Skills under `<workspace>/.claude/skills/` are
  included in the backup; user-level skills in `~/.claude/skills/` are not.
- Check how your Claude Code version discovers project-level skills (`claude --help`, Claude Code
  docs) if a workspace skill is not picked up in a topic session; the user level always works.
