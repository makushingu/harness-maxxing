// The Gamified view of the Office (AgentsOverview, picked at the top right): a pixel-art office floor like a small
// video game. One room per project (its wall and floor tinted with the project colour, a wooden sign with its emoji and
// name), one desk per agent with its character sitting behind it, and a free desk ("+", a new agent in that project).
// The rooms sit in a building (a corridor of grey tiles). The room grows with its agents: the desks fill a grid of 2-5 columns, the last row completed by a plant, a water
// cooler or a bookshelf. Status, game-style: a working agent bobs and its monitor glows, "!" when it waits for your OK,
// a green bubble with the number of new results, a red screen when the last run failed, "z z" and a dark screen when
// it is off. Everything is drawn with SVG rects on a pixel grid (crisp at 3 or 4 CSS px per pixel), no image, no lib.
// Click (or Enter on) a desk = open the agent. Animations stop under prefers-reduced-motion (globals.css).
import * as React from 'react'
import { useNavigate } from 'react-router'
import { useLang, useT } from '@/i18n'
import { agentRoute, useWorkspace } from '@/lib/queries'
import type { Agent } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Sensitive, StatusDot, Tooltip, useMask } from '@/components/ui'
import { useMediaQuery } from '@/stores/media'
import { AgentAvatarIcon, INK, OUTFIT, projectColor } from './Avatar'
import { statusOf, type Status } from './parts'
import type { CreateStart } from './CreateAgent'

/** A desk cell is W x H pixels of art. */
const W = 30
const H = 30
const GAP = 2

// Fixed game palette (the same in both themes, like the sprites of a game); rooms take the theme through color-mix.
const WOOD = { hi: '#f0c48c', top: '#dea56a', edge: '#9a6436', front: '#b8804a', drawer: '#c99158', knob: '#f6d9a8', dark: '#6b4322' }
const CHAIR = { back: '#4b4560', hi: '#635b7e' }
const METAL = { bezel: '#3b3648', stand: '#77728c' }
const SCREEN: Record<Status['id'] | 'free', { bg: string; ink: string }> = {
  idle: { bg: '#25405e', ink: '#5d8fc4' },
  unread: { bg: '#1f4a3a', ink: '#5fd38d' },
  running: { bg: '#0f4256', ink: '#8ff3ff' },
  waiting: { bg: '#4f3c08', ink: '#ffd34d' },
  failed: { bg: '#7a1c1c', ink: '#ff8a7a' },
  off: { bg: '#18171e', ink: '#2b2935' },
  free: { bg: '#25405e', ink: '#9fc2e8' },
}

const px = (x: number, y: number, w: number, h: number, fill: string, k?: string) => <rect key={k ?? `${x}.${y}.${w}.${h}`} x={x} y={y} width={w} height={h} fill={fill} />

/** A small stable number from a string (which decoration sits on which desk). */
const hash = (s: string) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7)

/** How many desk columns a room gets for `n` cells (2-5, growing with the room); fewer on a phone. */
const colsFor = (n: number, phone: boolean) => Math.min(phone ? 3 : 5, Math.max(2, Math.ceil(Math.sqrt(n * 1.8))))

export function OfficeGame({ groups, onStart }: { groups: [string, Agent[]][]; onStart: (s: CreateStart) => void }) {
  const phone = useMediaQuery('(max-width: 639px)')
  const s = phone ? 3 : 4
  return (
    // The building: a corridor of neutral tiles around the rooms.
    <div
      className="flex flex-wrap items-start gap-6 border-[3px] border-[#2a2433]/70 p-4 max-sm:justify-center max-sm:gap-4 max-sm:p-2.5 dark:border-black"
      style={{
        backgroundImage: 'repeating-conic-gradient(color-mix(in oklab, var(--muted-foreground) 9%, var(--background)) 0 25%, color-mix(in oklab, var(--muted-foreground) 14%, var(--background)) 0 50%)',
        backgroundSize: `${4 * s}px ${4 * s}px`,
      }}
      data-testid="agents-office-game"
    >
      {groups.map(([p, list]) => (
        <Room key={p} project={p} agents={list} s={s} phone={phone} onStart={onStart} />
      ))}
    </div>
  )
}

