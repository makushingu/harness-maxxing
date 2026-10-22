// Video quality (see docs/dev/API.md, /api/files/video): the server makes lighter H.264 copies (1080p / 720p /
// 480p, fast start) one at a time. The choice (Auto / Original / a height) is remembered on this device.
// Auto plays the copy the server suggests (heavy, > 1080p or not H.264 originals) once it is ready, the original
// meanwhile; its copy is made once the video is played (`active`), not for a video only opened. A chosen height not
// ready yet is prepared at once; the player switches to it, at the same time, when done.
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
  qualities: VideoQuality[]
  auto: number | null
}
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

export function useVideoQuality(path: string, enabled: boolean, version?: number | null, active = true) {
  const qc = useQueryClient()
  const [choice, setChoiceState] = React.useState<QualityChoice>(readChoice)
  const key = React.useMemo(() => ['files', 'video', path] as const, [path])
  const info = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => api.get<VideoInfo>('/api/files/video', { path }, { signal }),
    enabled,
    staleTime: 30_000,
    retry: false,
    refetchInterval: (q) => (q.state.data?.qualities.some(busy) ? 1500 : false),
  })
  const target = targetQuality(info.data, choice)
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
  // What plays now: the target copy when ready, else the original.
  const playing = target != null && targetState?.state === 'ready' ? target : null
  const v = version ? String(Math.round(version * 1000)) : undefined
  return {
    info: info.data,
    choice,
    setChoice,
    target,
    targetState,
    playing,
    src: playing != null ? videoStreamUrl(path, playing, v) : null,
  }
}
