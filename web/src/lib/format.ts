// Formatting helpers. Always pass the user's language/timezone (useFormat() hook in i18n).

export function fmtBytes(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return '–'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024
    i++
  }
  return `${v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)} ${u[i]}`
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return '–'
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${s % 60 ? `${s % 60}s` : ''}`.trim()
  const h = Math.floor(m / 60)
  if (h < 48) return `${h}h ${m % 60 ? `${m % 60}m` : ''}`.trim()
  return `${Math.floor(h / 24)}d ${h % 24 ? `${h % 24}h` : ''}`.trim()
}

// Intl formatters are slow to build (a long thread formats hundreds of dates and numbers): one per
// language + options, reused. Same output as building a new one each time.
const formatters = new Map<string, Intl.NumberFormat | Intl.DateTimeFormat | Intl.RelativeTimeFormat>()
function cached<T extends Intl.NumberFormat | Intl.DateTimeFormat | Intl.RelativeTimeFormat>(kind: string, lang: string, opts: object | undefined, make: () => T): T {
  const key = `${kind}|${lang}|${opts ? JSON.stringify(opts) : ''}`
  let f = formatters.get(key) as T | undefined
  if (!f) {
    f = make()
    if (formatters.size > 200) formatters.clear()
    formatters.set(key, f)
  }
  return f
}

export function fmtNumber(n: number, lang: string, opts?: Intl.NumberFormatOptions) {
  return cached('n', lang, opts, () => new Intl.NumberFormat(lang, opts)).format(n)
}

export function fmtDate(at: number, lang: string, tz?: string, opts?: Intl.DateTimeFormatOptions) {
  const o: Intl.DateTimeFormatOptions = { dateStyle: 'medium', timeStyle: 'short', timeZone: tz || undefined, ...opts }
  return cached('d', lang, o, () => new Intl.DateTimeFormat(lang, o)).format(new Date(at * 1000))
}

/** "3 min ago" / "in 2 h" — `at` in Unix seconds. */
export function fmtRelative(at: number, lang: string, now = Date.now() / 1000): string {
  const diff = at - now
  const abs = Math.abs(diff)
  const rtf = cached('r', lang, undefined, () => new Intl.RelativeTimeFormat(lang, { numeric: 'auto', style: 'short' }))
  if (abs < 45) return rtf.format(0, 'second')
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour')
  if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), 'day')
  if (abs < 86400 * 365) return rtf.format(Math.round(diff / (86400 * 30)), 'month')
  return rtf.format(Math.round(diff / (86400 * 365)), 'year')
}
