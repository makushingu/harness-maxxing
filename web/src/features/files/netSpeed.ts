// How fast this device downloads from the server, for Auto video quality (videoQuality.ts).
// Measured while a video plays (MediaPlayer: seconds of media gained per second x the source's bitrate). Only a sample
// taken while the buffer runs low is the connection's real speed (the browser then downloads flat out); with a full
// buffer it only fetches what it plays, so that sample is a floor: it clears an older, lower measure but never lowers
// the quality. Kept 30 min per kind of connection (Wi-Fi and 4G differ). Without a
// measure, the browser's own hint (Chromium: navigator.connection.downlink, below its 10 Mbit/s cap) or nothing: Auto then plays the original
// and steps down on the first stall. "Data saver" on = a light connection.

type Conn = { downlink?: number; effectiveType?: string; type?: string; saveData?: boolean }
const conn = (): Conn | undefined => (typeof navigator !== 'undefined' ? (navigator as Navigator & { connection?: Conn }).connection : undefined)

const KEY = 'mx-net-speed'
const KEEP_MS = 30 * 60_000
const SAVE_DATA_BPS = 1.5e6

const kind = () => {
  const c = conn()
  return c ? `${c.type ?? ''}/${c.effectiveType ?? ''}` : ''
}

function stored(): { bps: number; at: number; kind: string; real?: boolean } | null {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || 'null')
    return v && typeof v.bps === 'number' && Date.now() - v.at < KEEP_MS && v.kind === kind() ? v : null
  } catch {
    return null
  }
}

/** Bits per second this device gets from the server, or null when nothing tells (or only a floor is known). */
export function netSpeed(): number | null {
  const c = conn()
  const kept = stored()
  // Chromium caps downlink at 10 Mbit/s: from there it only says "fast", not how fast
  const s = kept ? (kept.real ? kept.bps : null) : c?.downlink && c.downlink < 10 ? c.downlink * 1e6 : null
  return c?.saveData ? Math.min(s ?? SAVE_DATA_BPS, SAVE_DATA_BPS) : s
}

/** A new sample (bits per second). `real`: taken while the buffer ran low (30 % of it goes into the kept measure);
 *  else a floor, kept only when above the measure. */
export function addNetSample(bps: number, real: boolean) {
  if (!(bps >= 0) || !Number.isFinite(bps)) return
  const prev = stored()
  let next: { bps: number; real: boolean }
  if (real) next = { bps: prev?.real ? prev.bps * 0.7 + bps * 0.3 : bps, real: true }
  else if (!prev || bps > prev.bps) next = { bps, real: false }
  else return
  try {
    localStorage.setItem(KEY, JSON.stringify({ bps: Math.round(next.bps), real: next.real, at: Date.now(), kind: kind() }))
  } catch {
    /* private mode */
  }
}
