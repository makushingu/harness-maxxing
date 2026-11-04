// The layout of the Agents page, shared by the list (AgentsList) and both views of the Office (Classic, Space):
// the order of the projects, the order of the agents inside each project and the colour of each project, picked by
// hand and kept on the server (GET/PUT /api/agents/layout, the same on every device). What was never moved keeps the
// default order: projects in the workspace order, agents by topic then name; a project's colour defaults to
// projectColor() (a stable pick from its name).
// Reordering: drag and drop (HTML5, computers) of a project header / room or of an agent; an agent only moves inside
// its own project (it is a folder of one of its topics). ProjectMenu (the "..." of a project) = Move up / down and the
// colour, the way in from the keyboard and touch screens.
import * as React from 'react'
import { ArrowDown, ArrowUp, Check, MoreHorizontal } from 'lucide-react'
import { tDyn, useT } from '@/i18n'
import { useAgents, useAgentsLayoutData, useSaveAgentsLayout, useWorkspace } from '@/lib/queries'
import type { Agent, AgentsLayout } from '@/lib/types'
import { cn } from '@/lib/utils'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui'
import { useCompact } from '@/stores/media'
import { AVATAR_OPTIONS, OUTFIT, projectColor } from './Avatar'

const EMPTY: AgentsLayout = { projects: [], colors: {}, agents: {} }

/** Position in a hand-picked order (not listed = after every listed one). */
const rank = (list: string[] | undefined, x: string) => {
  const i = list ? list.indexOf(x) : -1
  return i < 0 ? 1e9 : i
}
/** The default order of agents inside a project: by topic, then name. */
const byTopicName = (x: Agent, y: Agent) => x.topic.localeCompare(y.topic) || x.display_name.localeCompare(y.display_name)

/** `[x moved to the place of target]` (the others shift by one). */
function moveTo<T>(list: T[], x: T, target: T): T[] {
  const from = list.indexOf(x)
  const to = list.indexOf(target)
  if (from < 0 || to < 0 || from === to) return list
  const out = [...list]
  out.splice(from, 1)
  out.splice(to, 0, x)
  return out
}

export type ProjectGroup = { project: string; agents: Agent[] }

export type AgentsLayoutApi = {
  /** The project's colour name (a key of OUTFIT). */
  colorOf: (project: string) => string
  /** `agents` grouped by project, projects and agents in the layout order. */
  group: (agents: Agent[]) => ProjectGroup[]
  /** Every project with agents, in order (the reference for Move up / down, whatever the list shows). */
  projects: string[]
  moveProject: (project: string, target: string) => void
  /** One step up (-1) or down (+1) in `among` (the projects shown), else in every project. */
  stepProject: (project: string, dir: -1 | 1, among?: string[]) => void
  /** The agent at `path` takes the place of `target` (same project only). */
  moveAgent: (path: string, target: Agent) => void
  setColor: (project: string, color: string) => void
}

/** The colour of a project: the one picked on the Agents page, else projectColor(). For the outfit of a new agent. */
export function useProjectColorOf(): (project: string) => string {
  const { data: lay = EMPTY } = useAgentsLayoutData()
  return React.useCallback((p: string) => (lay.colors[p] && lay.colors[p] in OUTFIT ? lay.colors[p] : projectColor(p)), [lay])
}

/** THE helper of the Agents page for the order of projects and agents and the project colours. */
export function useAgentsLayout(): AgentsLayoutApi {
  const { data: lay = EMPTY } = useAgentsLayoutData()
  const { data: ws } = useWorkspace()
  const { data } = useAgents()
  const save = useSaveAgentsLayout()
  const all = React.useMemo(() => data?.agents || [], [data])
  const wsOrder = React.useMemo(() => (ws?.projects || []).map((p) => p.name), [ws])

  const colorOf = useProjectColorOf()
  const sortProjects = React.useCallback(
    (ps: string[]) => [...ps].sort((x, y) => rank(lay.projects, x) - rank(lay.projects, y) || rank(wsOrder, x) - rank(wsOrder, y) || x.localeCompare(y)),
    [lay, wsOrder],
  )
  const sortAgents = React.useCallback(
    (p: string, list: Agent[]) => [...list].sort((x, y) => rank(lay.agents[p], x.path) - rank(lay.agents[p], y.path) || byTopicName(x, y)),
    [lay],
  )
  const group = React.useCallback(
    (agents: Agent[]) => {
      const m = new Map<string, Agent[]>()
      for (const a of agents) m.set(a.project, [...(m.get(a.project) || []), a])
      return sortProjects([...m.keys()]).map((p) => ({ project: p, agents: sortAgents(p, m.get(p)!) }))
    },
    [sortProjects, sortAgents],
  )
  const projects = React.useMemo(() => sortProjects([...new Set(all.map((a) => a.project))]), [all, sortProjects])

  const put = (next: Partial<AgentsLayout>) => save.mutate({ ...EMPTY, ...lay, ...next })
  const moveProject = (p: string, target: string) => {
    const next = moveTo(projects, p, target)
    // Names kept on purpose (a project with no agent for now, a renamed one coming back) stay after the moved ones.
    if (next !== projects) put({ projects: [...next, ...(lay?.projects || []).filter((x) => !next.includes(x))] })
  }
  const stepProject = (p: string, dir: -1 | 1, among = projects) => {
    const target = among[among.indexOf(p) + dir]
    if (target) moveProject(p, target)
  }
  const moveAgent = (path: string, target: Agent) => {
    const p = target.project
    if (!path.startsWith(`projects/${p}/`)) return
    const list = sortAgents(p, all.filter((x) => x.project === p)).map((x) => x.path)
    const next = moveTo(list, path, target.path)
    if (next !== list) put({ agents: { ...lay.agents, [p]: next } })
  }
  const setColor = (p: string, color: string) => put({ colors: { ...lay.colors, [p]: color } })
  return { colorOf, group, projects, moveProject, stepProject, moveAgent, setColor }
}

