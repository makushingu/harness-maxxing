// Voice mode of a session: a call (voice: local, OpenAI or Gemini, Settings -> Voice -> Voice mode). The voice talks
// with the user and hands real work to this session in the user's own words (a message of the composer, marked as
// said on a call; while it works, the message joins the running turn); the end of each turn is read out by the
// voice, and news of a long one is said now and then.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { AudioLines, PhoneOff } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { api, errorMessage } from '@/lib/api'
import { Button, Tooltip, toast } from '@/components/ui'
import { getLog, useLogSelect, useSessionStream } from '@/pages/sessions/log'
import { useUI } from '@/stores/ui'
import { endCall, startCall, useCallStatus } from './call/api'
import { LocalVoice } from './call/local'
import { GeminiVoice } from './call/gemini'
import { OpenAIVoice } from './call/openai'
import { chimeOff, chimeOn, unlockChime } from './call/chime'
import type { Brain, CallPhase, Outcome, Voice } from './call/types'
import { LevelMeter } from './VoiceButton'

type Props = {
  /** The session the call talks to ('' while there is none yet: an agent's first message creates it). */
  sid: string
  /** What the call belongs to (one call each; it hangs up when this changes): the session, or `agent:<path>`. */
  callKey?: string
  /** The page does not follow the session's log by itself (an agent's page): the call does. */
  stream?: boolean
  running: boolean
  queueCount: number
  /** `call`: the call's language (Claude is told it is on the phone). */
  onSend: (text: string, attachments: string[], call?: string) => Promise<boolean>
  onStop?: () => void
}

/** The answer of the last turn: the assistant messages after the last user message. */
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
  for (let i = st.items.length - 1; i >= 0; i--) if (st.items[i].kind === 'result' || st.items[i].kind === 'note') return st.items[i].key
  return ''
}

/** How the last turn ended: a failure (its card), else its answer, else nothing written. */
function lastOutcome(sid: string, answer: string): Outcome {
  const items = getLog(sid).items
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i]
    if (it.kind === 'result') return it.cut || !it.ev.ok ? 'failed' : answer ? 'answer' : 'done'
    if (it.kind === 'note') return it.cut ? 'failed' : answer ? 'answer' : 'done'
  }
  return answer ? 'answer' : 'done'
}

const secs = (at: number) => (at > 1e12 ? at / 1000 : at)

/** Where the running turn is: its last note (assistant text) and its last tool, and a key that changes with them. */
function progressOf(sid: string): { key: string; note: string; tool: string } {
  const items = getLog(sid).items
  let note = ''
  let tool = ''
  let key = ''
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i]
    if (it.kind === 'user') break
    if (!key) key = it.key
    if (!tool && it.kind === 'tool') tool = it.use.name
    if (!note && !tool && it.kind === 'assistant' && !it.ev.error && it.ev.text) note = it.ev.text
  }
  return { key, note, tool }
}

const PROGRESS_FIRST_MS = 15_000 // quiet for this long while the session works: the voice says what it does
const PROGRESS_EVERY_MS = 25_000

/** One line on the session for the voice: working or not, since when, its last steps, the messages waiting. */
function sessionLine(sid: string, running: boolean, queue: number): string {
  const items = getLog(sid).items
  let start = 0
  const steps: string[] = []
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i]
    if (it.kind === 'user') {
      start = secs(it.ev.at)
      break
    }
    if (it.kind === 'tool' && steps.length < 4) steps.unshift((it.use.summary || it.use.name).slice(0, 120))
  }
  if (!running) return `idle (not working)${queue ? `, ${queue} message(s) waiting` : ''}`
  const since = start ? Math.max(0, Math.round(Date.now() / 1000 - start)) : 0
  return `working for ${since} s${steps.length ? `; last steps: ${steps.join(' | ')}` : '; thinking'}${queue ? `; ${queue} message(s) waiting` : ''}`
}

