// Voice mode of a session: a call with a voice (local, OpenAI or Gemini: Settings -> Voice -> Voice mode) that talks
// with the user while this session does the work. The voice's tools act on the session through the same paths as the
// composer (send, stop), and the end of each turn is told to the voice, which says the outcome.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { AudioLines, PhoneOff } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { errorMessage } from '@/lib/api'
import { Button, Tooltip, toast } from '@/components/ui'
import { getLog, useLogSelect } from '@/pages/sessions/log'
import { useUI } from '@/stores/ui'
import { endCall, startCall, useCallStatus } from './call/api'
import { LocalVoice } from './call/local'
import { GeminiVoice } from './call/gemini'
import { OpenAIVoice } from './call/openai'
import type { Brain, CallPhase, Voice } from './call/types'
import { LevelMeter } from './VoiceButton'

type Props = {
  sid: string
  running: boolean
  queueCount: number
  onSend: (text: string, attachments: string[]) => Promise<boolean>
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

const secs = (at: number) => (at > 1e12 ? at / 1000 : at)

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

export function VoiceCall({ sid, running, queueCount, onSend, onStop }: Props) {
  const t = useT()
  const navigate = useNavigate()
  const { data: st } = useCallStatus()
  const [phase, setPhase] = React.useState<CallPhase | 'off'>('off')
  const [level, setLevel] = React.useState(0)
  const [caption, setCaption] = React.useState<{ who: 'you' | 'voice'; text: string } | null>(null)
  const voice = React.useRef<Voice | null>(null)
  const callId = React.useRef<string | null>(null)
  const live = React.useRef({ running, queueCount, onSend, onStop })
  live.current = { running, queueCount, onSend, onStop }
  const resultKey = useLogSelect(sid, lastResultKey)
  const seenKey = React.useRef(resultKey)

  const hangUp = React.useCallback(() => {
    voice.current?.close()
    voice.current = null
    if (callId.current) void endCall(callId.current)
    callId.current = null
    setPhase('off')
    setCaption(null)
    setLevel(0)
  }, [])

  React.useEffect(() => hangUp, [hangUp, sid])

  // A turn of the session ended during the call: the voice tells its outcome.
  React.useEffect(() => {
    if (resultKey === seenKey.current) return
    seenKey.current = resultKey
    if (!voice.current || !resultKey) return
    const answer = lastAnswer(sid)
    voice.current.notify(answer || '(the session ended its turn without a written answer)')
  }, [resultKey, sid])

  if (!st) return null

  const brain: Brain = {
    ask: async (request) => {
      if (!request.trim()) return 'Nothing to send.'
      const busy = live.current.running
      const ok = await live.current.onSend(request.trim(), []).catch(() => false)
      if (!ok) return 'The message could not be sent to the session.'
      return busy ? 'Queued: the session is busy and will do it right after its current work.' : 'Sent: the session is working on it.'
    },
    status: () => sessionLine(sid, live.current.running, live.current.queueCount),
    stop: async () => {
      if (!live.current.running) return 'The session was not working.'
      live.current.onStop?.()
      return 'Stopped.'
    },
    lastAnswer: () => lastAnswer(sid).slice(0, 6000),
  }

  const start = async () => {
    if (!st.ready) {
      toast.info(t('vmode.notReady'))
      navigate('/settings/voice')
      return
    }
    setPhase('connecting')
    seenKey.current = resultKey
    try {
      const c = await startCall(sid, useUI.getState().language)
      const events = {
        phase: (p: CallPhase) => setPhase((cur) => (cur === 'off' ? cur : p)),
        caption: (who: 'you' | 'voice', text: string) => setCaption({ who, text }),
        error: (m: string) => toast.error(t('vmode.failed'), m),
        level: (l: number) => setLevel(l),
      }
      let v: Voice
      if (c.mode === 'local') {
        callId.current = c.call
        v = new LocalVoice(c.call, brain, events)
      } else v = c.provider === 'gemini' ? new GeminiVoice(c, brain, events) : new OpenAIVoice(c, brain, events)
      voice.current = v
      await v.start()
    } catch (e) {
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
