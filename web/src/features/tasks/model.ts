// Pure helpers for the Tasks page: priorities, due dates (in the configured time zone),
// filtering, sorting, ordering and the quick-add shortcut parser.
import type { Task, TaskPriority, TaskProject, TaskStatus } from '@/lib/types'
import type { TKey } from '@/i18n'

export const STATUSES: TaskStatus[] = ['todo', 'doing', 'done']
export const STATUS_KEY: Record<TaskStatus, TKey> = { todo: 'tasks.status.todo', doing: 'tasks.status.doing', done: 'tasks.status.done' }

export const PRIORITIES: TaskPriority[] = [3, 2, 1, 0]
export const PRIORITY_KEY: Record<TaskPriority, TKey> = {
  0: 'tasks.priority.none',
  1: 'tasks.priority.low',
  2: 'tasks.priority.medium',
  3: 'tasks.priority.urgent',
}
/** Text colour class per priority (tokens only). */
export const PRIORITY_CLS: Record<TaskPriority, string> = {
  0: 'text-muted-foreground',
  1: 'text-foreground/70',
  2: 'text-warning',
  3: 'text-destructive',
}

/* ------------------------------------------------------------------ project colours */
/** Task project colours = the accent palette (swatches are the documented exception to "no hard-coded colour"). */
export const PROJECT_COLORS = ['clay', 'blue', 'violet', 'green', 'amber', 'rose', 'teal', 'zinc'] as const
const SWATCH: Record<string, string> = {
  clay: 'oklch(0.68 0.145 40)',
  blue: 'oklch(0.62 0.185 258)',
  violet: 'oklch(0.6 0.2 293)',
  green: 'oklch(0.65 0.15 155)',
  amber: 'oklch(0.75 0.16 75)',
  rose: 'oklch(0.63 0.2 12)',
  teal: 'oklch(0.65 0.11 190)',
  zinc: 'oklch(0.6 0.01 286)',
}
/** CSS colour of a task project colour (palette name or #rrggbb written by hand). */
export function projectColor(c: string | undefined | null): string {
  if (!c) return SWATCH.zinc
  if (/^#[0-9a-f]{6}$/i.test(c)) return c
  return SWATCH[c] || SWATCH.zinc
}

/* ------------------------------------------------------------------ dates */
/** YYYY-MM-DD of "now" in the given time zone. */
export function todayISO(tz?: string, offsetDays = 0): string {
  const d = new Date(Date.now() + offsetDays * 86400_000)
  try {
    return new Intl.DateTimeFormat('en-CA', { timeZone: tz || undefined, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d)
  } catch {
    return d.toISOString().slice(0, 10)
  }
}
export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}
export function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400_000)
}

export type DueState = 'overdue' | 'today' | 'week' | 'later' | 'none'
export function dueState(t: Pick<Task, 'due' | 'status'>, today: string): DueState {
  if (!t.due) return 'none'
  const d = daysBetween(today, t.due)
  if (d < 0) return t.status === 'done' ? 'later' : 'overdue'
  if (d === 0) return 'today'
  if (d <= 7) return 'week'
  return 'later'
}

/** "Today", "Tomorrow", "Yesterday", weekday within a week, else a short date. */
export function fmtDue(due: string, today: string, lang: string, t: (k: TKey) => string): string {
  const d = daysBetween(today, due)
  if (d === 0) return t('tasks.due.today')
  if (d === 1) return t('tasks.due.tomorrow')
  if (d === -1) return t('tasks.due.yesterday')
  const date = new Date(`${due}T12:00:00Z`)
  if (d > 1 && d < 7) return new Intl.DateTimeFormat(lang, { weekday: 'long', timeZone: 'UTC' }).format(date)
  const sameYear = due.slice(0, 4) === today.slice(0, 4)
  return new Intl.DateTimeFormat(lang, { day: 'numeric', month: 'short', year: sameYear ? undefined : 'numeric', timeZone: 'UTC' }).format(date)
}

