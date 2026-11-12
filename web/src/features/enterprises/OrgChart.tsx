// The org chart: the home of an enterprise. A tree of position cards (connectors are plain borders) on a computer, a
// collapsible indented list on a phone. A click opens the position's panel (?pos=<id>); a card dragged onto another one
// (pointer, computer only) changes its lead. The owner's own box at the top is a drop target too ("report to the top").
import * as React from 'react'
import { useSearchParams } from 'react-router'
import { ChevronRight, Inbox, Plus, UserRound, UsersRound } from 'lucide-react'
import { useT } from '@/i18n'
import type { Enterprise, Position } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button, EmptyState, Sensitive, StatusDot } from '@/components/ui'
import { Callout } from '@/features/common'
import { AgentAvatarIcon } from '@/features/agents/Avatar'
import { fmtCost } from '@/pages/sessions/util'
import { useCompact } from '@/stores/media'
import { AddPositionDialog } from './dialogs'
import { PositionSheet } from './PositionSheet'
import { STATE_TONE, chartRoots, subtreeIds, useSavePosition } from './parts'

type Kids = Map<string | null, Position[]>

/** The face (or an empty seat), the title, who holds it, its state and what it cost today. */
function Face({ p, size }: { p: Position; size: number }) {
  return p.occupant ? (
    <AgentAvatarIcon avatar={p.occupant.avatar} size={size} mood={p.occupant.enabled ? 'idle' : 'sleep'} />
  ) : (
    <span style={{ width: size, height: size }} className="flex shrink-0 items-center justify-center rounded-md border border-dashed text-muted-foreground">
      <UserRound className="size-4" strokeWidth={1.6} />
    </span>
  )
}

function PositionCard({
  p,
  selected,
  over,
  onOpen,
  onDown,
}: {
  p: Position
  selected: boolean
  over: boolean
  onOpen: () => void
  onDown: (ev: React.PointerEvent) => void
}) {
  const t = useT()
  const st = STATE_TONE[p.state]
  return (
    <button
      type="button"
      data-pos={p.id}
      data-state={p.state}
      data-testid="position-card"
      onClick={onOpen}
      onPointerDown={onDown}
      aria-label={`${p.title} · ${t(st.label)}`}
      className={cn(
        'grid w-48 cursor-pointer gap-2 rounded-xl border bg-card p-3 text-left transition-colors outline-none select-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring',
        !p.occupant && 'border-dashed bg-transparent',
        (selected || over) && 'border-primary ring-2 ring-primary/40',
      )}
    >
      <span className="flex items-center gap-2.5">
        <Face p={p} size={32} />
        <span className="grid min-w-0 flex-1">
          <span className="truncate text-sm leading-tight font-medium">
            <Sensitive length={10}>{p.title}</Sensitive>
          </span>
          <span className="truncate text-xs text-muted-foreground">{p.occupant ? <Sensitive length={8}>{p.occupant.display_name}</Sensitive> : t('ent.chart.vacant')}</span>
        </span>
      </span>
      <span className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <StatusDot tone={st.tone} pulse={st.pulse} />
          <span className="truncate">{t(st.label)}</span>
        </span>
        <span className="inline-flex shrink-0 items-center gap-2 tabular-nums">
          {p.inbox > 0 && (
            <span className="inline-flex items-center gap-0.5" title={t('ent.chart.inbox', { count: p.inbox })}>
              <Inbox className="size-3" />
              {p.inbox}
            </span>
          )}
          <Sensitive length={4}>{fmtCost(p.cost_today)}</Sensitive>
        </span>
      </span>
    </button>
  )
}

/** The owner's box at the top of the chart: where a dragged card goes to report to the top. */
function OwnerCard({ over }: { over: boolean }) {
  const t = useT()
  return (
    <div data-pos="" data-testid="chart-owner" className={cn('flex w-48 items-center gap-2.5 rounded-xl border bg-muted/40 p-3 select-none', over && 'border-primary ring-2 ring-primary/40')}>
      <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
        <UsersRound className="size-4" strokeWidth={1.6} />
      </span>
      <span className="grid min-w-0">
        <span className="truncate text-sm font-medium">{t('ent.chart.owner')}</span>
        <span className="truncate text-xs text-muted-foreground">{t('ent.chart.ownerHint')}</span>
      </span>
    </div>
  )
}

