---
section: Extending
---
# Videos, PDFs and images

The installer prepares the tools Claude needs for everyday work, so you can ask for a video, a PDF
or a batch of images in any session - no setup.

| Installed | Used for |
|---|---|
| Node.js 22 + **Remotion** | motion design videos written in React (skill `video-motion-design`) |
| Chromium (one for everything) | HTML -> PDF (`maxxing pdf`, skill `pdf-document`), video renders and Scrapling share the same browser |
| ImageMagick, ffmpeg | resize, convert, compress, thumbnails (skill `image-edit`) |
| poppler-utils | read and preview PDFs (`pdftotext`, `pdftoppm`) |
| **Scrapling** + Chromium | web scraping: static, JavaScript and protected pages -> Markdown, CSV, JSON (skill `web-scraping`) |
| zip, unzip, jq, ripgrep | archives (exports, imports), JSON, fast search |

## Videos

Ask "make a 20-second vertical video announcing our summer sale". Claude creates a project
(`maxxing video new <topic>/videos/<name>`), writes the scenes, checks a few frames, renders an MP4
and gives you its path (open it in Files). Remotion is installed once in
`/var/lib/claude-maxxing/tools/remotion`; each project links to it, so it takes a second to create
and weighs a few MB.

## PDFs

Ask "make a PDF quote for …" or "turn this report into a nice PDF": Claude writes an HTML page and
prints it with `maxxing pdf page.html page.pdf` (A4, backgrounds, your fonts).

## Web scraping

Ask "collect the name and price of every product on this site into a CSV" or "tell me every morning
if this page changes". Claude uses Scrapling: `scrapling extract get|fetch|stealthy-fetch URL out.md`
for one page (plain HTTP, or a real browser for JavaScript pages), or a short Python script run with
`scrapling-python` for structured data over several pages. Results land in the topic (`data/`),
with the script, so the job can be re-run or scheduled. It respects `robots.txt` and goes slowly by
default; personal or login-protected data only with your explicit say-so. No MCP server is added
(it would cost context in every session): Claude calls the command line.
Installed in `/var/lib/claude-maxxing/tools/scrapling` (every package pinned with its checksum) and `tools/browsers` (Chromium, shared with videos and PDFs), ~750 MB.

## Images and SEO

`image-edit` covers resizing, webp conversion, compression, crops, thumbnails and contact sheets,
one file or whole folders. `seo-audit` checks a website for real (robots.txt, sitemap, titles,
descriptions, headings, canonical, Open Graph, Core Web Vitals through PageSpeed) and writes a
prioritized report in the topic.

## Check or repair

```bash
maxxing video status                          # Node.js, Remotion, headless browser, Scrapling
maxxing deps list                             # versions of every component
maxxing deps update                           # (re)install the tools, as root
```
`maxxing doctor` warns (never fails) when they are missing.
