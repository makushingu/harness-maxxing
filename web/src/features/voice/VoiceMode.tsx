// Hands-free voice mode of a session (experimental). On: Harness says a short version of each answer (server
// text-to-speech, POST /api/voice/speak), then listens; when the user stops talking (a silence after speech), the
// recording is sent as a voice message (the same path as the mic button), and so on. Tap the chip to skip the
// reading or to send now; ✕ turns the mode off. The microphone is closed while Harness speaks (no echo).
import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { AudioLines, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { api, errorMessage } from '@/lib/api'
import { Button, Tooltip, toast } from '@/components/ui'
import { getLog, useLogSelect } from '@/pages/sessions/log'
import { useVoice } from './api'
import { LevelMeter, micErrorText, voiceFile } from './VoiceButton'
import { useRecorder } from './recorder'

type Phase = 'off' | 'paused' | 'listening' | 'waiting' | 'preparing' | 'speaking'
type TTSStatus = { ready: boolean; voices: string[] }
type Spoken = { text: string; url: string; seconds: number }

/** 0.1 s of silence (WAV): played on the tap that turns the mode on, so the phone lets the answers play later. */
function silentWav(): string {
  const n = 800
  const b = new DataView(new ArrayBuffer(44 + n * 2))
  const w = (o: number, str: string) => [...str].forEach((c, i) => b.setUint8(o + i, c.charCodeAt(0)))
  w(0, 'RIFF'); b.setUint32(4, 36 + n * 2, true); w(8, 'WAVEfmt '); b.setUint32(16, 16, true); b.setUint16(20, 1, true)
  b.setUint16(22, 1, true); b.setUint32(24, 8000, true); b.setUint32(28, 16000, true); b.setUint16(32, 2, true)
  b.setUint16(34, 16, true); w(36, 'data'); b.setUint32(40, n * 2, true)
  return URL.createObjectURL(new Blob([b.buffer], { type: 'audio/wav' }))
}
const START_LEVEL = 0.16 // RecordingBar level (RMS x 4) that counts as speech
const END_SILENCE_MS = 1400
const MIN_SPEECH_MS = 350
const GIVE_UP_MS = 30_000 // no speech at all: pause (tap to listen again)

/** The text of the last answer: the assistant messages after the last user message. */
function lastAnswer(sid: string): string {
  const items = getLog(sid).items
  const parts: string[] = []
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i]
    if (it.kind === 'user') break
    if (it.kind === 'assistant' && !it.ev.error && it.ev.text) parts.unshift(it.ev.text)
  }
  return parts.join('\n\n')
}

const lastResultKey = (st: ReturnType<typeof getLog>) => {
  for (let i = st.items.length - 1; i >= 0; i--) if (st.items[i].kind === 'result') return st.items[i].key
  return ''
}

