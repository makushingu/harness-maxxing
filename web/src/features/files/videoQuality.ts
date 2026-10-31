// Video quality (see docs/dev/API.md, /api/files/video): the server makes lighter H.264 copies (1080p / 720p /
// 480p, fast start) one at a time. The choice (Auto / Original / a height) is remembered on this device.
// Auto plays the sharpest version this connection carries (autoPick): the ORIGINAL when the browser decodes it
// (canDecode: canPlayType with the codec the server read) and the measured speed (netSpeed.ts) is enough or unknown,
// else the first copy light enough. Each stall lowers a ceiling (`cap`, set by the player) below the source playing,
// so Auto steps down one version at a time, to 480p. A copy is made once the video is played (`active`), never for a
// video only opened; until it is ready the nearest ready copy plays (else the original). A chosen quality not ready
// yet is prepared at once; the player switches to it when done.
import * as React from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, withQuery } from '@/lib/api'

export type VideoQualityState = 'none' | 'queued' | 'running' | 'ready' | 'error'
export interface VideoQuality {
  q: number
  state: VideoQualityState
  progress: number
  error?: string
  /** Revision of the copy's name: in its URL, so a copy made again is never read from the browser's cache. */
  rev?: string
  /** Ready copies: their real bitrate (bits per second). */
  bitrate?: number
}
export interface VideoInfo {
  width: number
  height: number
  codec: string
  bitrate: number
  duration: number
  fps: number
  /** false: no sound at all (a short silent clip plays like a GIF). */
  has_audio?: boolean
  /** 90 / 270: shown sideways (phone videos), width and height are as coded. */
  rotation?: number
  qualities: VideoQuality[]
  auto: number | null
}

/** Width / height as shown (rotation applied). */
export const shownSize = (i: VideoInfo) => (i.rotation === 90 || i.rotation === 270 ? { w: i.height, h: i.width } : { w: i.width, h: i.height })
/** What "1080p" means: the short side (a vertical 1080x1920 video is 1080p, not 1920p). */
export const shortSide = (i: VideoInfo) => (i.width ? Math.min(i.width, i.height) : i.height)

/** A short clip without sound: played like a GIF (muted, looped, no resume). */
export const gifLike = (i: VideoInfo | undefined) => !!i && i.has_audio === false && i.duration > 0 && i.duration <= 15

// codecs= strings canPlayType understands for the codecs ffprobe names (a common profile of each)
const CODECS: Record<string, string> = {
  h264: 'avc1.640028',
  hevc: 'hvc1.1.6.L120.90',
  vp8: 'vp8',
  vp9: 'vp09.00.40.08',
  av1: 'av01.0.08M.08',
  mpeg4: 'mp4v.20.9',
}

/** Can this browser decode the original? false = no (Auto goes straight to the copy), true = it says so (a format
 *  error while playing still falls back on the copy), null = unknown yet. */
export function canDecode(info: VideoInfo | undefined, path: string): boolean | null {
  if (!info || typeof document === 'undefined') return null
  const codec = CODECS[info.codec]
  if (!codec) return false // ProRes, MJPEG, Windows Media...: never played by a browser
  const ext = path.slice(path.lastIndexOf('.') + 1).toLowerCase()
  const v = document.createElement('video')
  const can = (type: string) => v.canPlayType(`${type}; codecs="${codec}"`) !== ''
  if (ext === 'webm') return can('video/webm')
  if (ext === 'avi') return false
  // Matroska: Chromium and Firefox read it (they answer for WebM, its subset), Safari does not
  if (ext === 'mkv') return v.canPlayType('video/x-matroska') !== '' || (can('video/webm') && !/^((?!chrome|android).)*safari/i.test(navigator.userAgent))
  return can('video/mp4')
}

export const videoInfoQuery = (path: string) => ({
  queryKey: ['files', 'video', path] as const,
  queryFn: ({ signal }: { signal?: AbortSignal }) => api.get<VideoInfo>('/api/files/video', { path }, { signal }),
  staleTime: 30_000,
  retry: false,
})
/** 'auto' | 'original' | a height. */
export type QualityChoice = 'auto' | 'original' | number

const KEY = 'mx-video-quality'

export function readChoice(): QualityChoice {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'original') return 'original'
    const n = Number(v)
    return n > 0 ? n : 'auto'
  } catch {
    return 'auto'
  }
}
function saveChoice(c: QualityChoice) {
  try {
    localStorage.setItem(KEY, String(c))
  } catch {
    /* private mode */
  }
}

export const videoStreamUrl = (path: string, q: number, v?: string, r?: string) => withQuery('/api/files/video/stream', { path, q, v, r })

// what a copy usually weighs before it is made (crf 20, capped at 8 / 4 / 1.5 Mbit/s): its real bitrate once ready
const TYPICAL_BPS: Record<number, number> = { 1080: 5e6, 720: 2.5e6, 480: 1e6 }

/** Bits per second of the original (q null) or of a copy. */
export function rateOf(info: VideoInfo, q: number | null): number {
  const orig = info.bitrate || 1e7
  if (q == null) return orig
  const c = info.qualities.find((x) => x.q === q)
  return c?.bitrate || Math.min(TYPICAL_BPS[q] ?? orig, orig)
}