// ---- drag and drop ----------------------------------------------------------------------------------
// What is being dragged lives here (one window, one drag at a time): drop targets read it while hovering, which the
// DataTransfer does not allow.
type DragItem = { kind: 'project' | 'agent'; id: string; project: string; index: number }
let dragged: DragItem | null = null
const MIME = 'application/x-maxxing-agents'

const accepts = (target: DragItem) =>
  !!dragged && dragged.kind === target.kind && dragged.id !== target.id && (target.kind === 'project' || dragged.project === target.project)

export type DropSide = 'before' | 'after' | null

/**
 * A project header / room or an agent that can be dragged and dropped on its siblings. `index` = its place in the
 * list shown (the drop indicator goes on the side the dragged item comes from). `onDrop(id)` = the dragged item's id
 * (a project name or an agent path). `source` = what is grabbed, `target` = where it can land, `props` = both.
 * Off on touch screens (no HTML5 drag there: ProjectMenu instead).
 */
export function useReorder(item: DragItem, onDrop: (draggedId: string) => void) {
  const touch = useCompact()
  const [dragging, setDragging] = React.useState(false)
  const [side, setSide] = React.useState<DropSide>(null)
  if (touch) return { on: false, dragging: false, side: null as DropSide, source: {}, target: {}, props: {} }
  const source = {
    draggable: true,
    onDragStart: (e: React.DragEvent) => {
      e.stopPropagation()                               // an agent inside a room: the agent moves, not the room
      dragged = item
      e.dataTransfer.effectAllowed = 'move'
      e.dataTransfer.setData(MIME, item.id)
      setDragging(true)
    },
    onDragEnd: () => {
      dragged = null
      setDragging(false)
    },
  }
  const target = {
    onDragOver: (e: React.DragEvent) => {
      if (!accepts(item)) return
      e.preventDefault()
      e.stopPropagation()
      e.dataTransfer.dropEffect = 'move'
      const s: DropSide = dragged!.index < item.index ? 'after' : 'before'
      if (s !== side) setSide(s)
    },
    onDragLeave: (e: React.DragEvent) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setSide(null)
    },
    onDrop: (e: React.DragEvent) => {
      setSide(null)
      if (!accepts(item)) return
      e.preventDefault()
      e.stopPropagation()
      const id = dragged!.id
      dragged = null
      onDrop(id)
    },
  }
  return { on: true, dragging, side, source, target, props: { ...source, ...target } }
}

/** The drop indicator: a bar on the side the dragged item will go (`vertical` = a list, else a row of cards). */
export function DropBar({ side, vertical = true, className }: { side: DropSide; vertical?: boolean; className?: string }) {
  if (!side) return null
  return (
    <span
      aria-hidden
      className={cn(
        'pointer-events-none absolute z-10 rounded-full bg-primary',
        vertical ? 'inset-x-1 h-0.5' : 'inset-y-1 w-1',
        vertical ? (side === 'before' ? '-top-px' : '-bottom-px') : side === 'before' ? '-left-2' : '-right-2',
        className,
      )}
      data-testid="agents-drop-bar"
    />
  )
}

/** The "..." of a project: Move up, Move down (in `among`, the projects shown) and its colour. */
export function ProjectMenu({ project, layout, among, className }: { project: string; layout: AgentsLayoutApi; among: string[]; className?: string }) {
  const t = useT()
  const i = among.indexOf(project)
  const current = layout.colorOf(project)
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          onClick={(e) => e.stopPropagation()}
          className={cn(
            'relative grid size-6 shrink-0 place-items-center rounded-md text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring before:absolute before:-inset-1.5 before:content-[""] data-[state=open]:bg-accent data-[state=open]:text-foreground',
            className,
          )}
          aria-label={t('agents.layout.menu', { project })}
          data-testid="agents-project-menu"
        >
          <MoreHorizontal className="size-4" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" onClick={(e) => e.stopPropagation()}>
        <DropdownMenuItem disabled={i <= 0} onSelect={() => layout.stepProject(project, -1, among)} data-testid="agents-project-up">
          <ArrowUp /> {t('agents.layout.up')}
        </DropdownMenuItem>
        <DropdownMenuItem disabled={i < 0 || i >= among.length - 1} onSelect={() => layout.stepProject(project, 1, among)} data-testid="agents-project-down">
          <ArrowDown /> {t('agents.layout.down')}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>{t('agents.layout.color')}</DropdownMenuLabel>
        <div className="flex gap-1 px-1.5 pb-1.5" role="radiogroup" aria-label={t('agents.layout.color')}>
          {AVATAR_OPTIONS.color.map((c) => {
            const name = tDyn(t, `agents.avatar.color.${c}`, c)
            return (
              <button
                key={c}
                type="button"
                role="radio"
                aria-checked={c === current}
                aria-label={name}
                title={name}
                onClick={() => layout.setColor(project, c)}
                className={cn('grid size-7 place-items-center rounded-md outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring max-md:size-9', c === current && 'bg-accent')}
                data-testid={`agents-project-color-${c}`}
              >
                <span className="grid size-5 place-items-center rounded-full border border-black/15 text-white" style={{ background: OUTFIT[c] }}>
                  {c === current && <Check className="size-3" strokeWidth={3} />}
                </span>
              </button>
            )
          })}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
