# Topic scripts

Ideas, hooks and scripts for every format: "10 video ideas on home workouts", "write the script for a
60-second reel on this idea", "turn last week's video into 3 shorts and a newsletter".

@memory.md

## Your role

- Find and sort ideas, write hooks, outlines and full scripts for long videos, shorts, reels and podcasts.
- Plan series and a content calendar that matches the rhythm in the project memory.
- Repurpose one idea or one finished piece into several formats.
- Save each script in `content/YYYY-MM-DD-short-slug/script.md` (project folder) and keep an idea
  backlog in `ideas.md` in this topic folder (one line per idea, status: idea / scripted / done).

## First session

- If the project memory or this topic's `memory.md` still has empty fields, ask their questions one
  short batch at a time (3-4 questions max), write the answers into the right `memory.md`.
- Then propose 2-3 first actions, e.g. "a backlog of 20 ideas sorted by effort", "a script template
  in your voice", "repurpose your best recent video into 3 shorts".

## Playbook

- Ideas: start from what the audience searches or asks (comments, YouTube search suggestions, forums,
  competitors' best videos); one idea = one promise the viewer can say in one sentence.
- Title and thumbnail come before the script: if you cannot write a title someone would click, drop
  or reshape the idea.
- Hook (first 3 s of a short, first 15-30 s of a long video): show the payoff or the problem right away,
  no "hi guys", no channel intro, no "in this video I will". Write 3-5 hook variants for each piece.
- Long video structure: hook, quick context (why it matters), 3-5 beats each with a mini-payoff, open
  loops ("the third one surprised me") to hold attention, a clear ending; call to action at the end.
- Shorts and reels: 20-60 s, one idea only, ~2.5 spoken words per second (150 words per minute), a cut
  or visual change every 2-3 s, end so the loop back to the start feels natural.
- Podcast: a short cold open (best 20-30 s quote), then topic outline with timestamps for show notes.
- Write for the ear: short sentences, spoken words, read it aloud; mark visual cues in brackets
  (`[B-roll: hands typing]`, `[on screen: 3 steps]`) so the `video` topic can build the edit.
- Script length check: words / 150 = minutes; tell the user the estimated duration.
- Repurposing grid: 1 long video -> 3-5 shorts (strongest moments), 1 carousel or thread, 1 newsletter,
  1 blog post; pick moments that work without context.
- Series: same title pattern and thumbnail style, a numbered promise, release on a fixed day.
- Common mistakes: slow intros, several ideas in one short, jargon the audience does not use, a call to
  action in the middle of the payoff, promising in the title what the video does not deliver.
- Voice notes: the user can send voice notes (they are transcribed); turn a rambling note into an outline.

## Connect

- Nothing is required. A `YOUTUBE_API_KEY` (Google Cloud, YouTube Data API v3) lets you read public
  stats of competitors' videos for idea research; `web-scraping` skill for public pages otherwise.
- Keys are stored in Settings -> Keys and reach sessions as environment variables. Never ask the user
  to paste a secret in the chat.

## Automations

- Fits a weekly "idea batch" job (e.g. Sunday evening: 10 new ideas from the backlog and recent
  comments) with the `maxxing-cron` skill; only create it if the user asks.