/* ------------------------------------------------------------------ filters */
export type DueFilter = 'all' | 'overdue' | 'today' | 'week' | 'none'
export type TaskFilters = { q: string; project: string; label: string; priority: string; due: DueFilter }
export const EMPTY_FILTERS: TaskFilters = { q: '', project: 'all', label: 'all', priority: 'all', due: 'all' }
export const activeFilterCount = (f: TaskFilters) =>
  (f.project !== 'all' ? 1 : 0) + (f.label !== 'all' ? 1 : 0) + (f.priority !== 'all' ? 1 : 0) + (f.due !== 'all' ? 1 : 0)

export function matches(task: Task, f: TaskFilters, today: string): boolean {
  if (f.project === 'none' ? task.project_id : f.project !== 'all' && task.project_id !== f.project) return false
  if (f.label !== 'all' && !task.labels.includes(f.label)) return false
  if (f.priority !== 'all' && String(task.priority) !== f.priority) return false
  if (f.due !== 'all') {
    if (f.due === 'none') {
      if (task.due) return false
    } else {
      if (!task.due || task.status === 'done') return false
      const d = daysBetween(today, task.due)
      // "today" = overdue + due today (what needs attention today)
      if (f.due === 'overdue' && d >= 0) return false
      if (f.due === 'today' && d > 0) return false
      if (f.due === 'week' && d > 7) return false
    }
  }
  const q = f.q.trim().toLowerCase()
  if (q) {
    const hay = `${task.title}\n${task.notes}\n${task.labels.join(' ')}`.toLowerCase()
    if (!q.split(/\s+/).every((w) => hay.includes(w))) return false
  }
  return true
}

export const byOrder = (a: Task, b: Task) => a.order - b.order || a.created - b.created

export type SortKey = 'order' | 'due' | 'priority' | 'created' | 'updated' | 'title'
export function sorter(key: SortKey): (a: Task, b: Task) => number {
  switch (key) {
    case 'due':
      return (a, b) => (a.due || '9999').localeCompare(b.due || '9999') || b.priority - a.priority || byOrder(a, b)
    case 'priority':
      return (a, b) => b.priority - a.priority || (a.due || '9999').localeCompare(b.due || '9999') || byOrder(a, b)
    case 'created':
      return (a, b) => b.created - a.created
    case 'updated':
      return (a, b) => b.updated - a.updated
    case 'title':
      return (a, b) => a.title.localeCompare(b.title)
    default:
      return byOrder
  }
}

/** Order value for a card dropped between `prev` and `next` (either may be missing). */
export function orderBetween(prev?: number, next?: number): number {
  if (prev != null && next != null) return prev === next ? prev + 0.0005 : (prev + next) / 2
  if (prev != null) return prev + 1
  if (next != null) return next - 1
  return 1
}

export function allLabels(tasks: Task[]): string[] {
  const s = new Set<string>()
  for (const t of tasks) for (const l of t.labels) s.add(l)
  return [...s].sort((a, b) => a.localeCompare(b))
}

/* ------------------------------------------------------------------ quick add */
export type QuickParse = { title: string; labels: string[]; priority?: TaskPriority; project_id?: string; due?: string; projectName?: string }
const WEEKDAYS: Record<string, number> = {
  sun: 0, sunday: 0, dim: 0, dimanche: 0,
  mon: 1, monday: 1, lun: 1, lundi: 1,
  tue: 2, tuesday: 2, mar: 2, mardi: 2,
  wed: 3, wednesday: 3, mer: 3, mercredi: 3,
  thu: 4, thursday: 4, jeu: 4, jeudi: 4,
  fri: 5, friday: 5, ven: 5, vendredi: 5,
  sat: 6, saturday: 6, sam: 6, samedi: 6,
}
const norm = (s: string) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')

