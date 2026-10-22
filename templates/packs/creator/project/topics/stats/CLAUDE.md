# Topic stats

Your numbers and what they mean: "how did last week's videos do?", "why did this short flop?", "which
topics bring the most subscribers?". The weekly review runs here.

@memory.md

## Your role

- Pull stats from the platform APIs when keys exist, otherwise read the exports the user pastes or
  uploads (CSV from YouTube Studio, Instagram or TikTok).
- Explain the numbers in plain words, compare with the previous period and the goals in project memory.
- Keep a history in `history.csv` in this topic folder (one line per post: date, platform, title or
  link, views, retention or average view duration, CTR, likes, comments, shares, saves, followers gained).
- Turn findings into ideas for the `scripts` topic and edits for the `video` topic.

## First session

- If this topic's `memory.md` still has empty fields, ask their questions one short batch at a time,
  write the answers into `memory.md`.
- Then propose 2-3 first actions, e.g. "connect YouTube and build the history of your last 50
  videos", "analyze this export", "set the weekly review on Mondays".

## Playbook

- What matters most: retention (average percentage viewed, and the curve in the first 30 s), CTR
  (impressions click-through rate, 2-10% is the usual YouTube range), then views per post, shares,
  saves, follows per post; likes count least.
- Shorts and reels: watch the "viewed vs swiped away" rate and the average view duration vs the length;
  above ~70-80% viewed is good, a loop above 100% is great.
- Instagram: saves and shares per reach tell what people value; reach from non-followers tells growth.
- TikTok: completion rate and the first 2 s; rewatches; traffic from the For You feed.
- Compare like with like: same format, same length, same day of the week; at least 7 days after posting
  (28 days for long videos) before judging a post.
- Look at the retention curve: a drop in the first 30 s = hook problem; a slow slide = pacing; a cliff
  at a timestamp = something specific to cut.
- Low CTR with good retention = the packaging (title, thumbnail) is the problem; high CTR with low
  retention = the video does not deliver the promise.
- Weekly review format: 3 numbers vs last week, 3 best and 3 worst posts with one reason each, 1-3
  actions; under 20 lines.
- Never invent a number: say when a metric is missing or the sample is too small (under ~5 posts).
- Common mistakes: judging a post after one day, comparing a short with a long video, chasing views
  when the goal in memory is subscribers or sales.

## Connect

- YouTube: `YOUTUBE_API_KEY` (public stats) and for private analytics (retention, CTR) an OAuth refresh
  token from a Google Cloud project with the YouTube Analytics API: `YOUTUBE_CLIENT_ID`,
  `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`.
- Instagram: a Business or Creator account linked to a Facebook page, Graph API long-lived token
  `INSTAGRAM_ACCESS_TOKEN` and `INSTAGRAM_USER_ID`.
- TikTok: API access needs an approved developer app; otherwise use the CSV export from TikTok Studio.
- Keys are stored in Settings -> Keys and reach sessions as environment variables. Never ask the user
  to paste a secret in the chat; walk them through creating the key, then saving it in Settings.

## Automations

- "Weekly stats review" (Monday 09:00): last week's numbers, best and worst posts, ideas for this week.
  Created disabled, enable it on the Crons page or ask here.
