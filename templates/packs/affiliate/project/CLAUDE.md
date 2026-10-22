# Project affiliate

Your niche affiliate site, split by job: "plan a best X under 100 page", "which links are broken?",
"why did traffic drop last week?".

## Topics

- `website`: the site itself (static site or WordPress): structure, comparison pages, speed, disclosure.
- `blog`: SEO articles, keyword research, internal links and updating old posts.
- `affiliation`: programs, links, commission rates, revenue tracking, broken or out-of-stock links.
- `google`: Search Console, rankings, indexing, Core Web Vitals and Google Ads if any.

## Shared conventions

- The site's facts (URL, niche, audience, tone, platform, programs) live in this project's
  `memory.md`. Read it before any work; fill it in during the first session of any topic.
- Topic-specific facts (repo, keyword list, program IDs, Search Console property) live in the
  topic's `memory.md`.
- Keys and tokens are stored in Settings -> Keys and reach sessions as environment variables. Never
  ask the user to paste a secret in the chat, never write one into a file.
- Honesty first: no fake reviews, no invented tests or prices. Say "based on the specs and user
  reviews" when the product was not tested by the user. Every page with affiliate links shows a disclosure.
- Never publish, delete pages or change live links without an explicit "yes" from the user.
- Follow-ups go to the task board (`maxxing-tasks` skill); alerts go to the feed (`maxxing-feed`
  skill, e.g. `maxxing feed post "12 broken affiliate links" --level warning --source site`).

@memory.md
