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
}
export type CallStart =
  | { mode: 'local'; call: string; language: string }
  | { mode: 'cloud'; provider: CallProvider; token: string; model: string; url: string }

export const callKey = ['voice', 'call'] as const

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

export const startCall = (session: string, language?: string) => api.post<CallStart>('/api/voice/call/start', { session, language })
export const endCall = (call: string) => api.post(`/api/voice/call/${call}/end`, {}).catch(() => {})

export type SayLine = { say?: string; url?: string; seconds?: number; error?: string; code?: string; done?: boolean }
/** A sentence of the user, sorted on the server: "ask" = send `text` to the session, "stop" = stop its work,
 * "lang" = the call's language changed, "empty" / "skip" = nothing to do (the voice goes on where it was). */
export type Heard = { text: string; language: string; kind: 'ask' | 'stop' | 'lang' | 'skip' | 'empty'; say?: SayLine }

/** Local call: one sentence of the user (WAV) -> what it is, and the acknowledgement to play at once. */
export async function hear(call: string, audio: Blob, busy: boolean, signal?: AbortSignal): Promise<Heard> {
  const fd = new FormData()
  fd.append('audio', audio, 'turn.wav')
  fd.append('busy', busy ? 'true' : 'false')
  const r = await fetch(`/api/voice/call/${call}/hear`, { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-Maxxing': '1' }, signal })
  if (!r.ok) throw new Error(await failure(r))
  return (await r.json()) as Heard
}

/** Cloud call: the same sorting for a sentence transcribed by the provider. */
export const sortSentence = (text: string, language: string, expecting: boolean) =>
  api.post<{ kind: Heard['kind']; language: string }>('/api/voice/call/sort', { text, language, expecting })

async function failure(r: Response): Promise<string> {
  try {
    const j = await r.json()
    return String(j?.detail?.message || j?.detail || `HTTP ${r.status}`)
  } catch {
    return `HTTP ${r.status}`
  }
}

/** Local call: the session's answer read out, the NDJSON lines as they come. */
export async function* speak(call: string, answer: string, outcome: string, signal: AbortSignal, tool?: string): AsyncGenerator<SayLine> {
  const r = await fetch(`/api/voice/call/${call}/speak`, {
    method: 'POST',
    body: JSON.stringify({ answer: answer.slice(0, 60000), outcome, ...(tool ? { tool: tool.slice(0, 120) } : {}) }),
    credentials: 'same-origin',
    headers: { 'X-Maxxing': '1', 'Content-Type': 'application/json' },
    signal,
  })
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
      if (line) yield JSON.parse(line) as SayLine
    }
  }
  if (buf.trim()) yield JSON.parse(buf) as SayLine
}
