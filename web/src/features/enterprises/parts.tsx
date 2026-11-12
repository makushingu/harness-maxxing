// Building blocks shared by the Enterprises pages: the state of a position, the tree of the chart, the "off" page.
import { Link } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { Building2, Settings2 } from 'lucide-react'
import { useT, type TKey } from '@/i18n'
import { errorMessage, isApiError } from '@/lib/api'
import { entKeys, usePatchPosition, useSettings } from '@/lib/queries'
import type { Enterprise, Position, PositionPatch, PositionState } from '@/lib/types'
import { Button, EmptyState, toast, type DotTone } from '@/components/ui'
import { Page } from '@/components/shell/Page'

/** Settings -> Features: Enterprises is on and Agents too (undefined while the settings load). */
export function useEnterprisesOn(): boolean | undefined {
  const { data: s } = useSettings()
  return s ? !!s.enterprises_page && !!s.agents_page : undefined
}

/** The page shown when the feature is off. */
export function EnterprisesOff() {
  const t = useT()
  return (
    <Page title={t('ent.title')} description={t('ent.desc')}>
      <EmptyState
        icon={Building2}
        title={t('ent.off')}
        description={t('ent.offDesc')}
        action={
          <Button asChild>
            <Link to="/settings/features">
              <Settings2 /> {t('ent.turnOn')}
            </Link>
          </Button>
        }
      />
    </Page>
  )
}

/** The Office's tones for the states they share (waiting, working, unread, failed, off); the rest is calm. */
export const STATE_TONE: Record<PositionState, { tone: DotTone; pulse?: boolean; label: TKey }> = {
  working: { tone: 'running', pulse: true, label: 'ent.state.working' },
  waiting: { tone: 'warn', pulse: true, label: 'ent.state.waiting' },
  unread: { tone: 'unread', label: 'ent.state.unread' },
  failed: { tone: 'error', label: 'ent.state.failed' },
  off: { tone: 'idle', label: 'ent.state.off' },
  vacant: { tone: 'idle', label: 'ent.state.vacant' },
  blocked: { tone: 'warn', label: 'ent.state.blocked' },
  idle: { tone: 'ok', label: 'ent.state.idle' },
}

const BLOCKED_REASONS: Record<string, TKey> = {
  budget: 'ent.blocked.budget',
  envelope: 'ent.blocked.envelope',
  disabled: 'ent.blocked.disabled',
  'agent missing': 'ent.blocked.agentMissing',
}

/** What a position's state reads: a blocked one says why (known reasons translated, anything else as sent). */
export function stateText(t: (k: TKey) => string, p: Position): string {
  if (p.state !== 'blocked' || !p.blocked_reason) return t(STATE_TONE[p.state].label)
  const k = BLOCKED_REASONS[p.blocked_reason]
  return `${t('ent.state.blocked')}: ${k ? t(k) : p.blocked_reason}`
}

/** position id -> the positions that report to it, in chart order. A lead that is not in the chart (broken file)
 *  counts as no lead, so no box is ever lost. */
export function childrenMap(positions: Position[]): Map<string | null, Position[]> {
  const ids = new Set(positions.map((p) => p.id))
  const out = new Map<string | null, Position[]>()
  for (const p of positions) {
    const lead = p.reports_to && ids.has(p.reports_to) && p.reports_to !== p.id ? p.reports_to : null
    out.set(lead, [...(out.get(lead) || []), p])
  }
  return out
}

/** The position and everything below it. */
export function subtreeIds(positions: Position[], id: string): Set<string> {
  const kids = childrenMap(positions)
  const out = new Set<string>([id])
  const walk = (x: string) => {
    for (const c of kids.get(x) || []) if (!out.has(c.id)) {
      out.add(c.id)
      walk(c.id)
    }
  }
  walk(id)
  return out
}

/** The roots of the chart as drawn: under the top. A position as top (Director) leads the other roots. */
export function chartRoots(e: Pick<Enterprise, 'positions' | 'top'>): { kids: Map<string | null, Position[]>; roots: Position[] } {
  const kids = childrenMap(e.positions)
  const roots = kids.get(null) || []
  const top = e.top !== 'owner' ? roots.find((p) => p.id === e.top) : undefined
  if (!top) return { kids, roots }
  kids.set(top.id, [...(kids.get(top.id) || []), ...roots.filter((p) => p !== top)])
  return { kids, roots: [top] }
}

/** Where the agents of a position may come from: its linked projects' agents, as paths. */
export const inProjects = (path: string, projects: string[]) => projects.some((p) => path.startsWith(`projects/${p}/`))

/** Saves one position. `structural` (move, re-seat) sends the chart's `rev`: when another change got there first the
 *  server answers `409 stale`, the chart is fetched again and the owner is told. */
export function useSavePosition(e: Pick<Enterprise, 'id' | 'rev'>) {
  const t = useT()
  const qc = useQueryClient()
  const patch = usePatchPosition()
  const save = (pos: string, fields: Omit<PositionPatch, 'rev'>, opts: { structural?: boolean; onDone?: () => void } = {}) =>
    patch.mutate(
      { id: e.id, pos, ...(opts.structural ? { rev: e.rev } : {}), ...fields },
      {
        onSuccess: () => opts.onDone?.(),
        onError: (err) => {
          if (isApiError(err, 'stale')) {
            void qc.invalidateQueries({ queryKey: entKeys.one(e.id) })
            toast.error(t('ent.stale'))
          } else toast.error(errorMessage(err))
        },
      },
    )
  return { save, pending: patch.isPending }
}
