// The commit graph, drawn like VS Code's "Git Graph": one lane (column, colour) per line of history, merges and
// forks as curves, branch / tag / HEAD labels on their commit. Shared by the chat (```git blocks) and the Git page.
// Commits come newest first, children before parents (server/maxxing/gitview.py).
import * as React from 'react'
import { Cloud, Copy, ExternalLink, GitBranch, Link2, Tag } from 'lucide-react'
import type { GitCommit, GitRef } from '@/lib/types'
import { fmtDate, fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { useMediaQuery } from '@/stores/media'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'

// row height: 30 px, 40 px on touch screens so a tap opens the intended commit
const ROW_MOUSE = 30
const ROW_TOUCH = 40
const LANE = 16
const LANE_MIN = 7
// the lanes never take more than this share of the list: on a phone, 14 open branches squeeze their lanes
// instead of pushing the commit text off the row
const GRAPH_SHARE = 0.34
const PAD = 12
const R = 4.5
// Readable on dark and light backgrounds; a lane keeps its colour from top to bottom.
export const LANE_COLORS = ['#3b82f6', '#22c55e', '#f59e0b', '#ec4899', '#8b5cf6', '#14b8a6', '#ef4444', '#eab308', '#06b6d4', '#a3a3a3']
const color = (lane: number) => LANE_COLORS[lane % LANE_COLORS.length]

type Edge = { from: number; to: number; lane: number; kind: 'in' | 'out' | 'pass' }
type Row = { commit: GitCommit; col: number; color: number; edges: Edge[]; merge: boolean; span: number }

/** Lane assignment: `lanes[i]` = the sha lane i is waiting for (the next commit of that line). */
export function layout(commits: GitCommit[]): { rows: Row[]; width: number } {
  const lanes: (string | null)[] = []
  const laneColor: number[] = []   // colour index of each lane, given when the lane opens
  let nextColor = 0
  let width = 1
  const known = new Set(commits.map((c) => c.sha))
  const rows: Row[] = commits.map((c) => {
    let col = lanes.indexOf(c.sha)
    const continued = col !== -1 // a child above leads into this lane
    if (col === -1) {
      col = lanes.indexOf(null)
      if (col === -1) col = lanes.length
      lanes[col] = c.sha
      laneColor[col] = nextColor++
    }
    const edges: Edge[] = []
    // lines passing by, and lines ending here (several children of this commit = a fork seen from below)
    lanes.forEach((sha, i) => {
      if (sha === null || i === col) return
      if (sha === c.sha) {
        edges.push({ from: i, to: col, lane: laneColor[i], kind: 'in' })
        lanes[i] = null
      }
    })
    const above = lanes.map((s) => s)
    if (continued) edges.push({ from: col, to: col, lane: laneColor[col], kind: 'in' })
    const parents = c.parents.filter((p) => known.has(p))
    const cColor = laneColor[col]
    lanes[col] = parents[0] ?? null
    if (parents[0]) edges.push({ from: col, to: col, lane: cColor, kind: 'out' })
    for (const p of parents.slice(1)) {
      let j = lanes.indexOf(p)
      if (j === -1) {
        j = lanes.indexOf(null)
        if (j === -1) j = lanes.length
        lanes[j] = p
        laneColor[j] = nextColor++
      }
      edges.push({ from: col, to: j, lane: laneColor[j], kind: 'out' })
    }
    above.forEach((sha, i) => {
      if (sha !== null && i !== col && lanes[i] === sha) edges.push({ from: i, to: i, lane: laneColor[i], kind: 'pass' })
    })
    while (lanes.length && lanes[lanes.length - 1] === null) lanes.pop()
    width = Math.max(width, lanes.length, col + 1)
    // lanes drawn on this row: its text starts right after the rightmost one (not after the widest row of the graph)
    const span = Math.max(col, ...edges.map((e) => Math.max(e.from, e.to))) + 1
    return { commit: c, col, color: cColor, edges, merge: parents.length > 1, span }
  })
  return { rows, width }
}

const curve = (x1: number, y1: number, x2: number, y2: number) => {
  if (x1 === x2) return `M${x1} ${y1}V${y2}`
  const m = (y1 + y2) / 2
  return `M${x1} ${y1}C${x1} ${m} ${x2} ${m} ${x2} ${y2}`
}

// A long branch name shrinks with an ellipsis (full name on hover) instead of being cut mid-word, but keeps its first
// characters: on a phone, the HEAD row used to squeeze its remote badges down to the icon.
const badge = 'inline-flex items-center gap-1 rounded px-1.5 py-px font-mono text-[11px]'
// 7 characters + icon, gap, padding and border
const hold = 'pointer-coarse:select-none [-webkit-touch-callout:none]' // a label with a menu: long press = our menu
const fit = (name: string) => (name.length > 7 ? 'min-w-[calc(7ch+30px)]' : 'shrink-0')
const BadgeName = ({ name }: { name: string }) => <span className="min-w-0 truncate">{name}</span>

/** Where a branch label opens on GitHub: `github` = "owner/name" of the repository (origin for a clone on the server).
 *  A clone's remote branch counts only on origin; a local branch only once origin has it. null = not on GitHub. */
export function branchUrl(r: GitRef, github: string | null | undefined, onGithub: boolean, remotes: Set<string>): string | null {
  if (!github || (r.kind !== 'branch' && r.kind !== 'remote')) return null
  let name = r.name
  if (r.kind === 'remote') {
    if (!name.startsWith('origin/')) return null
    name = name.slice(7)
  } else if (!onGithub && !remotes.has(`origin/${name}`)) return null
  return `https://github.com/${github}/tree/${name.split('/').map(encodeURIComponent).join('/')}`
}

/** Commits of a clone that are on GitHub: those an origin/ branch leads to, within the loaded graph (children come
 *  before their parents, so one pass is enough). */
export function pushedShas(commits: GitCommit[]): Set<string> {
  const out = new Set<string>()
  for (const c of commits) {
    if (out.has(c.sha) || c.refs.some((r) => r.kind === 'remote' && r.name.startsWith('origin/'))) {
      out.add(c.sha)
      for (const p of c.parents) out.add(p)
    }
  }
  return out
}

type BadgeHandlers = Pick<React.HTMLAttributes<HTMLElement>, 'onContextMenu' | 'onTouchStart' | 'onTouchMove' | 'onTouchEnd' | 'onTouchCancel'>

function RefBadge({ r, lane, menu }: { r: GitRef; lane: number; menu?: BadgeHandlers }) {
  if (r.kind === 'head') return null
  const c = color(lane)
  if (r.kind === 'tag')
    return (
      <span title={r.name} className={cn(badge, 'shrink-0 border border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400')}>
        <Tag className="size-3 shrink-0" />
        <BadgeName name={r.name} />
      </span>
    )
  if (r.kind === 'remote')
    return (
      <span title={r.name} className={cn(badge, fit(r.name), menu && hold, 'border text-muted-foreground')} style={{ borderColor: `${c}66` }} data-ref={r.name} {...menu}>
        <Cloud className="size-3 shrink-0" />
        <BadgeName name={r.name} />
      </span>
    )
  return (
    <span
      title={r.name}
      className={cn(badge, fit(r.name), menu && hold, r.current && 'font-semibold text-white')}
      data-ref={r.name}
      {...menu}
      style={r.current ? { background: c } : { background: `${c}22`, color: c, boxShadow: `inset 0 0 0 1px ${c}66` }}
    >
      <GitBranch className="size-3 shrink-0" />
      <BadgeName name={r.name} />
    </span>
  )
}

export type GitGraphProps = {
  commits: GitCommit[]
  selected?: string | null
  onSelect?: (sha: string) => void
  /** commits to point out (full or short shas) */
  highlight?: Set<string>
  /** hide the author / date columns (narrow places: the chat on a phone) */
  compact?: boolean
  /** "owner/name" of the repository on GitHub: right click (long press) on a branch or a commit opens it there */
  github?: string | null
  /** the graph is read from GitHub itself (every branch is there), not from a clone */
  onGithub?: boolean
  className?: string
}

export function GitGraph({ commits, selected, highlight, onSelect, compact, github, onGithub, className }: GitGraphProps) {
  const lang = useLang()
  const t = useT()
  const remotes = React.useMemo(() => new Set(commits.flatMap((c) => c.refs.filter((r) => r.kind === 'remote').map((r) => r.name))), [commits])
  const pushed = React.useMemo(() => (onGithub ? null : pushedShas(commits)), [commits, onGithub])
  // Right click on a branch label or a commit row (a long press on a phone: iPhone Safari never fires contextmenu): a menu at the
  // pointer, placed inside the graph (its scroller is a containing block).
  type Target = { ref: GitRef; sha?: undefined } | { sha: string; ref?: undefined }
  const [menu, setMenu] = React.useState<(Target & { x: number; y: number; url: string | null }) | null>(null)
  const press = React.useRef<{ timer: number; x: number; y: number } | null>(null)
  const pressed = React.useRef(false) // the long press opened the menu: its touchend must not also select the commit
  const cancelPress = () => {
    if (press.current) window.clearTimeout(press.current.timer)
    press.current = null
  }
  React.useEffect(() => cancelPress, [])
  const openAt = (target: Target, x: number, y: number) => {
    const b = box.current?.getBoundingClientRect()
    if (!b) return
    const url = target.ref
      ? branchUrl(target.ref, github, !!onGithub, remotes)
      : github && (!pushed || pushed.has(target.sha))
        ? `https://github.com/${github}/commit/${target.sha}`
        : null
    setMenu({ ...target, x: x - b.left, y: y - b.top, url })
  }
  // stopPropagation: inside a chat message, the message's own menu (Copy / New session) must not open as well
  const menuHandlers = (target: Target): BadgeHandlers => ({
    onContextMenu: (e) => {
      if (window.getSelection()?.isCollapsed === false) return     // a selection keeps the browser's menu
      e.preventDefault()
      e.stopPropagation()
      openAt(target, e.clientX, e.clientY)
    },
    onTouchStart: (e) => {
      e.stopPropagation()
      cancelPress()
      const p = e.touches[0]
      pressed.current = false
      if (e.touches.length !== 1 || !p) return
      const at = { x: p.clientX, y: p.clientY }
      press.current = { ...at, timer: window.setTimeout(() => ((press.current = null), (pressed.current = true), openAt(target, at.x, at.y)), 550) }
    },
    onTouchMove: (e) => {
      const p = e.touches[0]
      if (press.current && p && Math.hypot(p.clientX - press.current.x, p.clientY - press.current.y) > 8) cancelPress()
    },
    onTouchEnd: (e) => {
      cancelPress()
      if (pressed.current) e.preventDefault()
    },
    onTouchCancel: cancelPress,
  })
  const rowH = useMediaQuery('(pointer: coarse)') ? ROW_TOUCH : ROW_MOUSE
  const { rows, width } = React.useMemo(() => layout(commits), [commits])
  const box = React.useRef<HTMLDivElement>(null)
  const [boxW, setBoxW] = React.useState(0)
  React.useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    setBoxW(el.clientWidth)
    const ro = new ResizeObserver(() => setBoxW(el.clientWidth))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const lane = width > 1 && boxW ? Math.max(LANE_MIN, Math.min(LANE, Math.floor((boxW * GRAPH_SHARE - PAD * 2) / (width - 1)))) : LANE
  const x = (i: number) => PAD + i * lane
  const w = PAD * 2 + (width - 1) * lane
  const h = rows.length * rowH
  const now = Date.now() / 1000
  return (
    <div ref={box} className={cn('relative text-[13px]', className)} role="list">
      <DropdownMenu open={!!menu} onOpenChange={(o) => !o && setMenu(null)}>
        <DropdownMenuTrigger asChild>
          <span aria-hidden tabIndex={-1} className="pointer-events-none absolute size-0" style={{ left: menu?.x ?? 0, top: menu?.y ?? 0 }} />
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="start"
          sideOffset={2}
          className="min-w-48"
          data-testid={menu?.sha ? 'git-commit-menu' : 'git-branch-menu'}
          onCloseAutoFocus={(e) => e.preventDefault()}
        >
          <DropdownMenuItem
            disabled={!menu?.url}
            onSelect={() => menu?.url && window.open(menu.url, '_blank', 'noopener,noreferrer')}
            data-testid="git-branch-github"
          >
            <ExternalLink />{' '}
            {menu?.url ? t(menu.sha ? 'git.commit.openGithub' : 'git.branch.openGithub') : t(menu?.sha ? 'git.commit.notOnGithub' : 'git.branch.notOnGithub')}
          </DropdownMenuItem>
          {menu?.url && (
            <DropdownMenuItem onSelect={() => void navigator.clipboard?.writeText(menu.url!)} data-testid="git-copy-link">
              <Link2 /> {t('git.copyLink')}
            </DropdownMenuItem>
          )}
          <DropdownMenuItem
            onSelect={() =>
              menu && void navigator.clipboard?.writeText(menu.sha ?? (menu.ref.kind === 'remote' ? menu.ref.name.replace(/^[^/]+\//, '') : menu.ref.name))
            }
          >
            <Copy /> {t(menu?.sha ? 'git.commit.copy' : 'git.branch.copy')}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <svg width={w} height={h} className="pointer-events-none absolute top-0 left-0" aria-hidden="true">
        {rows.map((row, i) => {
          const top = i * rowH
          const mid = top + rowH / 2
          const bottom = top + rowH
          return (
            <g key={row.commit.sha}>
              {row.edges.map((e, k) => {
                const d =
                  e.kind === 'pass'
                    ? curve(x(e.from), top, x(e.to), bottom)
                    : e.kind === 'in'
                      ? curve(x(e.from), top, x(e.to), mid)
                      : curve(x(e.from), mid, x(e.to), bottom)
                return <path key={k} d={d} stroke={color(e.lane)} strokeWidth={2} fill="none" strokeLinecap="round" />
              })}
            </g>
          )
        })}
        {rows.map((row, i) => {
          const cx = x(row.col)
          const cy = i * rowH + rowH / 2
          const lane = row.color
          const head = row.commit.refs.some((r) => r.kind === 'head')
          return (
            <g key={row.commit.sha}>
              {head && <circle cx={cx} cy={cy} r={R + 3.5} fill="none" stroke={color(lane)} strokeWidth={1.5} opacity={0.6} />}
              <circle cx={cx} cy={cy} r={row.merge ? R - 1 : R} fill={row.merge ? 'var(--background)' : color(lane)} stroke={color(lane)} strokeWidth={row.merge ? 2.5 : 0} />
            </g>
          )
        })}
      </svg>
      {rows.map((row) => {
        const c = row.commit
        const refs = c.refs.filter((r) => r.kind !== 'head')
        const sel = selected === c.sha
        const hl = !!highlight?.size && [...highlight].some((h) => c.sha.startsWith(h))
        return (
          <div
            key={c.sha}
            role="listitem"
            tabIndex={onSelect ? 0 : undefined}
            onClick={onSelect ? () => onSelect(c.sha) : undefined}
            onKeyDown={onSelect ? (e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onSelect(c.sha)) : undefined}
            className={cn(
              'flex items-center gap-2 rounded-md pr-2 outline-none',
              onSelect && 'cursor-pointer hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring',
              hl && !sel && 'bg-primary/10 ring-1 ring-primary/30 ring-inset',
              sel && 'bg-accent',
              github && 'pointer-coarse:select-none [-webkit-touch-callout:none]', // the long press opens our menu, not iOS's
            )}
            style={{ height: rowH, paddingLeft: PAD * 2 + (row.span - 1) * lane + 4 }}
            data-sha={c.sha}
            {...(github ? menuHandlers({ sha: c.sha }) : {})}
          >
            {refs.length > 0 && (
              <span className="flex max-w-[60%] min-w-0 shrink items-center gap-1 overflow-hidden">
                {refs.map((r) => (
                  <RefBadge key={r.kind + r.name} r={r} lane={row.color} menu={r.kind === 'tag' ? undefined : menuHandlers({ ref: r })} />
                ))}
              </span>
            )}
            <span className={cn('min-w-12 flex-1 truncate', row.merge && 'text-muted-foreground')} title={c.subject}>
              {c.subject}
            </span>
            {!compact && <span className="hidden max-w-32 shrink-0 truncate text-xs text-muted-foreground sm:inline">{c.author}</span>}
            <span className="w-20 shrink-0 text-right text-xs whitespace-nowrap text-muted-foreground tabular-nums" title={fmtDate(c.date, lang)}>
              {fmtRelative(c.date, lang, now)}
            </span>
            {!compact && <span className="hidden w-16 shrink-0 font-mono text-xs text-muted-foreground md:inline">{c.sha.slice(0, 7)}</span>}
          </div>
        )
      })}
    </div>
  )
}
