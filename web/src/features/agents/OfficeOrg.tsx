// The Org view of the Office (AgentsOverview, picked in its view menu): the desks grouped by enterprise and department,
// the lead in front, each desk captioned with its position. Only agents that hold a position show here; the others stay
// under "Not in an enterprise". Classic and Space stay grouped by project.
import * as React from 'react'
import { useQueries } from '@tanstack/react-query'
import { useT } from '@/i18n'
import { enterpriseQuery, useEnterprises, useSettings } from '@/lib/queries'
import type { Agent, Enterprise, Position } from '@/lib/types'
import { Badge, Sensitive } from '@/components/ui'
import type { ProjectGroup } from './layout'

export type Seat = { enterprise: Enterprise; position: Position }

/** agent path -> its position, over every enterprise; null while the feature is off or no agent holds a position. */
export function useOrgSeats(): Map<string, Seat> | null {
  const { data: s } = useSettings()
  const on = !!s?.enterprises_page && !!s?.agents_page
  const { data: list } = useEnterprises(on)
  const all = useQueries({ queries: on ? (list || []).map((x) => enterpriseQuery(x.id)) : [], combine: (rs) => rs.map((r) => r.data) })
  return React.useMemo(() => {
    const m = new Map<string, Seat>()
    for (const e of all) for (const p of e?.positions || []) if (e && p.agent && p.occupant) m.set(p.agent, { enterprise: e, position: p })
    return m.size ? m : null
  }, [all])
}

const GRID = 'grid grid-cols-[repeat(auto-fill,minmax(11rem,1fr))] gap-3'

/** Positions of a department in drawing order: the ones whose lead is outside the department first (the leads), then the rest. */
function ordered(positions: Position[], dept: string): { p: Position; lead: boolean }[] {
  const inDept = positions.filter((p) => p.department === dept)
  const ids = new Set(inDept.map((p) => p.id))
  const depth = (p: Position): number => {
    let n = 0
    let cur: Position | undefined = p
    while (cur?.reports_to && ids.has(cur.reports_to) && n < 12) {
      const up: string = cur.reports_to
      cur = inDept.find((x) => x.id === up)
      n++
    }
    return n
  }
  return inDept
    .map((p) => ({ p, lead: !p.reports_to || !ids.has(p.reports_to), d: depth(p) }))
    .sort((a, b) => a.d - b.d)
    .map(({ p, lead }) => ({ p, lead }))
}

export function OfficeOrg({ groups, seats, renderTile }: { groups: ProjectGroup[]; seats: Map<string, Seat>; renderTile: (a: Agent, index: number) => React.ReactNode }) {
  const t = useT()
  const byPath = React.useMemo(() => new Map(groups.flatMap((g) => g.agents).map((a) => [a.path, a])), [groups])
  const enterprises = React.useMemo(() => [...new Map([...seats.values()].map((s) => [s.enterprise.id, s.enterprise])).values()], [seats])
  const others = [...byPath.values()].filter((a) => !seats.has(a.path))
  return (
    <div className="grid gap-8" data-testid="agents-org">
      {enterprises.map((e) => {
        const depts = [...new Set(e.positions.filter((p) => p.agent && byPath.has(p.agent)).map((p) => p.department))]
        return (
          <section key={e.id} className="grid gap-5" aria-label={e.name} data-testid="agents-org-enterprise">
            <h2 className="flex min-w-0 items-center gap-2 text-sm font-semibold">
              {e.emoji && <span aria-hidden>{e.emoji}</span>}
              <span className="min-w-0 truncate">
                <Sensitive length={10}>{e.name}</Sensitive>
              </span>
            </h2>
            {depts.map((d) => {
              const rows = ordered(e.positions, d).filter(({ p }) => p.agent && byPath.has(p.agent))
              return (
                <div key={d} className="grid gap-3" data-testid="agents-org-department">
                  <h3 className="px-0.5 text-[13px] font-medium text-muted-foreground">
                    <Sensitive length={8}>{d ? e.departments[d]?.name || d : t('agents.office.orgNoDept')}</Sensitive>
                  </h3>
                  <ul className={GRID}>
                    {rows.map(({ p, lead }, i) => (
                      <li key={p.id} className="grid min-w-0 gap-1.5">
                        <span className="flex min-w-0 items-center gap-1.5 px-0.5 text-xs text-muted-foreground">
                          <span className="min-w-0 truncate">
                            <Sensitive length={10}>{p.title}</Sensitive>
                          </span>
                          {lead && <Badge variant="muted">{t('agents.office.orgLead')}</Badge>}
                        </span>
                        {renderTile(byPath.get(p.agent as string) as Agent, i)}
                      </li>
                    ))}
                  </ul>
                </div>
              )
            })}
          </section>
        )
      })}
      {others.length > 0 && (
        <section className="grid gap-3" aria-label={t('agents.office.orgOthers')}>
          <h2 className="px-0.5 text-sm font-semibold">{t('agents.office.orgOthers')}</h2>
          <ul className={GRID}>
            {others.map((a, i) => (
              <li key={a.path}>{renderTile(a, i)}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
