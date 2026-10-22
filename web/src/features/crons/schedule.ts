// Schedule presets <-> 5-field cron expressions. Anything that does not match a preset is "custom"
// (the raw expression field stays the source of truth; the server validates and humanises it).

export type PresetKind = 'minutes' | 'hours' | 'hourly' | 'daily' | 'weekdays' | 'weekly' | 'monthly' | 'custom'
export type Preset = {
  kind: PresetKind
  every: number // minutes / hours interval
  minute: number
  hour: number
  weekday: number // 0 = Sunday
  day: number // day of month
}
export const DEFAULT_PRESET: Preset = { kind: 'daily', every: 15, minute: 0, hour: 7, weekday: 1, day: 1 }
export const PRESET_KINDS: PresetKind[] = ['minutes', 'hours', 'hourly', 'daily', 'weekdays', 'weekly', 'monthly', 'custom']

const int = (s: string, lo: number, hi: number): number | null => {
  if (!/^\d{1,2}$/.test(s)) return null
  const n = Number(s)
  return n >= lo && n <= hi ? n : null
}

/** Best-effort match of an expression to a preset (base = values to keep for the other fields). */
export function toPreset(expr: string, base: Preset = DEFAULT_PRESET): Preset {
  const src = expr.trim().toLowerCase()
  const short: Record<string, string> = { '@hourly': '0 * * * *', '@daily': '0 0 * * *', '@midnight': '0 0 * * *', '@weekly': '0 0 * * 0', '@monthly': '0 0 1 * *' }
  const parts = (short[src] || src).split(/\s+/)
  const custom = { ...base, kind: 'custom' as const }
  if (parts.length !== 5) return custom
  const [mi, h, dom, mon, dow] = parts
  if (mon !== '*') return custom
  if (mi === '*' && h === '*' && dom === '*' && dow === '*') return { ...base, kind: 'minutes', every: 1 }
  const step = /^\*\/(\d{1,2})$/.exec(mi)
  if (step && h === '*' && dom === '*' && dow === '*') {
    const n = int(step[1], 1, 59)
    return n ? { ...base, kind: 'minutes', every: n } : custom
  }
  const m = int(mi, 0, 59)
  if (m == null) return custom
  const hstep = /^\*\/(\d{1,2})$/.exec(h)
  if (hstep && dom === '*' && dow === '*') {
    const n = int(hstep[1], 1, 23)
    return n ? { ...base, kind: 'hours', every: n, minute: m } : custom
  }
  if (h === '*' && dom === '*' && dow === '*') return { ...base, kind: 'hourly', minute: m }
  const hr = int(h, 0, 23)
  if (hr == null) return custom
  if (dom === '*' && dow === '*') return { ...base, kind: 'daily', minute: m, hour: hr }
  if (dom === '*' && (dow === '1-5' || dow === 'mon-fri')) return { ...base, kind: 'weekdays', minute: m, hour: hr }
  if (dom === '*') {
    const wd = int(dow, 0, 7)
    return wd == null ? custom : { ...base, kind: 'weekly', minute: m, hour: hr, weekday: wd % 7 }
  }
  if (dow === '*') {
    const d = int(dom, 1, 31)
    return d == null ? custom : { ...base, kind: 'monthly', minute: m, hour: hr, day: d }
  }
  return custom
}

export function fromPreset(p: Preset): string | null {
  switch (p.kind) {
    case 'minutes':
      return p.every <= 1 ? '* * * * *' : `*/${p.every} * * * *`
    case 'hours':
      return p.every <= 1 ? `${p.minute} * * * *` : `${p.minute} */${p.every} * * *`
    case 'hourly':
      return `${p.minute} * * * *`
    case 'daily':
      return `${p.minute} ${p.hour} * * *`
    case 'weekdays':
      return `${p.minute} ${p.hour} * * 1-5`
    case 'weekly':
      return `${p.minute} ${p.hour} * * ${p.weekday}`
    case 'monthly':
      return `${p.minute} ${p.hour} ${p.day} * *`
    default:
      return null
  }
}

export const hhmm = (h: number, m: number) => `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`

/** Weekday names in the UI language (0 = Sunday). */
export function weekdayNames(lang: string): string[] {
  const f = new Intl.DateTimeFormat(lang, { weekday: 'long', timeZone: 'UTC' })
  // 2023-01-01 was a Sunday
  return Array.from({ length: 7 }, (_, i) => f.format(new Date(Date.UTC(2023, 0, 1 + i))))
}

/* ------------------------------------------------------------------ timeout */
export type TimeoutUnit = 's' | 'min' | 'h'
export function splitTimeout(s: number): { value: number; unit: TimeoutUnit } {
  if (s >= 3600 && s % 3600 === 0) return { value: s / 3600, unit: 'h' }
  if (s >= 60 && s % 60 === 0) return { value: s / 60, unit: 'min' }
  return { value: s, unit: 's' }
}
export const UNIT_S: Record<TimeoutUnit, number> = { s: 1, min: 60, h: 3600 }