export function VoiceCall({ sid, callKey, stream, running, queueCount, onSend, onStop }: Props) {
  const t = useT()
  const navigate = useNavigate()
  const { data: st } = useCallStatus()
  const [phase, setPhase] = React.useState<CallPhase | 'off'>('off')
  const [level, setLevel] = React.useState(0)
  const [caption, setCaption] = React.useState<{ who: 'you' | 'voice'; text: string } | null>(null)
  const voice = React.useRef<Voice | null>(null)
  const callId = React.useRef<string | null>(null)
  const attempt = React.useRef(0) // the call being started: a hang up during its start ends that one
  const live = React.useRef({ sid, running, queueCount, onSend, onStop })
  live.current = { sid, running, queueCount, onSend, onStop }
  const key = callKey || sid
  useSessionStream(stream && phase !== 'off' && sid ? sid : null)
  const resultKey = useLogSelect(sid || null, lastResultKey)
  const seenKey = React.useRef(resultKey)
  const seenSid = React.useRef(sid)
  const lastSaid = React.useRef(0) // last time the call did anything but listen
  const progressKey = React.useRef('')
  const progressCount = React.useRef(0)

  const hangUp = React.useCallback(() => {
    attempt.current++
    if (voice.current) chimeOff()
    voice.current?.close()
    voice.current = null
    if (callId.current) void endCall(callId.current)
    callId.current = null
    setPhase('off')
    setCaption(null)
    setLevel(0)
  }, [])

  React.useEffect(() => hangUp, [hangUp, key])

  // While the session works and the call is quiet, the voice says now and then what it does.
  React.useEffect(() => {
    if (phase === 'off') return
    const timer = window.setInterval(() => {
      if (!voice.current || !live.current.running) {
        progressCount.current = 0
        return
      }
      const quiet = Date.now() - lastSaid.current
      if (quiet < (progressCount.current ? PROGRESS_EVERY_MS : PROGRESS_FIRST_MS)) return
      const p = progressOf(sid)
      if (!p.key || p.key === progressKey.current) return
      progressKey.current = p.key
      progressCount.current++
      lastSaid.current = Date.now()
      voice.current.progress(p.note, p.tool)
    }, 3000)
    return () => window.clearInterval(timer)
  }, [phase === 'off', sid]) // eslint-disable-line react-hooks/exhaustive-deps

  // A turn of the session ended during the call: the voice reads it out.
  React.useEffect(() => {
    if (seenSid.current !== sid) {
      // the call moved to another session (an agent's new conversation): only its next ends are read out
      seenSid.current = sid
      seenKey.current = resultKey
      return
    }
    if (resultKey === seenKey.current) return
    seenKey.current = resultKey
    if (!voice.current || !resultKey) return
    const answer = lastAnswer(sid)
    voice.current.notify(answer, lastOutcome(sid, answer))
  }, [resultKey, sid])

  if (!st) return null

  const brain: Brain = {
    ask: async (request, lang) => {
      if (!request.trim()) return 'Nothing to send.'
      const busy = live.current.running
      const ok = await live.current.onSend(request.trim(), [], lang).catch(() => false)
      if (!ok) return 'The message could not be sent to the session.'
      // Talking while it works: the sentence joins the running turn (read at its next step) instead of waiting.
      const sid = live.current.sid
      if (busy && sid) {
        const r = await api.post<{ injected: boolean }>(`/api/sessions/${encodeURIComponent(sid)}/inject`).catch(() => null)
        if (r?.injected) return 'Added to the work in progress.'
      }
      return busy ? 'Queued: the session is busy and will do it right after its current work.' : 'Sent: the session is working on it.'
    },
    busy: () => live.current.running,
    status: () => sessionLine(live.current.sid, live.current.running, live.current.queueCount),
    stop: async () => {
      if (!live.current.running) return 'The session was not working.'
      live.current.onStop?.()
      return 'Stopped.'
    },
    lastAnswer: () => lastAnswer(live.current.sid).slice(0, 6000),
  }

  const start = async () => {
    if (!st.ready) {
      toast.info(t('vmode.notReady'))
      navigate('/settings/voice')
      return
    }
    unlockChime()
    const mine = ++attempt.current
    setPhase('connecting')
    seenKey.current = resultKey
    lastSaid.current = Date.now()
    progressCount.current = 0
    try {
      const ui = useUI.getState().language
      const c = await startCall(key, ui)
      if (attempt.current !== mine) {
        // hung up while it was asked for: the local call already started on the server is ended
        if (c.mode === 'local') void endCall(c.call)
        return
      }
      const events = {
        phase: (p: CallPhase) => {
          if (p !== 'listening') lastSaid.current = Date.now()
          setPhase((cur) => (cur === 'off' ? cur : p))
        },
        caption: (who: 'you' | 'voice', text: string) => setCaption({ who, text }),
        error: (m: string) => toast.error(t('vmode.failed'), m),
        ended: () => {
          if (attempt.current === mine) hangUp()
        },
        level: (l: number) => setLevel(l),
      }
      let v: Voice
      if (c.mode === 'local') {
        callId.current = c.call
        v = new LocalVoice(c.call, c.language, c.silence_ms, brain, events)
      } else {
        const lang = (ui || navigator.language || 'en').split('-')[0].toLowerCase()
        // the provider ends a connection now and then: a new token for the same call
        const renew = async (resume?: string) => {
          const n = await startCall(key, ui, resume ?? '')
          if (n.mode !== 'cloud') throw new Error('The voice settings changed during the call')
          return n
        }
        v = c.provider === 'gemini' ? new GeminiVoice(c, brain, events, lang, renew) : new OpenAIVoice(c, brain, events, lang, renew)
      }
      voice.current = v
      await v.start()
      if (voice.current === v && attempt.current === mine) chimeOn()
    } catch (e) {
      if (attempt.current !== mine) return // hung up meanwhile: nothing failed
      hangUp()
      toast.error(t('vmode.failed'), errorMessage(e))
    }
  }

  if (phase === 'off')
    return (
      <Tooltip content={t('vmode.on')}>
        <Button variant="ghost" size="icon-sm" aria-label={t('vmode.on')} onClick={() => void start()} data-voice-call className="max-md:size-11 max-md:rounded-full">
          <AudioLines />
        </Button>
      </Tooltip>
    )

  const label = t(`vmode.${phase === 'listening' && running ? 'working' : phase}` as 'vmode.listening')
  const tip = caption ? `${caption.who === 'you' ? t('vmode.you') : t('vmode.voice')} : ${caption.text}` : label
  return (
    <span className="flex min-w-0 items-center gap-0.5 rounded-full border border-primary/40 bg-primary/10 pl-1" data-voice-call={phase}>
      <Tooltip content={tip}>
        <button
          type="button"
          onClick={() => voice.current?.interrupt()}
          className="flex h-6 min-w-0 items-center gap-1.5 rounded-full px-1.5 text-[12px] font-medium text-primary"
          aria-label={phase === 'speaking' ? t('vmode.tapSkip') : label}
        >
          <AudioLines className={cn('size-3.5 shrink-0', (phase === 'speaking' || phase === 'thinking' || phase === 'connecting' || running) && 'animate-pulse')} />
          <span className="max-w-40 truncate">{label}</span>
          {(phase === 'listening' || phase === 'hearing') && <LevelMeter level={level} className="h-4 max-sm:hidden" />}
        </button>
      </Tooltip>
      <Tooltip content={t('vmode.off')}>
        <Button variant="ghost" size="icon-sm" aria-label={t('vmode.off')} onClick={hangUp} className="size-6 rounded-full text-destructive">
          <PhoneOff className="size-3.5" />
        </Button>
      </Tooltip>
    </span>
  )
}