function parseDue(word: string, today: string): string | undefined {
  const w = norm(word)
  if (/^\d{4}-\d{2}-\d{2}$/.test(w)) return w
  if (w === 'today' || w === 'aujourdhui' || w === 'auj') return today
  if (w === 'tomorrow' || w === 'tmr' || w === 'demain') return addDays(today, 1)
  if (w in WEEKDAYS) {
    const cur = new Date(`${today}T12:00:00Z`).getUTCDay()
    const diff = (WEEKDAYS[w] - cur + 7) % 7 || 7
    return addDays(today, diff)
  }
  const m = /^\+?(\d{1,3})d$/.exec(w) || /^\+?(\d{1,3})j$/.exec(w)
  if (m) return addDays(today, Number(m[1]))
  return undefined
}

/**
 * Shortcuts: `#label`, `!` / `!!` / `!!!` (priority low/medium/urgent), `@project` (task project name,
 * spaces as dashes), `^today` `^tomorrow` `^fri` `^3d` `^2026-05-04` (due date). Unknown tokens stay in the title.
 */
export function parseQuickAdd(input: string, projects: TaskProject[], today: string): QuickParse {
  const out: QuickParse = { title: '', labels: [] }
  const rest: string[] = []
  for (const tok of input.split(/\s+/).filter(Boolean)) {
    if (/^!{1,3}$/.test(tok)) {
      out.priority = tok.length as TaskPriority
      continue
    }
    if (/^#[^\s#]{1,40}$/.test(tok)) {
      const l = tok.slice(1)
      if (!out.labels.includes(l)) out.labels.push(l)
      continue
    }
    if (/^@\S+$/.test(tok)) {
      const want = norm(tok.slice(1)).replace(/[-_]+/g, ' ')
      const p = projects.find((x) => norm(x.name) === want) || projects.find((x) => norm(x.name).startsWith(want))
      if (p) {
        out.project_id = p.id
        out.projectName = p.name
        continue
      }
    }
    if (/^\^\S+$/.test(tok)) {
      const d = parseDue(tok.slice(1), today)
      if (d) {
        out.due = d
        continue
      }
    }
    rest.push(tok)
  }
  out.title = rest.join(' ')
  return out
}

/* ------------------------------------------------------------------ projects */
export type ProjectStats = { open: number; doing: number; overdue: number; today: number; urgent: number; done: number; total: number; next?: Task }
const EMPTY_STATS: ProjectStats = { open: 0, doing: 0, overdue: 0, today: 0, urgent: 0, done: 0, total: 0 }

/** Counts per task project id ('' = tasks without a project, or with a project that no longer exists). */
export function projectStats(tasks: Task[], projects: TaskProject[], today: string): Map<string, ProjectStats> {
  const known = new Set(projects.map((p) => p.id))
  const m = new Map<string, ProjectStats>()
  for (const x of tasks) {
    const k = x.project_id && known.has(x.project_id) ? x.project_id : ''
    const s = m.get(k) ?? { ...EMPTY_STATS }
    s.total++
    if (x.status === 'done') s.done++
    else {
      s.open++
      if (x.status === 'doing') s.doing++
      if (x.priority === 3) s.urgent++
      if (x.due && x.due < today) s.overdue++
      if (x.due === today) s.today++
      if (x.due && (!s.next || x.due < s.next.due! || (x.due === s.next.due && x.priority > s.next.priority))) s.next = x
    }
    m.set(k, s)
  }
  return m
}
export const statsOf = (m: Map<string, ProjectStats>, id: string) => m.get(id) ?? EMPTY_STATS

/** Workspace projects in the workspace order (Sessions tree), then free projects by name. */
export function orderProjects(projects: TaskProject[], workspaceOrder: string[]): TaskProject[] {
  const rank = new Map(workspaceOrder.map((n, i) => [n, i]))
  return [...projects].sort((a, b) => {
    const ra = a.workspace != null && rank.has(a.workspace) ? rank.get(a.workspace)! : Infinity
    const rb = b.workspace != null && rank.has(b.workspace) ? rank.get(b.workspace)! : Infinity
    return ra - rb || a.name.localeCompare(b.name)
  })
}

/** Monday of the week of `iso`. */
export function weekStart(iso: string): string {
  const day = new Date(`${iso}T12:00:00Z`).getUTCDay()
  return addDays(iso, -((day + 6) % 7))
}