function Room({ project, agents, s, phone, onStart }: { project: string; agents: Agent[]; s: number; phone: boolean; onStart: (s: CreateStart) => void }) {
  const t = useT()
  const mask = useMask()
  const { data: ws } = useWorkspace()
  const emoji = ws?.projects.find((x) => x.name === project)?.emoji || ''
  const c = OUTFIT[projectColor(project)]
  const cells = agents.length + 1
  const cols = colsFor(cells, phone)
  const fillers = (cols - (cells % cols)) % cols
  // The free desk goes to the topic most of the room's agents live in (the sheet lets the user change it).
  const topic = React.useMemo(() => {
    const n = new Map<string, number>()
    for (const a of agents) n.set(a.topic, (n.get(a.topic) || 0) + 1)
    return [...n.entries()].sort((x, y) => y[1] - x[1])[0]?.[0]
  }, [agents])
  const wallH = 15 * s
  const style = {
    '--room': c,
    '--wall': `color-mix(in oklab, ${c} 34%, var(--card))`,
    '--wall-2': `color-mix(in oklab, ${c} 42%, var(--card))`,
    '--wainscot': `color-mix(in oklab, ${c} 55%, ${INK})`,
    '--tile-a': `color-mix(in oklab, ${c} 13%, var(--background))`,
    '--tile-b': `color-mix(in oklab, ${c} 21%, var(--background))`,
    '--s': `${s}px`,
  } as React.CSSProperties
  return (
    <section
      aria-label={mask(project, 8)}
      className="relative w-fit max-w-full border-[3px] border-[#2a2433] shadow-[0_6px_0_0_rgba(0,0,0,0.22)] dark:border-black"
      style={style}
      data-testid="office-room"
    >
      {/* The wall: striped wallpaper, a darker wainscot and a baseboard; the sign on the left, windows, a clock. */}
      <div
        className="relative flex items-start gap-3 overflow-hidden px-3"
        style={{
          height: wallH,
          background: `linear-gradient(to bottom, transparent ${wallH - 4 * s}px, var(--wainscot) ${wallH - 4 * s}px, var(--wainscot) ${wallH - s}px, ${INK} ${wallH - s}px), repeating-linear-gradient(90deg, var(--wall) 0 ${2 * s}px, var(--wall-2) ${2 * s}px ${4 * s}px)`,
        }}
      >
        <span className="mt-[calc(var(--s)*2)] flex h-7 max-w-[60%] min-w-0 shrink items-center gap-1.5 border-2 border-[#2a2433] bg-[#8c5a2f] px-2 text-xs font-bold text-[#fbe7c6] shadow-[0_3px_0_0_rgba(0,0,0,0.3)]">
          {emoji && <span aria-hidden>{emoji}</span>}
          <span className="truncate">
            <Sensitive length={8}>{project}</Sensitive>
          </span>
          <span className="shrink-0 font-semibold tabular-nums opacity-75">{agents.length}</span>
        </span>
        <span className="flex min-w-0 flex-1 justify-center gap-4 overflow-hidden pt-[calc(var(--s)*1.5)]" aria-hidden>
          {Array.from({ length: Math.max(1, cols - 2) }, (_, i) => (
            <Window key={i} s={s} />
          ))}
        </span>
        <span className="pt-[calc(var(--s)*2)]" aria-hidden>
          <Clock s={s} />
        </span>
      </div>
      {/* The floor: checker tiles; desks in rows, then the decorations completing the last row. */}
      <div
        className="grid p-3 pt-2"
        style={{
          gridTemplateColumns: `repeat(${cols}, ${W * s}px)`,
          // rows further apart: the bubbles above the heads stay clear of the name plates
          gap: `${GAP * s + 12}px ${GAP * s}px`,
          backgroundImage: 'repeating-conic-gradient(var(--tile-a) 0 25%, var(--tile-b) 0 50%)',
          backgroundSize: `${8 * s}px ${8 * s}px`,
        }}
      >
        {agents.map((a) => (
          <Desk key={a.path} agent={a} s={s} />
        ))}
        <FreeDesk s={s} label={t('agents.office.freeDesk')} onClick={() => onStart(topic ? { topic: `projects/${project}/topics/${topic}` } : {})} />
        {Array.from({ length: fillers }, (_, i) => (
          <Filler key={i} kind={(hash(project) + i) % 3} s={s} />
        ))}
      </div>
    </section>
  )
}

