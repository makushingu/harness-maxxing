// Maxxing mode meter: how well the user and the sessions keep each other busy, over the last 10 minutes.
// A game more than a measure - kept in this browser only, gone on reload.
//   utilisation = share of the time the sessions worked rather than waited for the user (70 %)
//   reactivity  = how fast the user answers a finished session, against a 30 s target (30 %); faster than the
//                 target gives a bonus, so a busy and fast user overflows the bar (capped at 110 %).

const WINDOW_MS = 10 * 60_000
const SAMPLE_MS = 2_000
const TARGET_MS = 30_000
export const SCORE_MAX = 1.1

type Sample = { t: number; running: number; waiting: number }
const samples: Sample[] = []
const delays: { t: number; ms: number }[] = []
const finishedAt = new Map<string, number>()

/** The browser clock went back (NTP, wake from sleep): move what is stored back as much, so no time is
 * counted negative and the next samples are not merged into one taken "in the future". */
function rewind(now: number) {
  let last = Math.max(samples[samples.length - 1]?.t ?? -Infinity, delays[delays.length - 1]?.t ?? -Infinity)
  for (const at of finishedAt.values()) last = Math.max(last, at)
  if (last <= now) return
  const back = last - now
  for (const s of samples) s.t -= back
  for (const d of delays) d.t -= back
  for (const [id, at] of finishedAt) finishedAt.set(id, at - back)
}

function trim(now: number) {
  while (samples.length && samples[0].t < now - WINDOW_MS) samples.shift()
  while (delays.length && delays[0].t < now - WINDOW_MS) delays.shift()
}

/** A session finished its turn (or its plan waits): the clock of the user's answer starts. */
export function onFinished(id: string, now = Date.now()) {
  rewind(now)
  finishedAt.set(id, now)
}

/** The user sent a prompt to a session: how long it waited for them, if it was waiting. */
export function onSent(id: string, now = Date.now()) {
  rewind(now)
  const at = finishedAt.get(id)
  if (at === undefined) return
  finishedAt.delete(id)
  delays.push({ t: now, ms: Math.max(0, now - at) })
  trim(now)
}

/** How many sessions work and how many wait for the user right now (at most one sample every 2 s). */
export function sample(running: number, waiting: number, now = Date.now()) {
  rewind(now)
  const last = samples[samples.length - 1]
  if (last && now - last.t < SAMPLE_MS) {
    last.running = Math.max(last.running, running)
    last.waiting = Math.max(last.waiting, waiting)
    return
  }
  samples.push({ t: now, running, waiting })
  trim(now)
}

export type MaxxingScore = {
  /** 0 to 1.1 (over 1 = overdrive). */
  score: number
  /** 0 to 1, null before any session ran or waited. */
  utilisation: number | null
  /** Mean time the user took to answer a finished session (ms), null before the first answer. */
  delay: number | null
  /** Finished sessions answered in the window. */
  answered: number
}

export function score(now = Date.now()): MaxxingScore {
  rewind(now)
  trim(now)
  let run = 0
  let all = 0
  for (const s of samples) {
    run += s.running
    all += s.running + s.waiting
  }
  const utilisation = all > 0 ? run / all : null
  const delay = delays.length ? delays.reduce((a, d) => a + d.ms, 0) / delays.length : null
  const reactivity = delay === null ? 1 : Math.min(4 / 3, TARGET_MS / Math.max(delay, 1_000))
  const value = utilisation === null ? 0 : Math.min(SCORE_MAX, 0.7 * utilisation + 0.3 * reactivity)
  return { score: value, utilisation, delay, answered: delays.length }
}

/** Tests and Maxxing off: start again from nothing. */
export function resetStats() {
  samples.length = 0
  delays.length = 0
  finishedAt.clear()
}
