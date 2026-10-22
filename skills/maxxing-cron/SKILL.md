---
name: maxxing-cron
description: Create, change, disable or debug Harness Maxxing scheduled jobs (shell commands or Claude prompts run in a topic on a cron schedule, with Telegram reports). Use when the user wants something to happen every day/hour/week, asks about crons, or a job did not run.
---

# Scheduled jobs

Jobs are managed by Harness Maxxing and stored in `{{STATE_DIR}}/crons/jobs.json`. Each
enabled job is one line of a **managed block** in root's crontab calling `maxxing cron run <id>`;
lines outside the block are never touched. Run history: `crons/runs.jsonl` (shown in the Crons page).

## Prefer the UI
Crons page -> New job: name, schedule (with a live preview of the next runs), type, notify policy,
timeout. "Run now" and history are there too.

## Job fields
| Field | Meaning |
|---|---|
| `name` | short label (max 80 chars) |
| `schedule` | 5-field cron expression in the **server system time zone** (keep it equal to the config time zone - `maxxing doctor` checks it) - `min hour day month weekday`; also `@daily`, `@hourly`, `@weekly`, `@monthly`, `@reboot` |
| `kind` | `shell` (runs `command` with bash) or `claude` (sends `prompt` to a Claude session in `topic_path`) |
| `command` | shell only, e.g. `{{WORKSPACE}}/projects/acme/scripts/report.sh` |
| `topic_path` | claude only: `projects/acme/topics/blog` (`""` = workspace root) |
| `prompt` | claude only: the instruction, self-contained (the job has no conversation context unless `reuse_session`) |
| `model` | claude only, `""` = default model |
| `reuse_session` | claude only: keep one session for every run (it accumulates context) instead of a new one per run |
| `enabled` | on/off |
| `notify` | `never` \| `failure` (default) \| `always` - Telegram report in the "Crons" thread |
| `timeout_s` | max duration, 10 s to 7 days (default 3600) |

Schedule examples: `0 7 * * *` every day 07:00 · `*/15 * * * *` every 15 min · `30 8 * * 1-5`
weekdays 08:30 · `0 9 1 * *` 1st of the month 09:00 · `0 */6 * * *` every 6 h.

## Without the UI (CLI + file)
1. Read `{{STATE_DIR}}/crons/jobs.json` (`{"version": 1, "jobs": [...]}`).
2. Add or edit a job object with the fields above plus a unique `id` (`c_` + 6 hex chars, e.g.
   `c_3fa91c`), `created`/`updated` (Unix seconds). Keep unknown fields. Write atomically (write a
   temp file in the same folder, then rename).
3. `maxxing cron sync` - rewrites the crontab block. `maxxing cron list` - check.
4. `maxxing cron run <id>` - test it now (records a run, sends the report per `notify`).

## Good practice
- Claude jobs: say exactly what to produce and where to write it; mention the skill to use if one
  exists ("Use the memory-compaction skill…"). Claude jobs appear as sessions flagged *cron*.
- Shell jobs: absolute paths, idempotent scripts, write their own logs if long; the run keeps the
  last 2 KB of output.
- Long work: raise `timeout_s` rather than chaining jobs. Overlapping runs of the same job are skipped.
- Debug: `maxxing cron list` (last result), `maxxing cron run <id>`, `crontab -l`, `systemctl status cron`.
- Never edit lines inside the `# >>> claude-maxxing (managed) >>>` block by hand: they are rewritten.
