---
name: pdf-document
description: Produce a well-designed PDF - a quote, an invoice, a report, a guide, a one-pager, a CV, a menu, a certificate - by writing HTML/CSS and printing it with the server's headless browser. Use when the user asks for a PDF or a printable document.
---

# PDF documents

1. Write one self-contained HTML file next to where the PDF belongs (the topic folder), with its
   CSS inline: `@page { size: A4; margin: 18mm }`, a clean font stack (system fonts, or a Google
   Font via `<link>`), headings, tables with borders, page breaks with `break-before: page`.
   Images: relative paths next to the HTML, or absolute `file://` paths.
2. Print it:
   ```bash
   maxxing pdf <file>.html <file>.pdf        # also works with an https:// URL
   ```
3. Check it: `pdftotext <file>.pdf - | head` for the text, and render page 1 to PNG
   (`pdftoppm -png -r 60 -f 1 -l 1 <file>.pdf /tmp/p1`) and look at it. Fix and print again.
4. Keep the HTML: the next version is an edit away. Never put secrets or bank details in the
   document unless the user gave them for this purpose.

No headless browser yet (`maxxing video status`)? `maxxing deps update` (as root) installs it.
