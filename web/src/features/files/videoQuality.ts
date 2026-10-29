// Video quality (see docs/dev/API.md, /api/files/video): the server makes lighter H.264 copies (1080p / 720p /
// 480p, fast start) one at a time. The choice (Auto / Original / a height) is remembered on this device.
// Auto plays the ORIGINAL whenever this browser can decode it (canDecode: canPlayType with the codec the server
// read), sharp as it is. It needs the copy the server suggests (`auto`: 1080p above 1080p, else 720p for a heavy
// original) only when the original cannot be decoded (HEVC, ProRes, AV1 here, or a format error while playing) or
// struggles (`needCopy`, decided by the player); that copy is made once the video is played (`active`), never for a
// video only opened. A chosen height not ready yet is prepared at once; the player switches to it when done.
import * as React from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, withQuery } from '@/lib/api'

export type VideoQualityState = 'none' | 'queued' | 'running' | 'ready' | 'error'
export interface VideoQuality {
  q: number
  state: VideoQualityState
  progress: number
  error?: string
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

export const videoStreamUrl = (path: string, q: number, v?: string) => withQuery('/api/files/video/stream', { path, q, v })

const busy = (q?: VideoQuality) => q?.state === 'queued' || q?.state === 'running'

/** The height to play for a choice: a chosen height falls back to the closest offered one (a 720p video has no
 *  1080p copy). null = the original. */
export function targetQuality(info: VideoInfo | undefined, choice: QualityChoice): number | null {
  if (!info || choice === 'original') return null
  if (choice === 'auto') return info.auto
  const offered = info.qualities.map((q) => q.q)
  if (!offered.length || choice >= info.height) return null
  return offered.reduce((best, q) => (Math.abs(q - choice) < Math.abs(best - choice) ? q : best), offered[0]!)
}

/** `needCopy`: Auto must leave the original (it cannot be decoded or it struggles); `mustLeave`: it cannot be decoded,
 *  so even "Original" falls back on Auto's copy. */
export function useVideoQuality(path: string, enabled: boolean, version?: number | null, active = true, needCopy = false, mustLeave = false) {
  const qc = useQueryClient()
  const [choice, setChoiceState] = React.useState<QualityChoice>(readChoice)
  const key = React.useMemo(() => ['files', 'video', path] as const, [path])
  const info = useQuery({
    ...videoInfoQuery(path),
    enabled,
    refetchInterval: (q) => (q.state.data?.qualities.some(busy) ? 1500 : false),
  })
  const target = choice === 'auto' ? (needCopy ? (info.data?.auto ?? null) : null) : (targetQuality(info.data, choice) ?? (mustLeave ? (info.data?.auto ?? null) : null))
  const targetState = info.data?.qualities.find((q) => q.q === target)
  const asked = React.useRef(new Set<number>())

  const prepare = React.useCallback(
    async (q: number) => {
      asked.current.add(q)
      try {
        qc.setQueryData(key, await api.post<VideoInfo>('/api/files/video/prepare', { path, q }))
      } catch {
        /* reported by the next GET (state "error") or no ffmpeg: the original keeps playing */
      }
    },
    [qc, key, path],
  )
  // The wanted copy is missing: make it (once per player; an error is not retried in a loop).
  React.useEffect(() => {
    if (target != null && targetState?.state === 'none' && !asked.current.has(target) && (active || choice !== 'auto')) void prepare(target)
  }, [target, targetState?.state, prepare, active, choice])

  const setChoice = (c: QualityChoice) => {
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
  // What plays now: the target copy when ready, else the original.
  const playing = target != null && targetState?.state === 'ready' ? target : null
  const v = version ? String(Math.round(version * 1000)) : undefined
  return {
    info: info.data,
    retry,
    choice,
    setChoice,
    target,
    targetState,
    playing,
    src: playing != null ? videoStreamUrl(path, playing, v) : null,
  }
}