/** One agent at its desk; the whole cell opens it. */
function Desk({ agent: a, s }: { agent: Agent; s: number }) {
  const t = useT()
  const lang = useLang()
  const navigate = useNavigate()
  const st = statusOf(a, t, lang)
  const open = () => navigate(agentRoute(a))
  const working = st.id === 'running'
  const off = st.id === 'off'
  return (
    <Tooltip content={`${a.display_name} · ${st.text}`}>
      <div
        role="link"
        tabIndex={0}
        aria-label={`${t('agents.overview.open', { name: a.display_name })} · ${st.text}`}
        onClick={open}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget && (e.preventDefault(), open())}
        className="group/desk relative grid cursor-pointer justify-items-center outline-none"
        data-testid="office-desk"
        data-state={st.id}
      >
        <Cursor />
        <div className="relative" style={{ width: W * s, height: H * s }}>
          <Chair s={s} />
          <span className={cn('absolute', working && 'mx-game-bob', off && 'opacity-80')} style={{ left: 3 * s, top: s }}>
            <AgentAvatarIcon avatar={a.avatar} size={16 * s} tile={false} mood={off ? 'sleep' : 'idle'} animate={!off} />
          </span>
          <DeskFront s={s} screen={st.id} decor={hash(a.path) % 4} />
          <StatusBubble agent={a} status={st} s={s} />
        </div>
        <Plate dot={<StatusDot tone={st.tone} pulse={st.pulse} className="size-1.5" />} dim={off}>
          <Sensitive length={8}>{a.display_name}</Sensitive>
        </Plate>
      </div>
    </Tooltip>
  )
}

/** The empty desk at the end of a room: a new agent in this project. */
function FreeDesk({ s, label, onClick }: { s: number; label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} className="group/desk relative grid cursor-pointer justify-items-center outline-none" data-testid="office-free-desk">
      <Cursor />
      <div className="relative opacity-70 transition-opacity group-hover/desk:opacity-100 group-focus-visible/desk:opacity-100" style={{ width: W * s, height: H * s }}>
        <Chair s={s} />
        <DeskFront s={s} screen="free" decor={-1} />
        <span
          className="absolute grid place-items-center border-2 border-dashed border-[#2a2433]/60 bg-white/50 font-mono font-bold text-[#2a2433] dark:border-white/50 dark:bg-black/30 dark:text-white"
          style={{ left: 6 * s, top: 5 * s, width: 9 * s, height: 9 * s, fontSize: 6 * s, lineHeight: 1 }}
          aria-hidden
        >
          +
        </span>
      </div>
      <Plate dashed>{label}</Plate>
    </button>
  )
}

/** Corner brackets around the hovered / focused desk, like the selection cursor of a game. */
function Cursor() {
  const b = 'absolute size-2.5 border-primary opacity-0 transition-opacity group-hover/desk:opacity-100 group-focus-visible/desk:opacity-100'
  return (
    <span aria-hidden className="pointer-events-none absolute -inset-1">
      <i className={cn(b, 'top-0 left-0 border-t-[3px] border-l-[3px]')} />
      <i className={cn(b, 'top-0 right-0 border-t-[3px] border-r-[3px]')} />
      <i className={cn(b, 'bottom-0 left-0 border-b-[3px] border-l-[3px]')} />
      <i className={cn(b, 'right-0 bottom-0 border-r-[3px] border-b-[3px]')} />
    </span>
  )
}

