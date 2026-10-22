// Microphone recorder: MediaRecorder (opus/webm, mp4 on Safari) + live level meter + timer.
import * as React from 'react'

export type RecorderState = 'idle' | 'starting' | 'recording'
export type MicProblem = 'insecure' | 'unsupported' | 'denied' | 'no_device' | 'failed'

export class MicError extends Error {
  kind: MicProblem
  constructor(kind: MicProblem, message?: string) {
    super(message || kind)
    this.kind = kind
  }
}

/** Why recording cannot work in this browser (null = it can). */
export function micUnavailable(): MicProblem | null {
  if (typeof window === 'undefined') return 'unsupported'
  if (!window.isSecureContext) return 'insecure'
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') return 'unsupported'
  return null
}

function pickMime(): string {
  const prefs = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4;codecs=mp4a.40.2', 'audio/mp4', 'audio/aac']
  for (const m of prefs) {
    try {
      if (MediaRecorder.isTypeSupported(m)) return m
    } catch {
      /* old Safari throws */
    }
  }
  return ''
}

/**
 * useRecorder({maxSeconds}) → {state, elapsed, level, start, stop, cancel}.
 * `stop()` resolves to the recorded Blob (null if nothing was captured); `cancel()` discards it.
 * Reaching `maxSeconds` calls `onLimit` (the caller usually stops and transcribes).
 */
export function useRecorder({ maxSeconds = 900, onLimit }: { maxSeconds?: number; onLimit?: () => void } = {}) {
  const [state, setState] = React.useState<RecorderState>('idle')
  const [elapsed, setElapsed] = React.useState(0)
  const [level, setLevel] = React.useState(0)
  const rec = React.useRef<MediaRecorder | null>(null)
  const stream = React.useRef<MediaStream | null>(null)
  const chunks = React.useRef<Blob[]>([])
  const ctx = React.useRef<AudioContext | null>(null)
  const raf = React.useRef(0)
  const timer = React.useRef(0)
  const started = React.useRef(0)
  const onLimitRef = React.useRef(onLimit)
  onLimitRef.current = onLimit
  const stopResolve = React.useRef<((b: Blob | null) => void) | null>(null)
  const cancelled = React.useRef(false)

  const cleanup = React.useCallback(() => {
    cancelAnimationFrame(raf.current)
    window.clearInterval(timer.current)
    stream.current?.getTracks().forEach((tr) => tr.stop())
    stream.current = null
    ctx.current?.close().catch(() => {})
    ctx.current = null
    rec.current = null
    setLevel(0)
    setElapsed(0)
    setState('idle')
  }, [])

  React.useEffect(
    () => () => {
      cancelled.current = true
      try {
        rec.current?.stop()
      } catch {
        /* ignore */
      }
      cleanup()
    },
    [cleanup],
  )

  const start = React.useCallback(async () => {
    const problem = micUnavailable()
    if (problem) throw new MicError(problem)
    if (rec.current) return
    setState('starting')
    cancelled.current = false
    let s: MediaStream
    try {
      s = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
    } catch (e) {
      setState('idle')
      const name = (e as Error)?.name
      throw new MicError(name === 'NotAllowedError' || name === 'SecurityError' ? 'denied' : name === 'NotFoundError' ? 'no_device' : 'failed', (e as Error)?.message)
    }
    if (cancelled.current) {
      s.getTracks().forEach((tr) => tr.stop())
      setState('idle')
      return
    }
    stream.current = s
    const mime = pickMime()
    let r: MediaRecorder
    try {
      r = new MediaRecorder(s, mime ? { mimeType: mime, audioBitsPerSecond: 32000 } : undefined)
    } catch (e) {
      cleanup()
      throw new MicError('failed', (e as Error)?.message)
    }
    chunks.current = []
    r.ondataavailable = (ev) => {
      if (ev.data && ev.data.size) chunks.current.push(ev.data)
    }
    r.onstop = () => {
      const type = r.mimeType || mime || 'audio/webm'
      const blob = chunks.current.length ? new Blob(chunks.current, { type }) : null
      chunks.current = []
      const res = stopResolve.current
      stopResolve.current = null
      cleanup()
      res?.(cancelled.current ? null : blob)
    }
    rec.current = r
    r.start(250)
    started.current = performance.now()
    setElapsed(0)
    setState('recording')
    timer.current = window.setInterval(() => {
      const sec = (performance.now() - started.current) / 1000
      setElapsed(sec)
      if (sec >= maxSeconds) onLimitRef.current?.()
    }, 200)
    // Level meter (RMS of the waveform), ~20 fps.
    try {
      const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      const ac = new AC()
      ctx.current = ac
      const an = ac.createAnalyser()
      an.fftSize = 512
      ac.createMediaStreamSource(s).connect(an)
      const buf = new Uint8Array(an.fftSize)
      let last = 0
      const tick = (now: number) => {
        raf.current = requestAnimationFrame(tick)
        if (now - last < 50) return
        last = now
        an.getByteTimeDomainData(buf)
        let sum = 0
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128
          sum += v * v
        }
        setLevel(Math.min(1, Math.sqrt(sum / buf.length) * 4))
      }
      raf.current = requestAnimationFrame(tick)
    } catch {
      /* no meter: recording still works */
    }
  }, [cleanup, maxSeconds])

  const stop = React.useCallback(
    () =>
      new Promise<Blob | null>((resolve) => {
        const r = rec.current
        if (!r || r.state === 'inactive') {
          cancelled.current = true // a start() still waiting for permission is aborted
          cleanup()
          resolve(null)
          return
        }
        stopResolve.current = resolve
        try {
          r.requestData()
        } catch {
          /* ignore */
        }
        r.stop()
      }),
    [cleanup],
  )

  const cancel = React.useCallback(() => {
    cancelled.current = true
    const r = rec.current
    if (r && r.state !== 'inactive') r.stop()
    else cleanup()
  }, [cleanup])

  return { state, elapsed, level, start, stop, cancel }
}

export function fmtClock(sec: number): string {
  const s = Math.floor(sec)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
