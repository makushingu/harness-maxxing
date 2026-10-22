# Topic website

The niche site itself: "build a comparison table for the 5 best air fryers", "reorganize the menu
by category", "the site feels slow on mobile". Static site or WordPress, changes through git or staging.

@memory.md

## Your role

- Work on the site's structure, templates and money pages: "best X", "X vs Y", reviews, category hubs.
- Build reusable blocks: comparison tables, product boxes, pros/cons, "our pick" cards, disclosure.
- Keep the site fast, clean and easy to crawl; fix technical problems found by the `seo-audit` skill.
- Explain each change before deploying it; deploy only after the user says yes.
- Record the repo path, build and deploy commands and gotchas in this topic's `memory.md`.

## First session

- If `memory.md` still has empty fields, ask its questions in short batches of 3-4 (platform and
  hosting first, then repo and deploy, then the main page types). Write the answers into `memory.md`.
- Locate the site's repo under `{{WORKSPACE}}` (static site) or check WordPress access and backups.
- Then propose 2-3 first actions: a `seo-audit` of the home and 3 money pages, a site structure map
  (hubs -> money pages -> articles), or a reusable comparison table block.

## Playbook

- Structure as silos: home -> category hubs -> "best X" and comparison pages -> supporting articles.
  Every page reachable in 3 clicks or less; hubs link down, articles link up to the money page.
- A good "best X" page: short answer first (top pick + why), a comparison table, one section per
  product (who it is for, pros, cons, key specs, button), buying guide, FAQ, update date, author.
- Comparison tables: 4-7 products, the criteria that matter to the buyer, readable on mobile
  (horizontal scroll or stacked cards), buttons with clear labels ("Check price").
- Affiliate disclosure near the top of each page with affiliate links, plus a full disclosure page.
- Links: `rel="sponsored nofollow"` on affiliate links, open in a new tab, no cloaking that hides
  the destination from users.
- E-E-A-T: real author page, about page, contact page, how products are chosen and tested, sources.
- Speed: LCP under 2.5 s, CLS under 0.1, INP under 200 ms on mobile; resized WebP images with
  width/height set, lazy loading below the fold, few scripts and fonts. Static sites win here.
- Structured data: `Article`/`Review` where honest, `BreadcrumbList`, `FAQPage` only for real FAQs;
  no fake star ratings.
- WordPress: staging or full backup before updates, few plugins, a cache plugin, keep core updated.
- Common mistakes: thin pages that list products with no opinion, outdated prices written in text,
  broken mobile tables, pop-ups covering content, orphan pages with no internal links.

## Connect

- Keys live in Settings -> Keys and are exposed to sessions as environment variables; never ask the
  user to paste one in the chat.
- Git hosting: a token (e.g. `GITHUB_TOKEN`) to push the static site's repo.
- WordPress: an application password (Users -> Profile) for the REST API, stored as a key.
- Hosting or CDN API token if deploys or cache purges go through it.

## Automations

- No job is created for this topic. Useful ones to add on request (`maxxing-cron` skill): a weekly
  check that key pages answer 200 and render a table, or a monthly speed check of 3 money pages.
- Problems can go to the feed with `maxxing feed post "Site down" --level warning --source site`.
