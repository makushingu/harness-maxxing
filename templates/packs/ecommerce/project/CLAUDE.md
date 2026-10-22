# Project ecommerce

Everything about your online store, split by job: "how many orders today?", "write a brief for a new
Meta ad", "fix the add-to-cart button on mobile".

## Topics

- `code`: the store's site or theme, its git repo, deploys, speed and checkout bugs.
- `orders`: today's orders, shipping, customer service replies, refunds and stock.
- `ads`: Meta, Google and TikTok ads: briefs, creatives, budgets and the weekly review.
- `social`: Instagram, TikTok and Pinterest posts, captions, content calendar, short videos.

## Shared conventions

- The store's facts (name, URL, platform, products, audience, tone of voice, policies) live in this
  project's `memory.md`. Read it before any work; fill it in during the first session of any topic.
- Topic-specific facts (carrier, ad accounts, posting rhythm, repo) live in the topic's `memory.md`.
- Keys and tokens are stored in Settings -> Keys and reach sessions as environment variables. Never
  ask the user to paste a secret in the chat, never write one into a file.
- Never spend money, change prices, issue refunds, email customers or publish anything without an
  explicit "yes" from the user in the current conversation.
- Numbers: always say the period and the currency, and compare with the previous period.
- Follow-ups go to the task board (`maxxing-tasks` skill); alerts that matter go to the feed
  (`maxxing-feed` skill, e.g. `maxxing feed post "Stock low: Blue mug" --level warning --source shop`).

@memory.md
