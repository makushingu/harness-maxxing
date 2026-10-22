---
name: seo-audit
description: Run a practical SEO audit of a website - robots.txt, sitemap, status codes, titles and meta descriptions, headings, canonical, hreflang, images alt, Open Graph, internal links, page weight and Core Web Vitals - and write a prioritized report. Use when the user asks for an SEO audit, an SEO check, or why a site does not rank.
---

# SEO audit

Fetch real pages; never guess. Work with `curl -sL -A 'Mozilla/5.0 (compatible; SEO-audit)'` and a
short Python script (stdlib `html.parser`) to extract tags.

1. **Crawlability**: `robots.txt` (not blocking important paths, sitemap declared), `sitemap.xml`
   (exists, valid, URLs return 200, no redirects or noindex inside), HTTPS + one canonical host
   (http -> https, www or not: one 301 hop).
2. **Sample** the home page, 2-3 category / service pages and 3-5 content pages (from the sitemap).
   For each: status code, `<title>` (unique, 30-60 characters), meta description (70-160), one
   `<h1>`, logical h2/h3, `rel=canonical`, `meta robots`, `hreflang` if several languages,
   `og:title/og:image`, images without `alt`, internal links count, HTML size.
3. **Speed**: PageSpeed Insights, no key needed for a few calls:
   `curl -s 'https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=<URL>&strategy=mobile'`
   -> performance score, LCP, CLS, INP (field data when available).
4. **Content**: thin or duplicate pages, missing pages for obvious search intents, internal
   linking between related pages, structured data (`application/ld+json`) where it fits.
5. **Report** (`seo-audit-<date>.md` in the topic): a short summary, then a table *issue - why it
   matters - fix - effort* sorted by impact (critical / important / nice to have), with the exact
   URLs. Propose to fix what can be fixed from here (the site's files, or its CMS through an API key
   in Settings -> Keys) and note the audit date in the topic's memory.md to compare next time.