/** The name plate under a desk. */
function Plate({ children, dot, dim, dashed }: { children: React.ReactNode; dot?: React.ReactNode; dim?: boolean; dashed?: boolean }) {
  return (
    <span
      className={cn(
        'relative -mt-1 flex h-5 max-w-full min-w-0 items-center gap-1 border-2 px-1.5 text-[11px] leading-none font-semibold shadow-[0_2px_0_0_rgba(0,0,0,0.25)]',
        dashed ? 'border-dashed border-[#2a2433]/50 bg-[#f6ead0]/70 text-[#2a2433]/80 dark:border-white/40 dark:bg-black/30 dark:text-white/80' : 'border-[#2a2433] bg-[#f6ead0] text-[#2a2433]',
        dim && 'text-[#2a2433]/60',
      )}
    >
      {dot}
      <span className="truncate">{children}</span>
    </span>
  )
}

/** The back of the chair, behind the character. */
function Chair({ s }: { s: number }) {
  return (
    <svg aria-hidden viewBox={`0 0 ${W} ${H}`} width={W * s} height={H * s} shapeRendering="crispEdges" className="pointer-events-none absolute inset-0">
      {px(4, 7, 14, 10, INK)}
      {px(5, 8, 12, 8, CHAIR.back)}
      {px(5, 8, 12, 1, CHAIR.hi)}
      {px(9, 26, 4, 2, INK)}
    </svg>
  )
}

/** The desk in front of the character: its top, front and drawer, a keyboard, the monitor (its screen tells the
 *  state) and one small thing on the left (a plant, a mug, books or a lamp; none on the free desk). */
function DeskFront({ s, screen, decor }: { s: number; screen: keyof typeof SCREEN; decor: number }) {
  const sc = SCREEN[screen]
  const lit = screen === 'running'
  return (
    <svg aria-hidden viewBox={`0 0 ${W} ${H}`} width={W * s} height={H * s} shapeRendering="crispEdges" className="pointer-events-none absolute inset-0 overflow-visible">
      {/* desk */}
      {px(0, 16, 30, 10, INK)}
      {px(1, 17, 28, 3, WOOD.top)}
      {px(1, 17, 28, 1, WOOD.hi)}
      {px(1, 20, 28, 1, WOOD.edge)}
      {px(1, 21, 28, 4, WOOD.front)}
      {px(3, 21, 14, 4, WOOD.dark)}
      {px(19, 21, 8, 3, WOOD.drawer)}
      {px(22, 22, 2, 1, WOOD.knob)}
      {px(1, 26, 3, 2, INK)}
      {px(26, 26, 3, 2, INK)}
      {px(2, 28, 26, 1, 'rgba(0,0,0,0.16)')}
      {/* keyboard */}
      {screen !== 'free' && px(6, 18, 9, 1, '#d9d6e3')}
      {screen !== 'free' && px(6, 19, 9, 1, '#9f9bb0')}
      {/* monitor */}
      {lit && <rect x={18} y={6} width={10} height={9} fill={sc.ink} className="mx-game-glow" />}
      {px(17, 5, 12, 11, INK)}
      {px(18, 6, 10, 9, METAL.bezel)}
      {px(19, 7, 8, 7, sc.bg)}
      <Screen id={screen} ink={sc.ink} />
      {px(22, 16, 2, 1, METAL.stand)}
      {px(20, 17, 6, 1, METAL.stand)}
      {decor >= 0 && <Decor kind={decor} />}
    </svg>
  )
}

/** What the screen shows (inside x 19-26, y 7-13). */
function Screen({ id, ink }: { id: keyof typeof SCREEN; ink: string }) {
  if (id === 'off') return null
  if (id === 'failed')
    return (
      <g fill={ink}>
        {[0, 1, 2, 3, 4].map((i) => (
          <React.Fragment key={i}>
            <rect x={20 + i} y={8 + i} width={1} height={1} />
            <rect x={24 - i} y={8 + i} width={1} height={1} />
          </React.Fragment>
        ))}
      </g>
    )
  if (id === 'waiting')
    return (
      <g fill={ink} className="mx-game-blink">
        <rect x={22} y={8} width={2} height={3} />
        <rect x={22} y={12} width={2} height={1} />
      </g>
    )
  if (id === 'free') return null
  // Lines of text; while it works they scroll.
  return (
    <g fill={ink} className={id === 'running' ? 'mx-game-type' : undefined}>
      <rect x={20} y={8} width={4} height={1} />
      <rect x={20} y={10} width={6} height={1} />
      <rect x={20} y={12} width={3} height={1} />
      {id === 'unread' && <rect x={25} y={8} width={1} height={1} fill="#ffffff" />}
    </g>
  )
}

