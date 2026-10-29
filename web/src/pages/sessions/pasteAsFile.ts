// Pasted data becomes an attachment instead of a wall of text in the composer: JSON, XML / HTML, CSV / TSV,
// logs, tokens and dumps, and any very long paste. Prose (a prompt, even a long one) and short snippets stay text.
// Ctrl+Shift+V (⌘⇧V) always pastes as text; the toast shown after the switch puts the text back too.

export type PastedFile = { ext: string; type: string }

const MIN_STRUCTURED = 400 // valid JSON / XML / CSV from this size
const MIN_DATA = 2000 // other non-prose text from this size
const HUGE = 20000 // anything from this size
const LONG_TOKEN = /\S{200,}/ // a cookie, a key, base64...

const JSON_FILE = { ext: 'json', type: 'application/json' }
const TEXT_FILE = { ext: 'txt', type: 'text/plain' }

function isJson(s: string): boolean {
  if (!/^[[{][\s\S]*[\]}]$/.test(s)) return false
  try {
    JSON.parse(s)
    return true
  } catch {
    return false
  }
}

// One JSON object per line (logs, exports): at least 3 lines, every one parses.
function isJsonLines(lines: string[]): boolean {
  const rows = lines.filter((l) => l.trim())
  return rows.length >= 3 && rows.every((l) => isJson(l.trim()))
}

// Same number (2 or more) of the same separator on almost every line.
function delimited(lines: string[]): PastedFile | null {
  const rows = lines.filter((l) => l.trim())
  if (rows.length < 4) return null
  for (const [sep, file] of [
    ['\t', { ext: 'tsv', type: 'text/tab-separated-values' }],
    [',', { ext: 'csv', type: 'text/csv' }],
    [';', { ext: 'csv', type: 'text/csv' }],
  ] as const) {
    const counts = rows.map((l) => l.split(sep).length - 1)
    const n = counts[0]
    if (n >= 2 && counts.filter((c) => c === n).length >= rows.length * 0.9) return file
  }
  return null
}

// Share of code / markup signs: about 0 in a prompt (even with a few links), 5-10 % in code, logs, dumps.
function symbolShare(s: string): number {
  return (s.match(/[{}[\]<>=/\\$_`|&*#@^~+%]/g)?.length ?? 0) / s.length
}

// Most lines start with a date or a time: a log.
function isLog(lines: string[]): boolean {
  const rows = lines.filter((l) => l.trim())
  return rows.length >= 10 && rows.filter((l) => /^\W{0,2}(\d{4}-\d\d-\d\d|\d\d:\d\d:\d\d|[A-Z][a-z]{2} +\d+ \d\d:)/.test(l)).length >= rows.length * 0.6
}

/** What a pasted text should become: a file (its extension and type), or null to paste it as text. */
export function pastedFile(text: string): PastedFile | null {
  const s = text.trim()
  if (s.length < MIN_STRUCTURED) return null
  const lines = s.split(/\r?\n/)
  if (isJson(s)) return JSON_FILE
  if (isJsonLines(lines)) return { ext: 'jsonl', type: 'application/x-ndjson' }
  if (/^<[?!a-z][\s\S]*>$/i.test(s) && lines.length >= 3) {
    return /^<(!doctype html|html|head|body)\b/i.test(s) ? { ext: 'html', type: 'text/html' } : { ext: 'xml', type: 'application/xml' }
  }
  const table = delimited(lines)
  if (table) return table
  if (s.length >= MIN_DATA && isLog(lines)) return { ext: 'log', type: 'text/plain' }
  if (s.length >= HUGE) return TEXT_FILE
  if (s.length >= MIN_DATA && (LONG_TOKEN.test(s) || symbolShare(s) > 0.03)) return TEXT_FILE
  return null
}

/** `pasted-2026-10-29-143205.json`, in local time. */
export function pastedName(ext: string, now = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  const day = `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`
  return `pasted-${day}-${p(now.getHours())}${p(now.getMinutes())}${p(now.getSeconds())}.${ext}`
}
