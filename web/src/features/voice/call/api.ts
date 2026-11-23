// Voice mode API (docs/dev/API.md#voice-mode): settings and keys, start / end a call, hear the user and read the
// session's answers out (local call), sort a sentence (cloud call).
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useMut } from '@/lib/queries/util'
import { qk } from '@/lib/queries/keys'

export type CallProvider = 'openai' | 'gemini'
export type CallSettings = {
  mode: 'local' | 'cloud'
  provider: CallProvider | null
  openai_key: string | null
  gemini_key: string | null
  openai_model: string
  openai_voice: string
  gemini_model: string
  gemini_voice: string
  talker_model: 'haiku' | 'sonnet'
  local_voice: string
  local_speed: number
  silence_ms: number
}
export type CallStatus = {
  settings: CallSettings
  /** The provider used in cloud mode: chosen, else the only one with a key. */
  provider: CallProvider | null
  keys: Record<CallProvider, { found: string[]; using: string | null }>
  local: { ready: boolean; reason: 'stt' | 'tts' | null; tts: { ready: boolean; voices: string[]; catalogue: { id: string; name: string; lang: string }[]; install: { state: string; error?: string | null } } }
  cloud: { ready: boolean; reason: 'choose' | 'choose_key' | 'no_key' | null }
  ready: boolean
  voices: { openai: string[]; gemini: string[]; local: string[] }
  silence_range: [number, number]
}
export type CallStart =
  | { mode: 'local'; call: string; language: string; silence_ms: number }
  | { mode: 'cloud'; provider: CallProvider; token: string; model: string; url: string }

const callKey = ['voice', 'call'] as const

export function useCallStatus(enabled = true) {
  return useQuery({
    queryKey: callKey,
    queryFn: () => api.get<CallStatus>('/api/voice/call'),
    enabled,
    staleTime: 30_000,
    refetchInterval: (q) => (q.state.data?.local.tts.install.state === 'running' ? 1500 : false),
  })
}

export function useCallSettings() {
  return useMut((b: Partial<Omit<CallSettings, 'provider'>> & { provider?: CallProvider | '' }) => api.put<CallStatus>('/api/voice/call/settings', b), {
    invalidate: [callKey],
  })
}

export function useInstallLocalVoice() {
  return useMut((voices?: string[]) => api.post('/api/voice/tts/install', voices ? { voices } : {}), { invalidate: [callKey] })
}

export function useSaveCallKey() {
  return useMut(({ name, value }: { name: string; value: string }) => api.put<{ ok: boolean }>(`/api/secrets/${encodeURIComponent(name)}`, { value, note: 'Voice mode' }), {
    invalidate: [callKey, qk.secrets],
  })
}

/** `resume`: a cloud call reconnecting (Gemini's handle of its last state, '' for OpenAI): a new token, same call. */
export const startCall = (session: string, language?: string, resume?: string) =>
  api.post<CallStart>('/api/voice/call/start', { session, language, resume: resume || undefined })
export const endCall = (call: string) => api.post(`/api/voice/call/${call}/end`, {}).catch(() => {})

export type TurnLine = {
  heard?: string
  /** What the sentence is: "empty" = noise or the voice's own echo (nothing follows), "stop", "lang", "ask". */
  kind?: 'ask' | 'stop' | 'lang' | 'skip' | 'empty'
  language?: string
  /** `request`: the user's own words, to send to the session. */
  action?: { type: 'ask'; request: string } | { type: 'stop' }
  say?: string
  url?: string
  seconds?: number
  error?: string
  code?: string
  done?: boolean
  empty?: boolean
}

/** Cloud call: the same sorting for a sentence transcribed by the provider. */
export const sortSentence = (text: string, language: string, expecting: boolean) =>
  api.post<{ kind: NonNullable<TurnLine['kind']>; language: string }>('/api/voice/call/sort', { text, language, expecting })

async function failure(r: Response): Promise<string> {
  try {
    const j = await r.json()
    return String(j?.message || j?.detail?.message || j?.error || j?.detail || `HTTP ${r.status}`)
  } catch {
    return `HTTP ${r.status}`
  }
}

/** One exchange of a local call (the user's sentence, the end of a turn, news of a turn): the NDJSON lines as
 * they come. */
export async function* callTurn(
  call: string,
  body: { audio?: Blob; text?: string; event?: string; outcome?: string; note?: string; tool?: string; context?: string; busy?: boolean; saying?: string },
  signal: AbortSignal,
): AsyncGenerator<TurnLine> {
  const fd = new FormData()
  if (body.audio) fd.append('audio', body.audio, 'turn.wav')
  if (body.text) fd.append('text', body.text)
  if (body.event !== undefined) fd.append('event', body.event.slice(0, 60000))
  if (body.outcome) fd.append('outcome', body.outcome)
  if (body.note) fd.append('note', body.note.slice(0, 3000))
  if (body.tool) fd.append('tool', body.tool.slice(0, 120))
  if (body.context) fd.append('context', body.context.slice(0, 1000))
  if (body.busy) fd.append('busy', 'true')
  if (body.saying) fd.append('saying', body.saying.slice(0, 2000)) // what the voice was saying: its echo is not the user
  const r = await fetch(`/api/voice/call/${call}/turn`, { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-Maxxing': '1' }, signal })
  if (!r.ok || !r.body) throw new Error(await failure(r))
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += value
    let i
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).trim()
      buf = buf.slice(i + 1)
      if (line) yield JSON.parse(line) as TurnLine
    }
  }
  if (buf.trim()) yield JSON.parse(buf) as TurnLine
}