type Ctx = { kids: Kids; sel: string | null; over: string | null | undefined; open: (id: string) => void; down: (p: Position, ev: React.PointerEvent) => void }

/** One position and the row of its reports under it: a stub down from the card, a bar across the row, a stub into each
 *  report (the bar has no left half on the first report and no right half on the last). */
function Branch({ p, ctx }: { p: Position; ctx: Ctx }) {
  const reports = ctx.kids.get(p.id) || []
  return (
    <div className="flex flex-col items-center">
      <PositionCard p={p} selected={ctx.sel === p.id} over={ctx.over === p.id} onOpen={() => ctx.open(p.id)} onDown={(ev) => ctx.down(p, ev)} />
      {reports.length > 0 && <Row list={reports} ctx={ctx} />}
    </div>
  )
}

function Row({ list, ctx }: { list: Position[]; ctx: Ctx }) {
  return (
    <>
      <div className="h-4 w-px bg-border" />
      <div className="flex items-start">
        {list.map((c, i) => (
          <div key={c.id} className="flex flex-col items-center">
            <div className="flex h-4 w-full">
              <div className={cn('flex-1', i > 0 && 'border-t')} />
              <div className="w-px bg-border" />
              <div className={cn('flex-1', i < list.length - 1 && 'border-t')} />
            </div>
            <div className="px-2">
              <Branch p={c} ctx={ctx} />
            </div>
          </div>
        ))}
      </div>
    </>
  )
}

/** Phone: an indented list, each lead with a fold. */
function ListNode({ p, ctx, depth, closed, toggle }: { p: Position; ctx: Ctx; depth: number; closed: Set<string>; toggle: (id: string) => void }) {
  const t = useT()
  const reports = ctx.kids.get(p.id) || []
  const folded = closed.has(p.id)
  const st = STATE_TONE[p.state]
  return (
    <li>
      <div className="flex items-center gap-1 border-b" style={{ paddingLeft: depth * 16 }}>
        {reports.length > 0 ? (
          <Button variant="ghost" size="icon-sm" aria-expanded={!folded} aria-label={t(folded ? 'ent.chart.expand' : 'ent.chart.collapse', { title: p.title })} onClick={() => toggle(p.id)}>
            <ChevronRight className={cn('transition-transform motion-reduce:transition-none', !folded && 'rotate-90')} />
          </Button>
        ) : (
          <span className="size-8 shrink-0" />
        )}
        <button
          type="button"
          data-pos={p.id}
          data-testid="position-row"
          onClick={() => ctx.open(p.id)}
          className={cn('flex min-h-14 min-w-0 flex-1 items-center gap-2.5 py-2 pr-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring', ctx.sel === p.id && 'bg-accent')}
        >
          <Face p={p} size={32} />
          <span className="grid min-w-0 flex-1">
            <span className="truncate text-sm font-medium">
              <Sensitive length={10}>{p.title}</Sensitive>
            </span>
            <span className="truncate text-xs text-muted-foreground">{p.occupant ? <Sensitive length={8}>{p.occupant.display_name}</Sensitive> : t('ent.chart.vacant')}</span>
          </span>
          <span className="grid shrink-0 justify-items-end gap-0.5 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <StatusDot tone={st.tone} pulse={st.pulse} />
              {t(st.label)}
            </span>
            <span className="tabular-nums">
              <Sensitive length={4}>{fmtCost(p.cost_today)}</Sensitive>
            </span>
          </span>
        </button>
      </div>
      {reports.length > 0 && !folded && (
        <ul>
          {reports.map((c) => (
            <ListNode key={c.id} p={c} ctx={ctx} depth={depth + 1} closed={closed} toggle={toggle} />
          ))}
        </ul>
      )}
    </li>
  )
}