/** One small thing on the left of the desk top (x 1-4). */
function Decor({ kind }: { kind: number }) {
  if (kind === 0)
    // a plant in a pot
    return (
      <g>
        {px(1, 13, 4, 4, INK)}
        {px(2, 14, 2, 2, '#c4643c')}
        {px(1, 10, 1, 3, '#3f9a4a')}
        {px(2, 8, 2, 5, '#5cc45e')}
        {px(4, 9, 1, 3, '#3f9a4a')}
      </g>
    )
  if (kind === 1)
    // a mug
    return (
      <g>
        {px(1, 13, 4, 4, INK)}
        {px(2, 14, 2, 2, '#d04f4f')}
        {px(2, 14, 2, 1, '#e87a6a')}
        {px(0, 14, 1, 2, INK)}
      </g>
    )
  if (kind === 2)
    // a stack of books
    return (
      <g>
        {px(1, 14, 4, 1, '#d04f4f')}
        {px(1, 15, 4, 1, '#3d7bd6')}
        {px(1, 16, 4, 1, '#e3b341')}
      </g>
    )
  // a lamp
  return (
    <g>
      {px(2, 16, 3, 1, INK)}
      {px(3, 12, 1, 4, '#77728c')}
      {px(1, 10, 4, 2, '#e3b341')}
      {px(1, 12, 4, 1, 'rgba(255,230,140,0.5)')}
    </g>
  )
}

/** The game-style bubble above the head: "..." working, "!" waiting for an OK, new results, "z z" off. */
function StatusBubble({ agent: a, status: st, s }: { agent: Agent; status: Status; s: number }) {
  const pos = { left: 11 * s, top: 2 * s }
  if (st.id === 'off')
    return (
      <span aria-hidden className="absolute flex -translate-y-full items-end gap-0.5 font-mono leading-none font-bold text-[#5b5470] dark:text-[#c9c3dc]" style={{ left: 13 * s, top: 4 * s }}>
        <span className="mx-game-zzz text-[11px]">z</span>
        <span className="mx-game-zzz text-[14px] [animation-delay:0.6s]">Z</span>
      </span>
    )
  const cls =
    st.id === 'waiting'
      ? 'bg-[#ffd34d] text-[#2a2433] mx-game-hop'
      : st.id === 'unread'
        ? 'bg-[#3fb950] text-white'
        : st.id === 'running'
          ? 'bg-white text-[#2a2433] mx-px-dots'
          : ''
  if (!cls) return null
  return (
    <span aria-hidden className="absolute z-10 -translate-x-1/2 -translate-y-full" style={pos}>
      <span className={cn('flex h-5 min-w-5 items-center justify-center gap-0.5 border-2 border-[#2a2433] px-1 font-mono text-[12px] leading-none font-bold tabular-nums shadow-[2px_2px_0_0_rgba(0,0,0,0.25)]', cls)}>
        {st.id === 'waiting' ? '!' : st.id === 'unread' ? a.thread_unread : (
          <>
            <i className="size-1 bg-[#2a2433]" />
            <i className="size-1 bg-[#2a2433]" />
            <i className="size-1 bg-[#2a2433]" />
          </>
        )}
      </span>
      {/* the tail, two steps of pixels */}
      <svg viewBox="0 0 4 2" width={8} height={4} shapeRendering="crispEdges" className="mx-auto -mt-0.5 block">
        <rect x={0} y={0} width={1} height={1} fill="#2a2433" />
        <rect x={1} y={0} width={2} height={1} fill={st.id === 'waiting' ? '#ffd34d' : st.id === 'unread' ? '#3fb950' : '#ffffff'} />
        <rect x={3} y={0} width={1} height={1} fill="#2a2433" />
        <rect x={1} y={1} width={2} height={1} fill="#2a2433" />
      </svg>
    </span>
  )
}

