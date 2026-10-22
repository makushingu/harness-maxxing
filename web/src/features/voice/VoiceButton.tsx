// Composer mic button. Tap = start, tap again = stop; long-press = push-to-talk (release to stop,
// slide left to cancel); Esc / ✕ cancels. With the "send right away" setting (default) the recording goes to
// `onVoiceMessage` as it is (sent like a voice note, the server transcribes it); otherwise it is transcribed here
// and the transcript is handed to `onTranscript` (inserted at the cursor for review, or sent with "send automatically").
// While recording/transcribing, an overlay covers the composer card (the card must be `relative`).
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Check, Mic, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT, type TFn } from '@/i18n'
import { errorMessage, isApiError } from '@/lib/api'
import { Button, Spinner, Tooltip, TooltipContent, TooltipRoot, TooltipTrigger, toast } from '@/components/ui'
import { transcribe, useVoice } from './api'
import { MicError, fmtClock, micUnavailable, useRecorder } from './recorder'

const HOLD_MS = 350 // a press longer than this is push-to-talk
const CANCEL_SLIDE_PX = 80 // slide left while holding = cancel

/** The recording as a file named like a voice note (voice-YYYYMMDD-HHMMSS.webm), in the topic's attachments. */
function voiceFile(blob: Blob): File {
  const type = blob.type || 'audio/webm'
  const ext = type.includes('mp4') || type.includes('aac') ? 'm4a' : type.includes('ogg') ? 'ogg' : type.includes('wav') ? 'wav' : 'webm'
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  const stamp = `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
  return new File([blob], `voice-${stamp}.${ext}`, { type: type.split(';')[0] })
}

export function micErrorText(t: TFn, e: unknown): string {
  if (e instanceof MicError) {
    if (e.kind === 'insecure') return t('voice.err.insecure')
    if (e.kind === 'unsupported') return t('voice.err.unsupported')
    if (e.kind === 'denied') return t('voice.err.denied')
    if (e.kind === 'no_device') return t('voice.err.noDevice')
    return t('voice.err.mic')
  }
  if (isApiError(e, 'empty_audio')) return t('voice.err.empty')
  if (isApiError(e, 'too_long')) return t('voice.err.tooLong')
  return errorMessage(e)
}

export function VoiceButton({
  onTranscript,
  onVoiceMessage,
  disabled,
}: {
  onTranscript: (text: string, autoSend: boolean) => void
  onVoiceMessage?: (file: File) => void
  disabled?: boolean
}) {
  const t = useT()
  const navigate = useNavigate()
  const { data: voice } = useVoice()
  const [phase, setPhase] = React.useState<'idle' | 'transcribing'>('idle')
  const [ptt, setPtt] = React.useState(false)
  const [slide, setSlide] = React.useState(0)
  const abort = React.useRef<AbortController | null>(null)
  const press = React.useRef<{ at: number; x: number; id: number } | null>(null)
  const finishRef = React.useRef<() => void>(() => {})
  const rec = useRecorder({
    maxSeconds: voice?.max_seconds ?? 900,
    onLimit: () => finishRef.current(),
  })
  const active = rec.state !== 'idle' || phase === 'transcribing'

  const finish = React.useCallback(async () => {
    setPtt(false)
    setSlide(0)
    const blob = await rec.stop()
    if (!blob) return
    if (blob.size < 1200) {
      toast.info(t('voice.tooShort'))
      return
    }
    if (onVoiceMessage && voice?.settings.direct !== false) {
      onVoiceMessage(voiceFile(blob))
      return
    }
    setPhase('transcribing')
    const ctrl = new AbortController()
    abort.current = ctrl
    try {
      const out = await transcribe(blob, { signal: ctrl.signal })
      const text = out.text.trim()
      if (!text) toast.info(t('voice.noSpeech'))
      else onTranscript(text, !!voice?.settings.auto_send)
    } catch (e) {
      if ((e as Error)?.name !== 'AbortError') toast.error(t('voice.failed'), micErrorText(t, e))
    } finally {
      abort.current = null
      setPhase('idle')
    }
  }, [rec, onTranscript, onVoiceMessage, voice?.settings.auto_send, voice?.settings.direct, t])
  finishRef.current = finish

  const cancel = React.useCallback(() => {
    press.current = null
    setPtt(false)
    setSlide(0)
    abort.current?.abort()
    rec.cancel()
  }, [rec])

  React.useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        cancel()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, cancel])

  const begin = async () => {
    try {
      await rec.start()
    } catch (e) {
      press.current = null
      setPtt(false)
      toast.error(t('voice.micError'), micErrorText(t, e))
    }
  }

  // Engine off / not ready: muted button that leads to the settings.
  if (!voice) return null
  if (!voice.ready) {
    const hint = voice.reason === 'off' ? t('voice.offHint') : t('voice.notReadyHint')
    return (
      <Tooltip content={hint}>
        <Button variant="ghost" size="icon-sm" aria-label={hint} className="text-muted-foreground/60" onClick={() => navigate('/settings/voice')}>
          <Mic />
        </Button>
      </Tooltip>
    )
  }

  const onPointerDown = (e: React.PointerEvent<HTMLButtonElement>) => {
    if (e.button !== 0 || disabled || phase === 'transcribing') return
    if (rec.state === 'recording') return // second tap → handled on pointerup
    const problem = micUnavailable()
    if (problem) {
      toast.error(t('voice.micError'), micErrorText(t, new MicError(problem)))
      return
    }
    e.currentTarget.setPointerCapture?.(e.pointerId)
    press.current = { at: performance.now(), x: e.clientX, id: e.pointerId }
    void begin()
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const p = press.current
    if (!p || p.id !== e.pointerId) return
    if (!ptt && performance.now() - p.at > HOLD_MS) setPtt(true)
    const dx = Math.min(0, e.clientX - p.x)
    setSlide(dx)
    if (dx < -CANCEL_SLIDE_PX) cancel()
  }
  const onPointerUp = (e: React.PointerEvent) => {
    const p = press.current
    press.current = null
    if (!p) {
      if (rec.state === 'recording') void finish() // tap mode: second tap stops
      return
    }
    if (p.id !== e.pointerId) return
    const held = performance.now() - p.at
    if (held > HOLD_MS && rec.state === 'recording')
      void finish() // push-to-talk release
    else setPtt(false) // short tap: keep recording
  }

  return (
    <>
      {/* Same element for the whole press (a remount would lose the pointer capture of push-to-talk). */}
      <TooltipRoot open={active ? false : undefined}>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={rec.state === 'recording' ? t('voice.stop') : t('voice.record')}
            aria-pressed={rec.state === 'recording'}
            disabled={disabled}
            data-voice-button
            className={cn('touch-none select-none [-webkit-touch-callout:none] max-md:size-11 max-md:rounded-full max-md:bg-accent max-md:[&_svg]:size-5', rec.state === 'recording' && 'text-destructive')}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={() => ptt && cancel()}
            onContextMenu={(e) => e.preventDefault()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                if (rec.state === 'recording') void finish()
                else if (rec.state === 'idle' && phase === 'idle') void begin()
              }
            }}
          >
            <Mic />
          </Button>
        </TooltipTrigger>
        <TooltipContent>{t('voice.record')}</TooltipContent>
      </TooltipRoot>
      {active && (
        <RecordingBar
          transcribing={phase === 'transcribing'}
          starting={rec.state === 'starting'}
          elapsed={rec.elapsed}
          level={rec.level}
          ptt={ptt}
          slide={slide}
          onCancel={cancel}
          onStop={() => void finish()}
        />
      )}
    </>
  )
}

/** Overlay shown over the composer card while recording / transcribing. */
function RecordingBar({
  transcribing,
  starting,
  elapsed,
  level,
  ptt,
  slide,
  onCancel,
  onStop,
}: {
  transcribing: boolean
  starting: boolean
  elapsed: number
  level: number
  ptt: boolean
  slide: number
  onCancel: () => void
  onStop: () => void
}) {
  const t = useT()
  return (
    <div
      role="status"
      aria-live="polite"
      data-voice-overlay
      className="absolute inset-0 z-10 flex items-center gap-2 rounded-[inherit] bg-card/95 px-2"
      style={ptt && slide ? { transform: `translateX(${Math.max(slide, -60) / 3}px)` } : undefined}
    >
      <Tooltip content={t('voice.cancel')}>
        <Button variant="ghost" size="icon-sm" aria-label={t('voice.cancel')} onClick={onCancel}>
          <X />
        </Button>
      </Tooltip>
      {transcribing ? (
        <span className="flex min-w-0 flex-1 items-center gap-2 text-sm text-muted-foreground">
          <Spinner className="size-4" /> {t('voice.transcribing')}
        </span>
      ) : (
        <>
          <span className={cn('size-2.5 shrink-0 rounded-full', starting ? 'bg-muted-foreground/40' : 'animate-pulse bg-destructive')} aria-hidden />
          <span className="w-12 shrink-0 text-sm font-medium tabular-nums" data-voice-timer>
            {starting ? '…' : fmtClock(elapsed)}
          </span>
          <LevelMeter level={level} />
          <span className="min-w-0 flex-1 truncate text-[12px] text-muted-foreground max-sm:hidden">
            {starting ? t('voice.allowMic') : ptt ? t('voice.releaseHint') : t('voice.tapHint')}
          </span>
        </>
      )}
      {!transcribing && (
        <Tooltip content={t('voice.stop')}>
          <Button size="icon-sm" className="ml-auto rounded-lg" aria-label={t('voice.stop')} onClick={onStop} disabled={starting}>
            <Check />
          </Button>
        </Tooltip>
      )}
    </div>
  )
}

const BARS = 12
export function LevelMeter({ level, className }: { level: number; className?: string }) {
  // Rolling history of levels → a small waveform.
  const hist = React.useRef<number[]>(Array(BARS).fill(0))
  hist.current = [...hist.current.slice(1), level]
  return (
    <span className={cn('flex h-6 shrink-0 items-center gap-[3px]', className)} aria-hidden data-voice-level={level.toFixed(2)}>
      {hist.current.map((v, i) => (
        <span key={i} className="w-[3px] rounded-full bg-primary/80 transition-[height] duration-75" style={{ height: `${Math.max(3, Math.round(v * 24))}px` }} />
      ))}
    </span>
  )
}
