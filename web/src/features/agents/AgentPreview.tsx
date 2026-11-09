// Preview card of an agent, shown beside the sidebar's sessions rail when the pointer rests on an agent of the tree
// (pages/sessions/RailTree.tsx), or when it is focused from the keyboard: the agent in its Office, the room of its
// project as the Agents page draws it in the Space view (OfficeFuture.tsx: same art, its console under the selection
// cursor, the other agents of the project around, the free desk), then in words what it does now: the working rows of
// its running session (the session card's own block, pages/sessions/PreviewWorking.tsx), else its last run and its
// next scheduled start. Same frame as the session card (components/shell/SessionPreview.tsx: PreviewShell).
// Lazy-loaded with the "agents" texts (the rail's chunk only knows the import): fetched the first time the pointer
// enters a rail that lists agents. Read-only: the office is `inert`, a click on the row still opens the agent.
import * as React from 'react'
import { Clock } from 'lucide-react'
import { useAgents, useCrons, useSessionSeeded } from '@/lib/queries'
import type { Agent } from '@/lib/types'
import { fmtRelative } from '@/lib/format'
import { useLang, useT } from '@/i18n'
import { Sensitive, StatusDot } from '@/components/ui'
import { PreviewShell } from '@/components/shell/SessionPreview'
import PreviewWorking from '@/pages/sessions/PreviewWorking'
import { AgentAvatarIcon } from './Avatar'
import { OfficeRoom } from './OfficeFuture'
import { useAgentsLayout } from './layout'
import { agoText, firstLine, statusOf } from './parts'

/** Wide enough for a room of 3 consoles (the most a row of the preview holds). */
const CARD_W = 360
const CARD_MAX_H = 520
/** Consoles drawn at most (two rows with the free desk): the hovered agent is always one of them. */
const MAX_DESKS = 5

export default function AgentPreviewCard({
  agent: a,
  anchor,
  rail,
  onPointerEnter,
  onPointerLeave,
}: {
  agent: Agent
  anchor: HTMLElement
  rail: HTMLElement
  onPointerEnter: () => void
  onPointerLeave: () => void
}) {
  const t = useT()
  const lang = useLang()
  const layout = useAgentsLayout()
  const { data: list } = useAgents()
  const { data: crons } = useCrons()
  const st = statusOf(a, t, lang)
  // The room: the agents of its project in the Office's order, cut around the hovered one.
  const room = React.useMemo(() => {
    const peers = (list?.agents || []).filter((x) => x.project === a.project && x.path !== a.path)
    const ordered = layout.group([a, ...peers])[0]?.agents ?? [a]
    if (ordered.length <= MAX_DESKS) return ordered
    const i = Math.max(0, ordered.findIndex((x) => x.path === a.path))
    const from = Math.min(Math.max(0, i - 2), ordered.length - MAX_DESKS)
    return ordered.slice(from, from + MAX_DESKS)
  }, [layout, list, a])
  const manual = !a.telegram && !a.triggers.some((x) => x.enabled !== false) && !(crons?.jobs || []).some((j) => j.topic_path === a.path && j.enabled)
  const next = React.useMemo(() => {
    const own = (crons?.jobs || []).filter((j) => j.topic_path === a.path && j.enabled && j.next_run)
    return own.sort((x, y) => (x.next_run || 0) - (y.next_run || 0))[0]?.next_run ?? null
  }, [crons, a.path])
  const runId = a.running_sessions?.[0]?.id ?? null
  const { data: run } = useSessionSeeded(runId)
  const running = st.id === 'running' && !!runId
  const last = a.last_run

  return (
    <PreviewShell anchor={anchor} rail={rail} width={CARD_W} maxHeight={CARD_MAX_H} swapKey={a.path} testId="agent-preview" onPointerEnter={onPointerEnter} onPointerLeave={onPointerLeave}>
      <div className="flex shrink-0 items-start gap-2.5 border-b px-3.5 pt-3 pb-2.5">
        <AgentAvatarIcon avatar={a.avatar} size={32} mood={st.id === 'off' ? 'sleep' : 'idle'} className="mt-0.5" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm leading-5 font-semibold">
            <Sensitive length={10}>{a.display_name}</Sensitive>
            {a.silent && (
              <span className="ml-1 text-xs" title={t('agents.silentBadge')} aria-label={t('agents.silentBadge')}>
                🔕
              </span>
            )}
          </p>
          <p className="truncate text-xs leading-4 text-muted-foreground">
            <Sensitive length={10}>{`${a.project} / ${a.topic}`}</Sensitive>
          </p>
          <div className="mt-1.5 flex min-w-0 items-center gap-1.5 text-[11px] leading-4 text-muted-foreground">
            <StatusDot tone={st.tone} pulse={st.pulse} className="size-1.5 shrink-0" />
            <span className={st.id === 'running' || st.id === 'waiting' ? 'truncate text-foreground' : st.id === 'failed' ? 'truncate text-destructive' : 'truncate'}>{st.text}</span>
          </div>
        </div>
      </div>
      <div className="shrink-0 border-b">
        <OfficeRoom project={a.project} agents={room} focus={a.path} layout={layout} />
      </div>
      {running ? (
        // its run's own bottom rows while Claude works (the session card's block), its title until they load
        <div className="flex max-h-[176px] min-h-0 shrink-0 flex-col justify-end overflow-hidden bg-muted/30 px-3 pt-2 pb-0.5">
          <p className="mb-1 truncate text-[11px] leading-4 text-muted-foreground">
            <Sensitive length={14}>{a.running_sessions?.[0]?.title || t('agents.list.working')}</Sensitive>
          </p>
          {run && <PreviewWorking session={run} />}
        </div>
      ) : (
        <div className="grid min-h-0 gap-1.5 overflow-hidden px-3.5 py-2.5 text-[13px] leading-5">
          {last ? (
            <div className="min-w-0">
              <p className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">{t('agents.overview.ran', { when: agoText(last.at, lang, t) })}</p>
              {firstLine(last.text) && (
                <p className="line-clamp-2 break-words text-foreground/90">
                  <Sensitive length={30}>{firstLine(last.text)}</Sensitive>
                </p>
              )}
            </div>
          ) : (
            a.description && (
              <p className="line-clamp-2 break-words text-foreground/90">
                <Sensitive length={30}>{firstLine(a.description)}</Sensitive>
              </p>
            )
          )}
          {(next || manual) && (
            <p className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
              <Clock className="size-3 shrink-0" aria-hidden />
              <span className="block min-w-0 truncate first-letter:uppercase">{next ? t('agents.trigger.next', { when: fmtRelative(next, lang) }) : t('agents.trigger.manualOnly')}</span>
            </p>
          )}
        </div>
      )}
    </PreviewShell>
  )
}
