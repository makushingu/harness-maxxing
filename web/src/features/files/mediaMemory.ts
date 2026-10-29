// What the players remember in this browser: volume, mute and speed (one set for every player, `mx-media-prefs`),
// and where each audio / video file was left (`mx-media-pos`: path + version -> seconds, the 100 most recent, written
// at most once a second). Opening a file again resumes there, unless it was in the first 3 s or the last 5 s.
// No React here.
import { store } from '@/lib/utils'

export type MediaPrefs = { volume: number; muted: boolean; speed: number }

const PREFS = 'mx-media-prefs'
const POS = 'mx-media-pos'
const MAX = 100
const DEFAULTS: MediaPrefs = { volume: 1, muted: false, speed: 1 }

const num = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n)

export function readPrefs(): MediaPrefs {
  try {
    const p = JSON.parse(store.get(PREFS) || '{}') as Partial<MediaPrefs>
    return {
      volume: num(p.volume) ? Math.max(0, Math.min(1, p.volume)) : DEFAULTS.volume,
      muted: typeof p.muted === 'boolean' ? p.muted : DEFAULTS.muted,
      speed: num(p.speed) && p.speed >= 0.25 && p.speed <= 4 ? p.speed : DEFAULTS.speed,
    }
  } catch {
    return { ...DEFAULTS }
  }
}

export function savePrefs(change: Partial<MediaPrefs>) {
  const next = { ...readPrefs(), ...change }
  store.set(PREFS, JSON.stringify(next))
}

/* ------------------------------------------------------------------ positions */
type Pos = { t: number; at: number }
let cache: Map<string, Pos> | null = null
let timer: ReturnType<typeof setTimeout> | null = null

function load() {
  if (cache) return cache
  cache = new Map()
  try {
    const raw = JSON.parse(store.get(POS) || '{}') as Record<string, Pos>
    const rows = Object.entries(raw).filter(([, v]) => v && num(v.t) && v.t >= 0 && num(v.at))
    rows.sort((a, b) => a[1].at - b[1].at) // oldest first: the Map's order is the eviction order
    for (const [k, v] of rows) cache.set(k, { t: v.t, at: v.at })
  } catch {
    /* unreadable: start empty */
  }
  return cache
}

function write() {
  if (timer) clearTimeout(timer)
  timer = null
  if (cache) store.set(POS, JSON.stringify(Object.fromEntries(cache)))
}

function schedule() {
  timer ??= setTimeout(write, 1000)
}

if (typeof window !== 'undefined') window.addEventListener('pagehide', () => timer && write())

export const mediaPosKey = (path: string, version?: number | null) => `${path}|${version ? Math.round(version * 1000) : ''}`

/** Where to resume this file, or null (never played, or left in its first 3 s / last 5 s). */
export function resumePos(key: string, duration: number): number | null {
  const p = load().get(key)
  if (!p || p.t < 3 || !Number.isFinite(duration) || duration <= 0 || p.t > duration - 5) return null
  return p.t
}

export function setMediaPos(key: string, t: number) {
  if (!num(t)) return
  const m = load()
  m.delete(key)
  m.set(key, { t: Math.round(t * 10) / 10, at: Date.now() })
  while (m.size > MAX) m.delete(m.keys().next().value!)
  schedule()
}

export function clearMediaPos(key: string) {
  if (load().delete(key)) schedule()
}