/** Auto's pick: the sharpest version within the budget (80 % of the speed, under the stall ceiling `cap`); null = the
 *  original. Nothing known (no speed, no stall): the original when decodable, else the server's suggestion (or the
 *  sharpest copy: an H.264 .avi needs one too). */
export function autoPick(info: VideoInfo, decodable: boolean, speed: number | null, cap: number): number | null {
  const copies = info.qualities.map((q) => q.q)
  const options: (number | null)[] = decodable ? [null, ...copies] : copies
  if (!options.length) return null
  const budget = Math.min(speed != null ? speed * 0.8 : Infinity, cap) // 0 = measured during a stall, not unknown
  if (budget === Infinity) return decodable ? null : (info.auto ?? copies[0] ?? null)
  return options.find((o) => rateOf(info, o) <= budget) ?? options[options.length - 1]!
}

const busy = (q?: VideoQuality) => q?.state === 'queued' || q?.state === 'running'

/** The height to play for a choice: a chosen height falls back to the closest offered one (a 720p video has no
 *  1080p copy). null = the original. */
export function targetQuality(info: VideoInfo | undefined, choice: QualityChoice): number | null {
  if (!info || choice === 'original') return null
  if (choice === 'auto') return info.auto
  const offered = info.qualities.map((q) => q.q)
  if (!offered.length || choice >= shortSide(info)) return null
  return offered.reduce((best, q) => (Math.abs(q - choice) < Math.abs(best - choice) ? q : best), offered[0]!)
}

/** `decodable`: this browser plays the original (else even "Original" falls back on Auto's pick); `speed`: bits per
 *  second (netSpeed); `cap`: the ceiling the player lowers on each stall. */
export function useVideoQuality(path: string, enabled: boolean, version?: number | null, active = true, decodable = true, speed: number | null = null, cap = Infinity) {
  const qc = useQueryClient()
  const [choice, setChoiceState] = React.useState<QualityChoice>(readChoice)
  const key = React.useMemo(() => ['files', 'video', path] as const, [path])
  const info = useQuery({
    ...videoInfoQuery(path),
    enabled,
    refetchInterval: (q) => (q.state.data?.qualities.some(busy) ? 1500 : false),
  })
  const d = info.data
  const auto = d ? autoPick(d, decodable, speed, cap) : null
  const target = choice === 'auto' ? auto : (targetQuality(d, choice) ?? (decodable ? null : auto))
  const targetState = d?.qualities.find((q) => q.q === target)
  const asked = React.useRef(new Set<number>())
  const again = React.useRef(new Set<number>()) // picked again by hand after an error: ask once more

  const prepare = React.useCallback(
    async (q: number) => {
      asked.current.add(q)
      try {
        qc.setQueryData(key, await api.post<VideoInfo>('/api/files/video/prepare', { path, q }))
      } catch {
        // refused (queue full, no ffmpeg): asked again a bit later, not in a loop
        setTimeout(() => {
          asked.current.delete(q)
          void qc.invalidateQueries({ queryKey: key })
        }, 15_000)
      }
    },
    [qc, key, path],
  )
  // A copy that was queued, running or ready and is "none" again (the server restarted, the cache dropped it): it
  // may be asked again.
  const seen = React.useRef(new Map<number, VideoQualityState>())
  React.useEffect(() => {
    for (const q of d?.qualities ?? []) {
      if (q.state === 'none' && seen.current.get(q.q) && seen.current.get(q.q) !== 'none') asked.current.delete(q.q)
      seen.current.set(q.q, q.state)
    }
  }, [d])
  // The wanted copy is missing: make it (once per player; an error is not retried in a loop, only when picked again).
  React.useEffect(() => {
    if (target == null || !(active || choice !== 'auto')) return
    const st = targetState?.state
    if (st === 'error' && again.current.delete(target)) void prepare(target)
    else if (st === 'none' && !asked.current.has(target)) void prepare(target)
  }, [target, targetState?.state, prepare, active, choice])

  const setChoice = (c: QualityChoice) => {
    if (typeof c === 'number') again.current.add(c)
    setChoiceState(c)
    saveChoice(c)
  }
  /** The copy could not be played (removed from the cache since): ask its state again and make it again if gone. */
  const retry = React.useCallback(
    (q: number) => {
      asked.current.delete(q)
      void qc.invalidateQueries({ queryKey: key })
    },
    [qc, key],
  )
  // What plays now: the target copy when ready. Else, for Auto, the nearest ready copy (a lighter one first: the
  // connection asked for less), and the original when none is ready; a quality picked by hand waits on the original.
  const ready = (d?.qualities ?? []).filter((q) => q.state === 'ready').map((q) => q.q)
  let playing: number | null = null
  if (target != null && ready.includes(target)) playing = target
  else if (target != null && (choice === 'auto' || !decodable)) {
    const lighter = ready.filter((q) => q < target)
    const heavier = ready.filter((q) => q > target)
    playing = lighter.length ? Math.max(...lighter) : heavier.length ? Math.min(...heavier) : null
  }
  const playingRev = d?.qualities.find((q) => q.q === playing)?.rev
  const v = version ? String(Math.round(version * 1000)) : undefined
  return {
    info: info.data,
    /** Auto's pick now (null = the original). */
    auto,
    retry,
    choice,
    setChoice,
    target,
    targetState,
    playing,
    src: playing != null ? videoStreamUrl(path, playing, v, playingRev) : null,
  }
}