export function OrgChart({ enterprise: e }: { enterprise: Enterprise }) {
  const t = useT()
  const touch = useCompact()
  const [params, setParams] = useSearchParams()
  const sel = params.get('pos')
  const [adding, setAdding] = React.useState(false)
  const [closed, setClosed] = React.useState<Set<string>>(new Set())
  const [drag, setDrag] = React.useState<{ id: string; x: number; y: number; over: string | null | undefined } | null>(null)
  const { save } = useSavePosition(e)
  const { kids, roots } = React.useMemo(() => chartRoots(e), [e])
  const byId = React.useMemo(() => new Map(e.positions.map((p) => [p.id, p])), [e.positions])

  const open = React.useCallback(
    (id: string | null) =>
      setParams(
        (p) => {
          if (id) p.set('pos', id)
          else p.delete('pos')
          return p
        },
        { replace: true },
      ),
    [setParams],
  )

  // Drag: a computer's pointer only. Where it lands: a card (its id), the owner's box ('' = report to the top) or nowhere.
  const eRef = React.useRef(e)
  eRef.current = e
  const suppress = React.useRef(false)
  const target = (x: number, y: number, p: Position): string | null | undefined => {
    const el = document.elementFromPoint(x, y)?.closest<HTMLElement>('[data-pos]')
    if (!el) return undefined
    const id = el.dataset.pos ?? ''
    if (id === p.id || subtreeIds(eRef.current.positions, p.id).has(id)) return undefined
    return id === '' ? (p.reports_to === null ? undefined : null) : id === p.reports_to ? undefined : id
  }
  const down = (p: Position, ev: React.PointerEvent) => {
    if (touch || ev.pointerType !== 'mouse' || ev.button !== 0) return
    const sx = ev.clientX
    const sy = ev.clientY
    let moved = false
    const move = (m: PointerEvent) => {
      if (!moved && Math.hypot(m.clientX - sx, m.clientY - sy) < 6) return
      moved = true
      setDrag({ id: p.id, x: m.clientX, y: m.clientY, over: target(m.clientX, m.clientY, p) })
    }
    const up = (m: PointerEvent) => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', up)
      if (!moved) return
      // the click that ends the drag must not open the panel
      suppress.current = true
      setTimeout(() => (suppress.current = false), 0)
      setDrag(null)
      const to = m.type === 'pointerup' ? target(m.clientX, m.clientY, p) : undefined
      if (to !== undefined) save(p.id, { reports_to: to }, { structural: true })
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', up)
  }
  const ctx: Ctx = {
    kids,
    sel,
    over: drag ? drag.over : undefined,
    open: (id) => {
      if (!suppress.current) open(id)
    },
    down,
  }
  const dragged = drag ? byId.get(drag.id) : undefined
  const toggle = (id: string) => setClosed((s) => (s.has(id) ? new Set([...s].filter((x) => x !== id)) : new Set(s).add(id)))

  return (
    <div className="grid gap-4" data-testid="org-chart">
      {e.broken && (
        <Callout tone="warning" title={t('ent.chart.broken')}>
          {typeof e.broken === 'string' ? e.broken : t('ent.chart.brokenDesc')}
        </Callout>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] text-muted-foreground">{touch ? t('ent.chart.hintTouch') : t('ent.chart.hint')}</p>
        <Button size="sm" variant="outline" onClick={() => setAdding(true)} data-testid="position-add">
          <Plus /> {t('ent.position.add')}
        </Button>
      </div>
      {e.positions.length === 0 ? (
        <EmptyState
          icon={UsersRound}
          title={t('ent.chart.empty')}
          description={t('ent.chart.emptyDesc')}
          action={
            <Button onClick={() => setAdding(true)}>
              <Plus /> {t('ent.position.add')}
            </Button>
          }
        />
      ) : touch ? (
        <div className="-mx-3 border-t">
          <ul>
            <li>
              <div className="flex items-center gap-2.5 border-b px-4 py-3 text-sm font-medium">
                <UsersRound className="size-4 text-muted-foreground" />
                {t('ent.chart.owner')}
              </div>
            </li>
            {roots.map((p) => (
              <ListNode key={p.id} p={p} ctx={ctx} depth={0} closed={closed} toggle={toggle} />
            ))}
          </ul>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border bg-card/40">
          <div className="mx-auto flex w-max min-w-full flex-col items-center p-6">
            <OwnerCard over={drag?.over === null} />
            <Row list={roots} ctx={ctx} />
          </div>
        </div>
      )}
      {drag && dragged && (
        <div
          className="pointer-events-none fixed z-[60] flex w-48 items-center gap-2 rounded-xl border border-primary bg-popover p-2 text-sm shadow-pop"
          style={{ left: drag.x + 12, top: drag.y + 12 }}
          aria-hidden
        >
          <Face p={dragged} size={24} />
          <span className="truncate"><Sensitive length={10}>{dragged.title}</Sensitive></span>
        </div>
      )}
      <AddPositionDialog enterprise={e} open={adding} onOpenChange={setAdding} />
      <PositionSheet enterprise={e} positionId={sel} onClose={() => open(null)} />
    </div>
  )
}
