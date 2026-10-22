---
name: web-scraping
description: Collect data from websites with Scrapling - one page or a whole site, static or JavaScript pages, into Markdown, CSV or JSON (prices, catalogues, listings, contacts, articles, reviews), and watch a page for changes on a schedule. Use when the user asks to scrape, extract, collect, crawl or monitor data from a website.
---

# Web scraping (Scrapling)

Scrapling is installed on the server (`scrapling`, `scrapling-python`; check: `maxxing video status`).
Three ways to fetch, from the lightest to the heaviest - start light, go up only if needed:

| Fetcher | CLI | Use when |
|---|---|---|
| `Fetcher` (HTTP, real browser TLS) | `scrapling extract get URL out.md` | normal pages, APIs, sitemaps - fast |
| `DynamicFetcher` (Chromium) | `scrapling extract fetch URL out.md` | the content is built by JavaScript (empty result with `get`) |
| `StealthyFetcher` (Chromium, more human) | `scrapling extract stealthy-fetch URL out.md` | the site blocks plain browsers |

`out.md` gives Markdown (best to read), `out.txt` text, `out.html` HTML. Add `--css-selector '.price'`
to keep only part of the page. `scrapling extract get --help` lists options (headers, cookies, proxy).

## Structured data: a small script
```python
# scrape.py - run with: scrapling-python scrape.py
import csv
from scrapling.fetchers import Fetcher            # or DynamicFetcher / StealthyFetcher (.fetch(url))

rows, url = [], "https://example.com/products?page=1"
while url and len(rows) < 500:
    page = Fetcher.get(url)
    for card in page.css('.product'):
        rows.append({"name": card.css('.title::text').get(), "price": card.css('.price::text').get(),
                     "url": page.urljoin(card.css('a::attr(href)').get() or "")})
    nxt = page.css('a.next::attr(href)').get()
    url = page.urljoin(nxt) if nxt else None
with open("products.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["name", "price", "url"]); w.writeheader(); w.writerows(rows)
print(len(rows), "rows")
```
Selectors: `css()` / `xpath()` return a list - `.get()` the first value, `.getall()` all of them
(`::text`, `::attr(href)` like Scrapy); `find_all()`, `get_all_text()`; `page.urljoin()`, `page.status`. Inspect the real
HTML first (`scrapling extract get URL page.html`, then read it) instead of guessing selectors.

## Rules
- Be polite: respect `robots.txt` and the site's terms, one request at a time with a pause
  (`time.sleep(1)`) on multi-page jobs, a clear stop (page limit), no login-protected or personal
  data without the user's explicit permission. Prefer an official API or an export when one exists.
- Save results in the topic folder (`data/<name>-<date>.csv|json|md`), never only in the chat; tell
  the user the path, the row count and 2-3 sample rows. Keep the script next to the data so the
  job can be re-run.
- Monitoring ("tell me when the price changes"): a scheduled job (skill `maxxing-cron`) that runs
  the script, compares with the last saved result and reports only changes.