export function VoiceMode({ sid, running, onSendVoice }: { sid: string; running: boolean; onSendVoice?: (file: File) => Promise<boolean> }) {
  const t = useT()
  const { data: voice } = useVoice()
  const { data: tts } = useQuery({ queryKey: ['voice', 'tts'], queryFn: () => api.get<TTSStatus>('/api/voice/tts'), staleTime: 60_000 })
  const [phase, setPhase] = React.useState<Phase>('off')
  const [said, setSaid] = React.useState('')
  const phaseRef = React.useRef(phase)
  phaseRef.current = phase
  const audio = React.useRef<HTMLAudioElement | null>(null)
  const rec = useRecorder({ maxSeconds: 300, onLimit: () => void sendNow() })
  const vad = React.useRef({ start: 0, speech: 0, quiet: 0, heard: false })
  const resultKey = useLogSelect(sid, lastResultKey)
  const seenKey = React.useRef(resultKey)
  const speakAbort = React.useRef<AbortController | null>(null)

  const stopAudio = () => {
    speakAbort.current?.abort()
    speakAbort.current = null
    const a = audio.current
    if (a) {
      a.onended = null
      a.pause()
    }
  }

  const listen = React.useCallback(async () => {
    stopAudio()
    vad.current = { start: performance.now(), speech: 0, quiet: 0, heard: false }
    setPhase('listening')
    try {
      await rec.start()
    } catch (e) {
      setPhase('paused')
      toast.error(t('voice.micError'), micErrorText(t, e))
    }
  }, [rec, t])

  const sendNow = React.useCallback(async () => {
    const blob = await rec.stop()
    if (!blob || blob.size < 1200 || !vad.current.heard) {
      setPhase('paused')
      return
    }
    setPhase('waiting')
    const ok = onSendVoice ? await onSendVoice(voiceFile(blob)) : false
    if (!ok) setPhase('paused')
  }, [rec, onSendVoice])

  // Silence detection while listening.
  React.useEffect(() => {
    if (phase !== 'listening' || rec.state !== 'recording') return
    const v = vad.current
    const now = performance.now()
    if (rec.level >= START_LEVEL) {
      if (!v.speech) v.speech = now
      if (now - v.speech >= MIN_SPEECH_MS) v.heard = true
      v.quiet = 0
    } else {
      if (!v.heard) v.speech = 0
      if (!v.quiet) v.quiet = now
      if (v.heard && now - v.quiet >= END_SILENCE_MS) void sendNow()
      else if (!v.heard && now - v.start >= GIVE_UP_MS) {
        rec.cancel()
        setPhase('paused')
      }
    }
  }, [rec.level, rec.state, phase, rec, sendNow])

  // A turn ended: say its answer, then listen again.
  React.useEffect(() => {
    if (resultKey === seenKey.current) return
    seenKey.current = resultKey
    if (phaseRef.current === 'off' || !resultKey) return
    const text = lastAnswer(sid)
    if (!text.trim()) {
      if (phaseRef.current === 'waiting') void listen()
      return
    }
    rec.cancel()
    stopAudio()
    const ctrl = new AbortController()
    speakAbort.current = ctrl
    setPhase('preparing')
    api
      .post<Spoken>('/api/voice/speak', { text }, { signal: ctrl.signal })
      .then((r) => {
        if (ctrl.signal.aborted || phaseRef.current === 'off') return
        const a = audio.current || (audio.current = new Audio())
        setSaid(r.text)
        a.src = r.url
        a.onended = () => {
          if (phaseRef.current === 'speaking') void listen()
        }
        setPhase('speaking')
        return a.play()
      })
      .catch((e) => {
        if (ctrl.signal.aborted || (e as Error)?.name === 'AbortError') return
        toast.error(t('vmode.speakFailed'), errorMessage(e))
        if (phaseRef.current !== 'off') void listen()
      })
  }, [resultKey, sid, listen, rec, t])

  // Off when the column goes away.
  React.useEffect(
    () => () => {
      stopAudio()
    },
    [],
  )

  if (!voice?.ready || !tts?.ready || !onSendVoice) return null

  const turnOn = () => {
    // Unlocks audio playback on phones (it must start from a tap).
    const a = audio.current || (audio.current = new Audio())
    a.src = silentWav()
    void a.play().catch(() => {})
    seenKey.current = resultKey
    if (running) setPhase('waiting')
    else void listen()
  }
  const turnOff = () => {
    stopAudio()
    rec.cancel()
    setSaid('')
    setPhase('off')
  }
  const tap = () => {
    if (phase === 'off') turnOn()
    else if (phase === 'listening') void sendNow()
    else if (phase === 'speaking' || phase === 'preparing' || phase === 'paused') void listen()
  }

  if (phase === 'off')
    return (
      <Tooltip content={t('vmode.on')}>
        <Button variant="ghost" size="icon-sm" aria-label={t('vmode.on')} onClick={turnOn} data-voice-mode>
          <AudioLines />
        </Button>
      </Tooltip>
    )

  const label =
    phase === 'listening'
      ? t('vmode.listening')
      : phase === 'waiting'
        ? t('vmode.waiting')
        : phase === 'preparing'
          ? t('vmode.preparing')
          : phase === 'speaking'
            ? t('vmode.speaking')
            : t('vmode.paused')
  const hint =
    phase === 'listening' ? t('vmode.tapSend') : phase === 'speaking' || phase === 'preparing' ? t('vmode.tapSkip') : phase === 'paused' ? t('vmode.tapListen') : said || label
  return (
    <span className="flex min-w-0 items-center gap-0.5 rounded-full border border-primary/40 bg-primary/10 pl-1" data-voice-mode={phase}>
      <Tooltip content={phase === 'speaking' && said ? said : hint}>
        <button type="button" onClick={tap} disabled={phase === 'waiting'} className="flex h-6 min-w-0 items-center gap-1.5 rounded-full px-1.5 text-[12px] font-medium text-primary">
          <AudioLines className={cn('size-3.5 shrink-0', (phase === 'speaking' || phase === 'waiting' || phase === 'preparing') && 'animate-pulse')} />
          <span className="truncate">{label}</span>
          {phase === 'listening' && <LevelMeter level={rec.level} className="h-4" />}
        </button>
      </Tooltip>
      <Tooltip content={t('vmode.off')}>
        <Button variant="ghost" size="icon-sm" aria-label={t('vmode.off')} onClick={turnOff} className="size-6 rounded-full">
          <X className="size-3.5" />
        </Button>
      </Tooltip>
    </span>
  )
}
