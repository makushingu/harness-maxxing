// What the pixel views of the Office share (Gamified OfficeGame.tsx, Futuristic OfficeFuture.tsx): the room of a
// project (its colour, emoji, grid of cells, where the free desk creates), an agent's desk (its status, open on click /
// Enter, drag and drop through layout.tsx) and the selection cursor. Each view only draws.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { useLang, useT } from '@/i18n'
import { agentRoute, useWorkspace } from '@/lib/queries'
import type { Agent } from '@/lib/types'
import { cn } from '@/lib/utils'
import { OUTFIT } from './Avatar'
import { useReorder, type AgentsLayoutApi } from './layout'
import { statusOf } from './parts'
import type { CreateStart } from './CreateAgent'

/** A small stable number from a string (which decoration sits on which desk). */
export const hash = (s: string) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7)

/** How many desk columns a room gets for `n` cells (2-5, growing with the room); fewer on a phone. */
export const colsFor = (n: number, phone: boolean) => Math.min(phone ? 3 : 5, Math.max(2, Math.ceil(Math.sqrt(n * 1.8))))

/** A project's room: its colour (hex), emoji, the grid (agents + the free desk, completed by `fillers`), the drag and
 *  drop of the whole room and what the free desk opens (a new agent in the topic most of its agents live in). */
export function useRoom(project: string, agents: Agent[], index: number, layout: AgentsLayoutApi, phone: boolean, onStart: (s: CreateStart) => void) {
  const dnd = useReorder({ kind: 'project', id: project, project, index }, (p) => layout.moveProject(p, project))
  const { data: ws } = useWorkspace()
  const emoji = ws?.projects.find((x) => x.name === project)?.emoji || ''
  const color = OUTFIT[layout.colorOf(project)]
  const cells = agents.length + 1
  const cols = colsFor(cells, phone)
  const fillers = (cols - (cells % cols)) % cols
  const topic = React.useMemo(() => {
    const n = new Map<string, number>()
    for (const a of agents) n.set(a.topic, (n.get(a.topic) || 0) + 1)
    return [...n.entries()].sort((x, y) => y[1] - x[1])[0]?.[0]
  }, [agents])
  const create = () => onStart(topic ? { topic: `projects/${project}/topics/${topic}` } : {})
  return { dnd, emoji, color, cols, fillers, create }
}

/** An agent's desk: its status and the props of the cell that opens it (a link: click, Enter or Space; draggable). */
export function useDesk(a: Agent, index: number, layout: AgentsLayoutApi) {
  const t = useT()
  const lang = useLang()
  const navigate = useNavigate()
  const dnd = useReorder({ kind: 'agent', id: a.path, project: a.project, index }, (path) => layout.moveAgent(path, a))
  const st = statusOf(a, t, lang)
  const open = () => navigate(agentRoute(a))
  const props = {
    role: 'link',
    tabIndex: 0,
    'aria-label': `${t('agents.overview.open', { name: a.display_name })} · ${st.text}`,
    onClick: open,
    onKeyDown: (e: React.KeyboardEvent) => (e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget && (e.preventDefault(), open()),
    ...dnd.props,
    'data-state': st.id,
    'data-path': a.path,
  }
  return { st, dnd, props }
}

/** Corner brackets around the hovered / focused desk, like the selection cursor of a game. */
export function Cursor({ className }: { className?: string }) {
  const b = cn('absolute size-2.5 border-primary opacity-0 transition-opacity group-hover/desk:opacity-100 group-focus-visible/desk:opacity-100', className)
  return (
    <span aria-hidden className="pointer-events-none absolute -inset-1">
      <i className={cn(b, 'top-0 left-0 border-t-[3px] border-l-[3px]')} />
      <i className={cn(b, 'top-0 right-0 border-t-[3px] border-r-[3px]')} />
      <i className={cn(b, 'bottom-0 left-0 border-b-[3px] border-l-[3px]')} />
      <i className={cn(b, 'right-0 bottom-0 border-r-[3px] border-b-[3px]')} />
    </span>
  )
}
