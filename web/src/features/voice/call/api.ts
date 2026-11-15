// Voice mode API (docs/dev/API.md#voice-mode): settings and keys, start / end a call, one turn of a local call.
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
}
export type CallStatus = {
  settings: CallSettings
  /** The provider used in cloud mode: chosen, else the only one with a key. */
  provider: CallProvider | null
  keys: Record<CallProvider, { found: string[]; using: string | null }>
  local: { ready: boolean; reason: 'stt' | 'tts' | null; tts: { ready: boolean; voices: string[]; catalogue: string[]; install: { state: string; error?: string | null } } }
  cloud: { ready: boolean; reason: 'choose' | 'choose_key' | 'no_key' | null }
  ready: boolean
  voices: { openai: string[]; gemini: string[]; local: string[] }
}
export type CallStart =
  | { mode: 'local'; call: string }
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

export const startCall = (session: string) => api.post<CallStart>('/api/voice/call/start', { session })
export const endCall = (call: string) => api.post(`/api/voice/call/${call}/end`, {}).catch(() => {})

export type TurnLine = { heard?: string; action?: { type: 'ask'; request: string } | { type: 'stop' }; say?: string; url?: string; seconds?: number; error?: string; code?: string; done?: boolean; empty?: boolean }

/** One turn of a local call: POST, then the NDJSON lines as they come. */
export async function* callTurn(call: string, body: { audio?: Blob; text?: string; event?: string; context?: string }, signal: AbortSignal): AsyncGenerator<TurnLine> {
  const fd = new FormData()
  if (body.audio) fd.append('audio', body.audio, 'turn.wav')
  if (body.text) fd.append('text', body.text)
  if (body.event) fd.append('event', body.event)
  if (body.context) fd.append('context', body.context)
  const r = await fetch(`/api/voice/call/${call}/turn`, { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-Maxxing': '1' }, signal })
  if (!r.ok || !r.body) {
    let msg = `HTTP ${r.status}`
    try {
      const j = await r.json()
      msg = j?.detail?.message || j?.detail || msg
    } catch {
      /* not JSON */
    }
    throw new Error(String(msg))
  }
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
