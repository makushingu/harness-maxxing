// Voice messages API (docs/dev/API.md#voice): status/settings, install job, transcription.
import { useQuery } from '@tanstack/react-query'
import { api, request } from '@/lib/api'
import { useMut } from '@/lib/queries/util'
import { qk } from '@/lib/queries/keys'

export type VoiceEngine = 'off' | 'local' | 'groq' | 'openai'
export type VoiceModel = 'tiny' | 'base' | 'small' | 'medium'
export type VoiceSettings = {
  engine: VoiceEngine
  model: VoiceModel
  language: string
  auto_send: boolean
  /** The mic sends the recording at once; the server transcribes it afterwards (off: transcribe first, to review). */
  direct: boolean
}
export type VoiceInstall = {
  state: 'idle' | 'running' | 'done' | 'error'
  step: 'deps' | 'model' | null
  progress: number | null
  model: VoiceModel | null
  message: string
  error: string | null
  at: number | null
}
export type VoiceStatus = {
  settings: VoiceSettings
  ready: boolean
  reason: 'off' | 'no_ffmpeg' | 'not_installed' | 'no_key' | null
  ffmpeg: boolean
  local: {
    installed: boolean
    loaded: string | null
    recommended: VoiceModel
    ram_gb: number
    cpus: number
    models: { id: VoiceModel; size_mb: number; present: boolean }[]
  }
  keys: { groq: boolean; openai: boolean }
  key_names: { groq: string; openai: string }
  install: VoiceInstall
  max_seconds: number
}
export type Transcript = {
  text: string
  language: string | null
  duration_s: number
  engine: VoiceEngine
  model: string | null
  ms: number
  audio_path: string | null
}

export const voiceKey = ['voice'] as const

/** Polls every second while an install/download is running. */
export function useVoice(enabled = true) {
  return useQuery({
    queryKey: voiceKey,
    queryFn: () => api.get<VoiceStatus>('/api/voice'),
    enabled,
    staleTime: 30_000,
    refetchInterval: (q) => (q.state.data?.install.state === 'running' ? 1000 : false),
  })
}

export function useVoiceSettings() {
  return useMut((b: Partial<VoiceSettings>) => api.put<{ ok: boolean; settings: VoiceSettings }>('/api/voice/settings', b), {
    optimistic: (b) => [{ key: voiceKey, update: (s: VoiceStatus) => ({ ...s, settings: { ...s.settings, ...b } }) }],
    invalidate: [voiceKey],
  })
}

export function useVoiceInstall() {
  return useMut((model?: VoiceModel) => api.post<VoiceInstall>('/api/voice/install', model ? { model } : {}), { invalidate: [voiceKey] })
}

export function useVoiceDeleteModel() {
  return useMut((model: VoiceModel) => api.del<{ ok: boolean }>(`/api/voice/models/${model}`), { invalidate: [voiceKey] })
}

/** Saves an API key in the Keys vault (GROQ_API_KEY / OPENAI_API_KEY). */
export function useSaveVoiceKey() {
  return useMut(
    ({ name, value }: { name: string; value: string }) =>
      api.put<{ ok: boolean }>(`/api/secrets/${encodeURIComponent(name)}`, {
        value,
        note: 'Voice transcription',
      }),
    {
      invalidate: [voiceKey, qk.secrets],
    },
  )
}

export function transcribe(blob: Blob, opts: { path?: string; language?: string; signal?: AbortSignal } = {}) {
  const fd = new FormData()
  const ext = blob.type.includes('mp4') ? 'm4a' : blob.type.includes('ogg') ? 'ogg' : 'webm'
  fd.append('audio', blob, `recording.${ext}`)
  if (opts.path !== undefined) fd.append('path', opts.path)
  if (opts.language) fd.append('language', opts.language)
  return request<Transcript>('/api/voice/transcribe', {
    method: 'POST',
    body: fd,
    signal: opts.signal,
  })
}

export const VOICE_LANGUAGES: { id: string; label: string }[] = [
  { id: 'en', label: 'English' },
  { id: 'fr', label: 'Français' },
  { id: 'es', label: 'Español' },
  { id: 'de', label: 'Deutsch' },
  { id: 'it', label: 'Italiano' },
  { id: 'pt', label: 'Português' },
  { id: 'nl', label: 'Nederlands' },
  { id: 'pl', label: 'Polski' },
  { id: 'ru', label: 'Русский' },
  { id: 'uk', label: 'Українська' },
  { id: 'tr', label: 'Türkçe' },
  { id: 'ar', label: 'العربية' },
  { id: 'ja', label: '日本語' },
  { id: 'zh', label: '中文' },
  { id: 'ko', label: '한국어' },
]
