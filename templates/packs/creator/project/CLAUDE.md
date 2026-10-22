# Project creator

Your content studio, from idea to numbers: "give me 10 hooks for a video on budgeting", "make captions
for this clip", "which videos kept people watching last month?".

## Topics

- `scripts`: ideas, hooks, scripts for long videos, shorts, reels and podcasts, series, repurposing.
- `video`: editing with Remotion, captions and subtitles, B-roll lists, thumbnails, export per platform.
- `stats`: platform numbers (YouTube, Instagram, TikTok), what they mean, and the weekly review.

## Shared conventions

- The creator's facts (niche, audience, channels, formats, tone, posting rhythm, goals) live in this
  project's `memory.md`. Read it before any work; fill it in during the first session of any topic.
- Topic-specific facts (script template, editing style, API accounts) live in the topic's `memory.md`.
- Files: one folder per piece of content, `content/YYYY-MM-DD-short-slug/` in this project (script,
  assets, renders, thumbnail, notes). Keep raw footage out of git and out of memory files.
- Keys and tokens are stored in Settings -> Keys and reach sessions as environment variables. Never
  ask the user to paste a secret in the chat, never write one into a file.
- Never publish, schedule, delete or reply to anything on a platform without an explicit "yes" from
  the user in the current conversation.
- Write in the creator's voice and language as noted in memory; no generic "AI" phrasing, no clickbait
  the content does not deliver.
- Follow-ups go to the task board (`maxxing-tasks` skill); alerts that matter go to the feed
  (`maxxing-feed` skill, e.g. `maxxing feed post "Render done: ep-12" --level info --source creator`).

@memory.md