/** A window on the wall: frame, sky, a cloud. */
function Window({ s }: { s: number }) {
  return (
    <svg viewBox="0 0 14 9" width={14 * s} height={9 * s} shapeRendering="crispEdges" className="shrink-0">
      {px(0, 0, 14, 9, INK)}
      {px(1, 1, 12, 7, '#f0e2c4')}
      {px(2, 2, 4, 5, '#8fd0f5')}
      {px(8, 2, 4, 5, '#8fd0f5')}
      {px(2, 2, 4, 1, '#b8e4fb')}
      {px(8, 2, 4, 1, '#b8e4fb')}
      {px(3, 4, 2, 1, '#ffffff')}
      {px(9, 5, 2, 1, '#ffffff')}
      {px(0, 8, 14, 1, '#8c5a2f')}
    </svg>
  )
}

/** A round clock on the wall. */
function Clock({ s }: { s: number }) {
  return (
    <svg viewBox="0 0 7 7" width={7 * s} height={7 * s} shapeRendering="crispEdges" className="shrink-0">
      {px(2, 0, 3, 1, INK)}
      {px(1, 1, 5, 5, INK)}
      {px(0, 2, 7, 3, INK)}
      {px(2, 6, 3, 1, INK)}
      {px(2, 1, 3, 5, '#fbf6ea')}
      {px(1, 2, 5, 3, '#fbf6ea')}
      {px(3, 2, 1, 2, INK)}
      {px(4, 3, 1, 1, '#d04f4f')}
    </svg>
  )
}

/** What completes the last row of a room: a tall plant, a water cooler or a bookshelf. */
function Filler({ kind, s }: { kind: number; s: number }) {
  return (
    <div aria-hidden className="grid justify-items-center" style={{ width: W * s }}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W * s} height={H * s} shapeRendering="crispEdges">
        {kind === 0 ? (
          // a tall plant
          <g>
            {px(10, 20, 10, 8, INK)}
            {px(11, 21, 8, 6, '#c4643c')}
            {px(11, 21, 8, 1, '#dd7e52')}
            {px(14, 8, 2, 12, '#2f7d3a')}
            {px(9, 9, 5, 4, '#5cc45e')}
            {px(16, 6, 5, 4, '#5cc45e')}
            {px(8, 14, 6, 4, '#3f9a4a')}
            {px(16, 12, 6, 5, '#3f9a4a')}
            {px(12, 4, 4, 4, '#6fd46f')}
            {px(10, 28, 10, 1, 'rgba(0,0,0,0.16)')}
          </g>
        ) : kind === 1 ? (
          // a water cooler
          <g>
            {px(11, 4, 8, 9, INK)}
            {px(12, 5, 6, 7, '#9ad7f2')}
            {px(13, 6, 1, 4, '#d4f0fb')}
            {px(10, 13, 10, 15, INK)}
            {px(11, 14, 8, 13, '#e7e4ee')}
            {px(13, 17, 2, 1, '#3d7bd6')}
            {px(16, 17, 2, 1, '#d04f4f')}
            {px(10, 28, 10, 1, 'rgba(0,0,0,0.16)')}
          </g>
        ) : (
          // a bookshelf
          <g>
            {px(5, 6, 20, 22, INK)}
            {px(6, 7, 18, 20, WOOD.front)}
            {px(6, 13, 18, 1, WOOD.dark)}
            {px(6, 20, 18, 1, WOOD.dark)}
            {[['#d04f4f', 7], ['#3d7bd6', 9], ['#e3b341', 11], ['#5cc45e', 14], ['#a26bd6', 16]].map(([c, x]) => px(x as number, 8, 2, 5, c as string, `a${x}`))}
            {[['#3d7bd6', 8], ['#e3b341', 10], ['#d04f4f', 15], ['#5cc45e', 18], ['#3d7bd6', 20]].map(([c, x]) => px(x as number, 15, 2, 5, c as string, `b${x}`))}
            {[['#a26bd6', 7], ['#5cc45e', 9], ['#d04f4f', 19], ['#e3b341', 21]].map(([c, x]) => px(x as number, 22, 2, 5, c as string, `c${x}`))}
            {px(5, 28, 20, 1, 'rgba(0,0,0,0.16)')}
          </g>
        )}
      </svg>
    </div>
  )
}
