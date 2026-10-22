---
name: memory-compaction
description: Compact memory.md files (global, projects, topics) that became long, redundant, contradictory or outdated. Run by the daily "Memory compaction" job; use it on demand when the user asks to clean up or shorten memory.
---

# Memory compaction

Goal: memory files stay **short, consistent and current**. Most days there is nothing to do; that
is the expected outcome.

## Procedure
1. Run `maxxing memory`: it lists every memory file (`memory.md`, `projects/*/memory.md`,
   `projects/*/topics/*/memory.md`) with its line count, and the **line limit** set in
   Settings -> Memory (default 200; `none` = no limit). A limit given in the prompt wins.
2. Compact a file **only if** at least one is true:
   - it has more lines than the limit (or, without a limit, larger than ~20 KB or ~400 lines);
   - facts contradict each other (keep the most recent);
   - duplicates or near-duplicates;
   - clearly outdated content (finished work long ago, old states superseded by newer ones).
3. When compacting:
   - the result must fit the limit: aim for ~80 % of it so the file has room to grow;
   - reorder into this structure (skip empty sections), most important first inside each:
     `# <title>` line kept as is, then `## Rules & preferences`, `## Current state`,
     `## Decisions`, `## References` (paths, URLs, commands), `## Context` (summarised history);
   - merge duplicates, settle contradictions (latest wins), keep dates on decisions;
   - summarise old history into one or two "Context" bullets, drop the rest;
   - move a fact to the right level if it is obviously misplaced (topic fact in global memory);
   - **never remove**: what is needed to understand the project, the user's preferences and rules,
     structural decisions, conventions, paths/URLs still in use.
4. Nothing to do -> change nothing.
5. End with one line per file changed (`projects/acme/memory.md: 412 -> 160 lines, merged 8 duplicates`)
   or `nothing to compact`.

## Safety
- Only edit `memory.md` files. Never `CLAUDE.md`, code, tasks.json or anything else.
- If unsure whether something is still useful, keep it.
- Never paste secrets; if you find one in a memory file, replace it by the key name and tell the
  user to rotate it (Settings -> Keys).
- The memory backup keeps history in git, so a past version can always be restored
  (`maxxing-backup` skill).
