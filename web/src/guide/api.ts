// The guide's server state (GET/PUT /api/guide, POST /api/guide/cards): progress + the cards Opus writes.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Use } from './steps'

export type GuidePrompt = { label: string; text: string; topic: string }
export type GuideCard = { status: 'pending' | 'ready' | 'failed'; intro?: string; prompts?: GuidePrompt[]; at: number }
export type GuideContext = {
  case: 'new' | 'import' | 'existing'
  imported: boolean
  topics: number
  sessions: number
  agents: number
  crons: number
  telegram: boolean
  backup: boolean
  pages: Record<string, boolean>
  recommended: Use[]
  default_topic: string | null
}
export type GuideState = {
  offer: boolean
  status: 'running' | 'paused' | 'done' | 'dismissed' | null
  level: 'beginner' | 'intermediate' | null
  mode: 'full' | 'partial' | null
  uses: Use[]
  steps: string[]
  index: number
  done: string[]
  tried: Record<string, { label: string; topic: string }>
  cards: Record<string, GuideCard>
  context?: GuideContext
}
export type GuidePatch = Partial<Pick<GuideState, 'status' | 'level' | 'mode' | 'uses' | 'steps' | 'index' | 'done'>> & {
  tried?: { step: string; label: string; topic: string }
}

const KEY = ['guide'] as const
// The last progress change on its way: cards are asked after it, so the server writes them for the level and the
// tour just chosen (a card asked before the PUT landed would be written for the old ones).
// The poll waits for it too, and only the answer to the latest change is applied (two quick "Next" never step back).
let saving: Promise<unknown> = Promise.resolve()
let seq = 0

/** Polled every 2.5 s while Opus writes a card (the queue lives on the server). */
export function useGuide() {
  const qc = useQueryClient()
  return useQuery({
    queryKey: KEY,
    queryFn: async () => {
      await saving
      const at = seq
      const s = await api.get<GuideState>('/api/guide')
      const old = qc.getQueryData<GuideState>(KEY)
      // a change was made while it was on its way: keep that progress, take the cards
      return at !== seq && old ? { ...old, cards: s.cards } : s
    },
    staleTime: Infinity,
    refetchInterval: (q) => (Object.values(q.state.data?.cards || {}).some((c) => c.status === 'pending') ? 2500 : false),
  })
}

export function useGuideContext(enabled: boolean) {
  return useQuery({ queryKey: [...KEY, 'context'], queryFn: () => api.get<GuideState>('/api/guide', { context: 1 }), enabled, staleTime: 0 })
}

export function useGuideActions() {
  const qc = useQueryClient()
  const set = (s: GuideState) => qc.setQueryData(KEY, (old: GuideState | undefined) => ({ ...old, ...s }))
  return {
    /** Optimistic: the overlay moves at once, the server answer replaces it. */
    patch: (p: GuidePatch) => {
      const { tried, ...rest } = p
      qc.setQueryData(KEY, (old: GuideState | undefined) =>
        old ? { ...old, ...rest, tried: tried ? { ...old.tried, [tried.step]: { label: tried.label, topic: tried.topic } } : old.tried } : old,
      )
      const mine = ++seq
      const req = api.put<GuideState>('/api/guide', p).then(
        (s) => mine === seq && set(s),
        () => qc.invalidateQueries({ queryKey: KEY }),
      )
      saving = req
      return req
    },
    cards: (steps: string[], force = false) =>
      saving
        .then(() => api.post<GuideState>('/api/guide/cards', { steps, force }))
        // only the cards: the progress may have moved since
        .then((s) => qc.setQueryData(KEY, (old: GuideState | undefined) => (old ? { ...old, cards: s.cards } : s)), () => undefined),
    reset: () => {
      seq++
      const req = api.post<GuideState>('/api/guide/reset').then(set)
      saving = req.catch(() => undefined)
      return req
    },
  }
}
