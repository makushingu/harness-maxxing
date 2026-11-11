// The Space view of the Office (AgentsOverview, picked in its view menu): a pixel-art office on a space station. One bay per project, its edges glowing in the project colour; its wall
// is a long window on space (drifting stars, a planet of the project colour) with a holographic sign (emoji, name,
// count, the "..." menu); the floor is dark metal plates with a grid. One hover-console per agent: a pod chair, the
// character, a floating holographic screen projected from the desk (its colour and drawing tell the state) and LEDs
// on the front; a free console ("+", a new agent in that project); the last row completed by a server rack, a little
// robot or a bio-pod. Status: a working agent bobs and its screen glows (screens never move), "!" when it waits for your
// OK, a green chip with the number of new results, a red glitching screen when the last run failed, "z Z" and no
// screen when it is off. Mostly dark in both themes, like a game scene. Shared with the views to come (office.tsx:
// click / Enter opens, drag and drop and the project menu through layout.tsx). Animations stop under
// prefers-reduced-motion (globals.css), at rest.
import * as React from 'react'
import { useT } from '@/i18n'
import type { Agent } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Sensitive, StatusDot, Tooltip, useMask } from '@/components/ui'
import { useMediaQuery } from '@/stores/media'
import { AgentAvatarIcon } from './Avatar'
import { DropBar, ProjectMenu, type AgentsLayoutApi, type ProjectGroup } from './layout'
import type { Status } from './parts'
import { WaitingBubble } from './approvals'
import type { CreateStart } from './CreateAgent'
import { colsFor, Cursor, hash, useDesk, useRoom } from './office'

/** A console cell is W x H pixels of art . */
const W = 30
const H = 30
const GAP = 2

// The station's palette (the same in both themes); the project colour comes on top for the edges, lights and plates.
const HULL = { void: '#060914', deep: '#0a1020', plate: '#101830', plate2: '#0d1428', seam: '#1c2744', ink: '#04060d' }
const STEEL = { hi: '#7d8bb3', top: '#4a5780', mid: '#2c3657', dark: '#1a2240', low: '#121931' }
const HOLO: Record<Status['id'] | 'free', string> = {
  idle: '#5ee7ff',
  unread: '#5dffa8',
  running: '#9ff8ff',
  waiting: '#ffcc4d',
  failed: '#ff5f6d',
  off: '#3a4466',
  free: '#5ee7ff',
}

const px = (x: number, y: number, w: number, h: number, fill: string, k?: string, o?: number) => (
  <rect key={k ?? `${x}.${y}.${w}.${h}.${fill}`} x={x} y={y} width={w} height={h} fill={fill} fillOpacity={o} />
)

/** A tile of stars (pixels of 1 x 1) repeated on the window to space; two layers drift at two speeds. */
const starTile = (stars: [number, number, string][], w: number, h: number) =>
  `url("data:image/svg+xml,${encodeURIComponent(
    `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 ${w} ${h}' width='${w}' height='${h}' shape-rendering='crispEdges'>${stars.map(([x, y, c]) => `<rect x='${x}' y='${y}' width='1' height='1' fill='${c}'/>`).join('')}</svg>`,
  )}")`
const FAR = starTile([[3, 2, '#8aa0d6'], [17, 7, '#6c7fb0'], [29, 3, '#9fb4e8'], [41, 11, '#6c7fb0'], [9, 13, '#8aa0d6'], [35, 15, '#5a6b99'], [23, 12, '#7f93c9'], [46, 5, '#5a6b99']], 48, 16)
// The station's own sky: sparse, uneven, dim (the bays stay the bright part).
const SKY = starTile([[7, 5, '#6c7fb0'], [38, 2, '#9fb4e8'], [61, 17, '#5a6b99'], [83, 9, '#8aa0d6'], [19, 29, '#5a6b99'], [52, 34, '#cfe8ff'], [90, 31, '#6c7fb0'], [70, 25, '#4d5d88'], [29, 16, '#4d5d88']], 96, 40)
const NEAR = starTile([[6, 4, '#ffffff'], [27, 10, '#dff6ff'], [44, 2, '#ffffff'], [60, 13, '#cfe8ff']], 64, 16)

/** LEDs blink in two shared rhythms (a page of desks would otherwise be hundreds of animations out of step, each
 *  change repainting the office). */
const ledClass = (g: number) => (g ? 'mx-future-led mx-future-led-b' : 'mx-future-led')

export function OfficeFuture({ groups, layout, onStart }: { groups: ProjectGroup[]; layout: AgentsLayoutApi; onStart: (s: CreateStart) => void }) {
  const phone = useMediaQuery('(max-width: 639px)')
  const s = phone ? 3 : 4
  // Every loop of every LED, glow and hologram fires an `animationiteration` event that bubbles up to React's root
  // listener (a hundred a second on a full office): stop them here, nothing in the office listens to them.
  const root = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    const el = root.current
    const stop = (e: Event) => e.stopPropagation()
    el?.addEventListener('animationiteration', stop)
    return () => el?.removeEventListener('animationiteration', stop)
  }, [])
  return (
    // The station: deep space with a faint grid, the bays docked in it.
    <div
      ref={root}
      className="flex flex-wrap items-start gap-6 rounded-xl border border-[#1c2744] p-4 shadow-[inset_0_0_60px_rgba(94,231,255,0.06)] max-sm:justify-center max-sm:gap-4 max-sm:p-2.5"
      style={{
        backgroundColor: HULL.void,
        backgroundImage: `${SKY}, linear-gradient(rgba(94,231,255,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(94,231,255,0.035) 1px, transparent 1px)`,
        backgroundSize: `${96 * s}px ${40 * s}px, ${16 * s}px ${16 * s}px, ${16 * s}px ${16 * s}px`,
        imageRendering: 'pixelated',
      }}
      data-testid="agents-office-future"
    >
      {groups.map(({ project: p, agents: list }, i) => (
        <Bay key={p} project={p} agents={list} index={i} layout={layout} s={s} phone={phone} onStart={onStart} />
      ))}
    </div>
  )
}

/**
 * One bay alone, read-only, for the sidebar's agent preview card (AgentPreview.tsx): the room of `project` with
 * `agents` at their consoles, `focus` (an agent path) under the selection cursor. At most 3 consoles a row (the
 * phone grid), smaller pixels for 3; `inert`: nothing in it takes a pointer, the focus or a screen reader (the card says
 * it in words).
 */
export function OfficeRoom({ project, agents, focus, layout }: { project: string; agents: Agent[]; focus?: string; layout: AgentsLayoutApi }) {
  // the Office's own pixel size while two consoles a row fit the card, smaller for three
  const s = colsFor(agents.length, true) <= 2 ? 4 : 3
  return (
    <div
      inert
      className="flex justify-center p-2.5"
      style={{
        backgroundColor: HULL.void,
        backgroundImage: `${SKY}, linear-gradient(rgba(94,231,255,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(94,231,255,0.035) 1px, transparent 1px)`,
        backgroundSize: `${96 * s}px ${40 * s}px, ${16 * s}px ${16 * s}px, ${16 * s}px ${16 * s}px`,
        imageRendering: 'pixelated',
      }}
      data-testid="office-room-preview"
    >
      <Bay project={project} agents={agents} index={0} layout={layout} s={s} phone onStart={() => {}} focus={focus} />
    </div>
  )
}

function Bay({ project, agents, index, layout, s, phone, onStart, focus }: { project: string; agents: Agent[]; index: number; layout: AgentsLayoutApi; s: number; phone: boolean; onStart: (s: CreateStart) => void; focus?: string }) {
  const t = useT()
  const mask = useMask()
  const room = useRoom(project, agents, index, layout, phone, onStart)
  const { dnd, emoji, color: c, create } = room
  // The preview (a `focus` given) keeps its rows short: the free desk only where the last row has room for it.
  const previewCols = colsFor(agents.length, true)
  const free = focus === undefined || agents.length % previewCols !== 0
  const cols = focus === undefined ? room.cols : previewCols
  const fillers = focus === undefined ? room.fillers : free ? (cols - ((agents.length + 1) % cols)) % cols : 0
  const wallH = 15 * s
  const style = {
    '--bay': c,
    '--s': `${s}px`,
    '--sw-far': `${48 * s}px`,
    '--sw-near': `${64 * s}px`,
    borderColor: c,
    boxShadow: `0 0 0 2px ${HULL.ink}, 0 0 18px color-mix(in oklab, ${c} 45%, transparent), inset 0 0 22px color-mix(in oklab, ${c} 18%, transparent)`,
  } as React.CSSProperties
  return (
    <section
      {...dnd.target}
      aria-label={mask(project, 8)}
      className={cn('relative w-fit max-w-full border-2', dnd.dragging && 'opacity-50')}
      style={style}
      data-testid="office-room"
      data-project={project}
    >
      <DropBar side={dnd.side} vertical={false} />
      {/* The wall: metal panels, a long window on space (stars drifting, a planet of the project colour), the
          holographic sign on the left and a panel of LEDs on the right. The wall is the handle that moves the bay. */}
      <div
        {...dnd.source}
        title={dnd.on ? t('agents.layout.dragProject') : undefined}
        data-testid="office-room-wall"
        className={cn('relative flex items-start gap-3 overflow-hidden px-3', dnd.on && 'cursor-grab active:cursor-grabbing')}
        style={{
          height: wallH,
          background: `linear-gradient(to bottom, transparent ${wallH - 3 * s}px, ${HULL.seam} ${wallH - 3 * s}px, ${HULL.seam} ${wallH - 2 * s}px, color-mix(in oklab, ${c} 75%, black) ${wallH - 2 * s}px, color-mix(in oklab, ${c} 75%, black) ${wallH - s}px, ${HULL.ink} ${wallH - s}px), repeating-linear-gradient(90deg, ${HULL.plate} 0 ${10 * s}px, ${HULL.seam} ${10 * s}px ${10 * s + 1}px)`,
        }}
      >
        <Viewport s={s} color={c} seed={hash(project)} />
        <span
          className="relative mt-[calc(var(--s)*2)] flex h-7 max-w-[60%] min-w-0 shrink items-center gap-1.5 border px-2 font-mono text-[11px] font-bold tracking-wider uppercase backdrop-blur-[1px]"
          style={{
            borderColor: c,
            color: `color-mix(in oklab, ${c} 35%, white)`,
            backgroundColor: `color-mix(in oklab, ${c} 16%, rgba(6,9,20,0.78))`,
            boxShadow: `0 0 10px color-mix(in oklab, ${c} 40%, transparent), inset 0 0 8px color-mix(in oklab, ${c} 25%, transparent)`,
            textShadow: `0 0 6px color-mix(in oklab, ${c} 70%, transparent)`,
          }}
        >
          {emoji && <span aria-hidden>{emoji}</span>}
          <span className="truncate">
            <Sensitive length={8}>{project}</Sensitive>
          </span>
          <span className="shrink-0 tabular-nums opacity-75">{agents.length}</span>
          <ProjectMenu project={project} layout={layout} among={layout.projects} className="-mr-1 size-5 text-current hover:bg-white/10 hover:text-white data-[state=open]:bg-white/10 data-[state=open]:text-white" />
        </span>
        <span className="flex-1" aria-hidden />
        <span className="relative pt-[calc(var(--s)*2)]" aria-hidden>
          <Leds s={s} color={c} seed={hash(project)} />
        </span>
      </div>
      {/* The floor: dark metal plates with a grid of the project colour; consoles in rows, then the fillers. */}
      <div
        className="grid p-3 pt-2"
        style={{
          gridTemplateColumns: `repeat(${cols}, ${W * s}px)`,
          gap: `${GAP * s + 12}px ${GAP * s}px`,
          backgroundColor: HULL.deep,
          backgroundImage: `linear-gradient(color-mix(in oklab, ${c} 16%, transparent) 1px, transparent 1px), linear-gradient(90deg, color-mix(in oklab, ${c} 16%, transparent) 1px, transparent 1px), repeating-conic-gradient(${HULL.plate} 0 25%, ${HULL.plate2} 0 50%)`,
          backgroundSize: `${8 * s}px ${8 * s}px, ${8 * s}px ${8 * s}px, ${16 * s}px ${16 * s}px`,
        }}
      >
        {agents.map((a, i) => (
          <Console key={a.path} agent={a} index={i} layout={layout} s={s} color={c} active={a.path === focus} />
        ))}
        {free && <FreeConsole s={s} color={c} label={t('agents.office.freeDesk')} onClick={create} />}
        {Array.from({ length: fillers }, (_, i) => (
          <Filler key={i} kind={(hash(project) + i) % 3} s={s} color={c} />
        ))}
      </div>
    </section>
  )
}

/** The window on space behind the sign: two layers of stars drifting at their own speed and a ringed planet. */
function Viewport({ s, color, seed }: { s: number; color: string; seed: number }) {
  const x = 30 + (seed % 40)
  return (
    <span
      aria-hidden
      className="pointer-events-none absolute inset-x-[calc(var(--s)*2)] top-[calc(var(--s)*1)] overflow-hidden border"
      style={{ height: 10 * s, borderColor: STEEL.dark, boxShadow: `inset 0 0 0 1px ${HULL.ink}, inset 0 0 14px rgba(0,0,0,0.8)`, backgroundColor: '#03050c' }}
    >
      {/* Each layer is wider than the window by its drift and slides with a transform (drawn by the GPU, no repaint). */}
      {[
        [FAR, 'var(--sw-far)', 2],
        [NEAR, 'var(--sw-near)', 4],
      ].map(([tile, w, n]) => (
        <span
          key={n}
          className="mx-future-stars absolute inset-y-0 left-0"
          style={{ '--d': `calc(${w} * ${n})`, width: `calc(100% + ${w} * ${n})`, backgroundImage: tile, backgroundSize: `${w} ${16 * s}px`, imageRendering: 'pixelated' } as React.CSSProperties}
        />
      ))}
      <svg viewBox="0 0 16 10" width={16 * s} height={10 * s} shapeRendering="crispEdges" className="absolute top-0" style={{ left: `${x}%` }}>
        {/* a planet in the project colour, lit from the left, with a ring */}
        {px(5, 2, 5, 1, color)}
        {px(4, 3, 7, 4, color)}
        {px(5, 7, 5, 1, color)}
        {px(5, 3, 2, 2, '#ffffff', 'lit', 0.35)}
        {px(8, 4, 3, 4, '#000000', 'shade', 0.35)}
        {px(1, 5, 14, 1, '#d8e6ff', 'ring', 0.55)}
        {px(2, 6, 2, 1, '#d8e6ff', 'ring2', 0.35)}
        {px(12, 4, 2, 1, '#d8e6ff', 'ring3', 0.35)}
      </svg>
    </span>
  )
}

/** A small panel of blinking LEDs on the wall (their rhythm differs from bay to bay). */
function Leds({ s, color, seed }: { s: number; color: string; seed: number }) {
  const lights = [color, '#5dffa8', color, '#ffcc4d', '#5ee7ff', color]
  return (
    <svg viewBox="0 0 9 7" width={9 * s} height={7 * s} shapeRendering="crispEdges" className="shrink-0">
      {px(0, 0, 9, 7, HULL.ink)}
      {px(1, 1, 7, 5, STEEL.low)}
      {/* two groups blinking in turn (which LEDs go together differs from bay to bay) */}
      {[0, 1].map((g) => (
        <g key={g} className={ledClass(g)}>
          {lights.map((c, i) => ((seed + i) % 2 === g ? px(2 + (i % 3) * 2, 2 + Math.floor(i / 3) * 2, 1, 1, c, `l${i}`) : null))}
        </g>
      ))}
    </svg>
  )
}

/** One agent at its console; the whole cell opens it. */
function Console({ agent: a, index, layout, s, color, active }: { agent: Agent; index: number; layout: AgentsLayoutApi; s: number; color: string; active?: boolean }) {
  const { st, dnd, props, menu } = useDesk(a, index, layout)
  const working = st.id === 'running'
  const off = st.id === 'off'
  return (
    <Tooltip content={`${a.display_name} · ${st.text}`}>
      <div {...props} className={cn('group/desk relative grid cursor-pointer justify-items-center outline-none', dnd.dragging && 'opacity-50')} data-testid="office-desk">
        <DropBar side={dnd.side} vertical={false} />
        {menu}
        <Cursor className={cn('border-[#5ee7ff] drop-shadow-[0_0_4px_#5ee7ff]', active && 'opacity-100')} />
        <div className="relative" style={{ width: W * s, height: H * s }}>
          <PodChair s={s} color={color} off={off} />
          <span className={cn('absolute', working && 'mx-game-bob', off && 'opacity-70')} style={{ left: 3 * s, top: s }}>
            <AgentAvatarIcon avatar={a.avatar} size={16 * s} tile={false} mood={off ? 'sleep' : 'idle'} animate={!off} />
          </span>
          <ConsoleFront s={s} color={color} screen={st.id} decor={hash(a.path) % 4} />
          <StatusChip agent={a} status={st} s={s} />
        </div>
        <Plate color={color} dot={<StatusDot tone={st.tone} pulse={st.pulse} className="size-1.5" />} dim={off}>
          <Sensitive length={8}>{a.display_name}</Sensitive>
        </Plate>
      </div>
    </Tooltip>
  )
}

/** The free console at the end of a bay: a new agent in this project. */
function FreeConsole({ s, color, label, onClick }: { s: number; color: string; label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} className="group/desk relative grid cursor-pointer justify-items-center outline-none" data-testid="office-free-desk">
      <Cursor className="border-[#5ee7ff] drop-shadow-[0_0_4px_#5ee7ff]" />
      <div className="relative opacity-75 transition-opacity group-hover/desk:opacity-100 group-focus-visible/desk:opacity-100" style={{ width: W * s, height: H * s }}>
        <PodChair s={s} color={color} off />
        <ConsoleFront s={s} color={color} screen="free" decor={-1} />
        {/* a hologram of "+" where the character would sit */}
        <span
          className="mx-future-holo absolute grid place-items-center border border-dashed font-mono font-bold"
          style={{
            left: 6 * s,
            top: 5 * s,
            width: 9 * s,
            height: 9 * s,
            fontSize: 6 * s,
            lineHeight: 1,
            color: HOLO.free,
            borderColor: HOLO.free,
            backgroundColor: 'rgba(94,231,255,0.12)',
            textShadow: `0 0 6px ${HOLO.free}`,
            boxShadow: '0 0 10px rgba(94,231,255,0.35)',
          }}
          aria-hidden
        >
          +
        </span>
      </div>
      <Plate color={color} dashed>
        {label}
      </Plate>
    </button>
  )
}

/** The name plate under a console: dark glass with a neon edge of the project colour. */
function Plate({ children, color, dot, dim, dashed }: { children: React.ReactNode; color: string; dot?: React.ReactNode; dim?: boolean; dashed?: boolean }) {
  return (
    <span
      // On touch there is no tooltip to read a cut name: up to two lines there.
      className={cn('relative -mt-1 flex h-5 max-w-full min-w-0 items-center gap-1 border px-1.5 font-mono text-[11px] leading-none font-semibold tracking-wide pointer-coarse:h-auto pointer-coarse:min-h-5 pointer-coarse:py-0.5', dashed && 'border-dashed opacity-80')}
      style={{
        borderColor: `color-mix(in oklab, ${color} ${dim ? 40 : 85}%, transparent)`,
        backgroundColor: 'rgba(6,9,20,0.88)',
        color: dim ? '#7f8bb0' : '#dbe8ff',
        boxShadow: dim ? undefined : `0 0 8px color-mix(in oklab, ${color} 35%, transparent)`,
      }}
    >
      {dot}
      <span className="truncate pointer-coarse:line-clamp-2 pointer-coarse:leading-[1.15] pointer-coarse:whitespace-normal pointer-coarse:[overflow-wrap:anywhere]">{children}</span>
    </span>
  )
}

/** The back of the pod chair behind the character: a rounded shell with a light strip of the project colour. */
function PodChair({ s, color, off }: { s: number; color: string; off?: boolean }) {
  return (
    <svg aria-hidden viewBox={`0 0 ${W} ${H}`} width={W * s} height={H * s} shapeRendering="crispEdges" className="pointer-events-none absolute inset-0">
      {px(5, 5, 12, 1, HULL.ink)}
      {px(4, 6, 14, 11, HULL.ink)}
      {px(6, 6, 10, 1, STEEL.mid)}
      {px(5, 7, 12, 9, STEEL.dark)}
      {px(5, 7, 1, 9, STEEL.mid)}
      {px(7, 6, 8, 1, color, 'strip', off ? 0.35 : 0.95)}
      {/* the column under the seat, its foot glowing */}
      {px(10, 26, 2, 1, STEEL.low)}
      {px(8, 27, 6, 1, color, 'foot', off ? 0.2 : 0.5)}
    </svg>
  )
}

/** The hover-console in front of the character: a slab with a neon edge, LEDs on its front, the glow under it, a
 *  light keyboard, the holographic screen above its projector (its colour and drawing tell the state) and one small
 *  thing on the left (a bio-pod, a holo-globe, a cup or a drone; none on the free console). */
function ConsoleFront({ s, color, screen, decor }: { s: number; color: string; screen: keyof typeof HOLO; decor: number }) {
  const ink = HOLO[screen]
  const off = screen === 'off'
  const free = screen === 'free'
  const leds = off ? [HOLO.off, HOLO.off, HOLO.off] : screen === 'failed' ? ['#ff5f6d', '#ff5f6d', '#ff5f6d'] : screen === 'waiting' ? ['#ffcc4d', color, '#5dffa8'] : [color, '#5dffa8', color]
  return (
    <svg aria-hidden viewBox={`0 0 ${W} ${H}`} width={W * s} height={H * s} shapeRendering="crispEdges" className="pointer-events-none absolute inset-0 overflow-visible">
      {/* the glow under the floating console */}
      <g className={off || free ? undefined : 'mx-future-pulse'}>
        {px(4, 25, 22, 1, color, 'g1', off ? 0.12 : 0.35)}
        {px(8, 26, 14, 1, color, 'g2', off ? 0.08 : 0.22)}
      </g>
      {/* slab */}
      {px(0, 16, 30, 8, HULL.ink)}
      {px(1, 16, 28, 1, STEEL.hi)}
      {px(1, 17, 28, 2, STEEL.top)}
      {px(1, 19, 28, 1, color, 'edge', off ? 0.4 : 1)}
      {px(2, 20, 26, 3, STEEL.dark)}
      {px(2, 20, 26, 1, STEEL.mid)}
      {px(4, 23, 22, 1, STEEL.low)}
      {/* LEDs on the front, a vent on the right */}
      {[0, 1].map((g) => (
        <g key={`led${g}`} className={off ? undefined : ledClass(g)}>
          {leds.map((c, i) => (i % 2 === g ? px(4 + i * 2, 21, 1, 1, c, `led${i}`) : null))}
        </g>
      ))}
      {px(19, 21, 7, 1, STEEL.low)}
      {/* keyboard of light */}
      {!free && px(6, 17, 9, 1, '#9ff8ff', 'kb', off ? 0.15 : 0.55)}
      {!free && px(7, 18, 7, 1, '#9ff8ff', 'kb2', off ? 0.1 : 0.3)}
      {/* projector and its beam */}
      {px(21, 15, 4, 1, HULL.ink)}
      {px(22, 15, 2, 1, off ? HOLO.off : ink, 'emit')}
      {!off && px(21, 13, 4, 2, ink, 'beam', 0.14)}
      {!off && px(20, 14, 6, 1, ink, 'beam2', 0.08)}
      {!off && <HoloScreen id={screen} ink={ink} />}
      {decor >= 0 && <Decor kind={decor} color={color} off={off} />}
    </svg>
  )
}

/** The floating screen (x 17-28, y 3-12): translucent, edged with light, scanlines; what it shows tells the state. */
function HoloScreen({ id, ink }: { id: keyof typeof HOLO; ink: string }) {
  const running = id === 'running'
  // The screen stays still (the owner's call): only the glow behind it pulses while the agent works.
  return (
    <g>
      <g>
        {running && <rect x={16} y={2} width={14} height={12} fill={ink} className="mx-game-glow" opacity={0.3} />}
        {px(17, 3, 12, 10, ink, 'fill', 0.16)}
        {/* edges, brighter at the corners */}
        {px(17, 3, 12, 1, ink, 't', 0.75)}
        {px(17, 12, 12, 1, ink, 'b', 0.5)}
        {px(17, 3, 1, 10, ink, 'l', 0.6)}
        {px(28, 3, 1, 10, ink, 'r', 0.6)}
        {px(17, 3, 2, 1, '#ffffff', 'c1', 0.8)}
        {px(27, 12, 2, 1, '#ffffff', 'c2', 0.5)}
        {/* scanlines */}
        {[5, 7, 9, 11].map((y) => px(18, y, 10, 1, '#000000', `sl${y}`, 0.18))}
        <ScreenArt id={id} ink={ink} />
      </g>
    </g>
  )
}

/** What the screen shows (inside x 19-26, y 5-10). */
function ScreenArt({ id, ink }: { id: keyof typeof HOLO; ink: string }) {
  if (id === 'free') return <g fill={ink}>{px(22, 6, 2, 4, ink, 'p1', 0.7)}{px(20, 7, 6, 2, ink, 'p2', 0.7)}</g>
  if (id === 'failed')
    return (
      <g fill={ink}>
        {[0, 1, 2, 3].map((i) => (
          <React.Fragment key={i}>
            <rect x={21 + i} y={5 + i} width={1} height={1} />
            <rect x={24 - i} y={5 + i} width={1} height={1} />
          </React.Fragment>
        ))}
        <rect x={19} y={10} width={8} height={1} fillOpacity={0.6} />
      </g>
    )
  if (id === 'waiting')
    return (
      <g fill={ink} className="mx-game-blink">
        <rect x={22} y={5} width={2} height={3} />
        <rect x={22} y={9} width={2} height={1} />
      </g>
    )
  // A little dashboard: a bar chart and lines of data; while it works, the lines scroll.
  return (
    <g fill={ink}>
      <rect x={19} y={9} width={1} height={2} />
      <rect x={20} y={7} width={1} height={4} />
      <rect x={21} y={8} width={1} height={3} />
      <g>
        <rect x={23} y={6} width={4} height={1} />
        <rect x={23} y={8} width={3} height={1} />
        <rect x={23} y={10} width={4} height={1} />
      </g>
      {id === 'unread' && <rect x={27} y={4} width={1} height={1} fill="#ffffff" />}
    </g>
  )
}

/** One small thing on the left of the console (x 0-5). */
function Decor({ kind, color, off }: { kind: number; color: string; off: boolean }) {
  if (kind === 0)
    // a bio-pod: a glass dome with a sprout
    return (
      <g>
        {px(1, 10, 4, 1, '#cfe8ff', 'd1', 0.5)}
        {px(0, 11, 1, 4, '#cfe8ff', 'd2', 0.4)}
        {px(5, 11, 1, 4, '#cfe8ff', 'd3', 0.4)}
        {px(1, 11, 4, 4, '#9ff8ff', 'd4', 0.1)}
        {px(2, 12, 1, 3, '#3fd47a')}
        {px(3, 11, 1, 3, '#5dffa8')}
        {px(0, 15, 6, 1, STEEL.mid)}
        {px(1, 15, 1, 1, color, 'd5')}
      </g>
    )
  if (kind === 1)
    // a holo-globe over its puck
    return (
      <g className={off ? undefined : 'mx-future-holo'}>
        {px(1, 10, 3, 1, '#5ee7ff', 'h1', off ? 0.2 : 0.7)}
        {px(0, 11, 5, 3, '#5ee7ff', 'h2', off ? 0.1 : 0.3)}
        {px(1, 12, 3, 1, '#5ee7ff', 'h3', off ? 0.2 : 0.8)}
        {px(1, 14, 3, 1, '#5ee7ff', 'h4', off ? 0.2 : 0.7)}
        {px(0, 15, 5, 1, STEEL.mid)}
      </g>
    )
  if (kind === 2)
    // a cup with a light ring
    return (
      <g>
        {px(1, 12, 4, 4, HULL.ink)}
        {px(2, 13, 2, 2, '#e8eefc')}
        {px(2, 14, 2, 1, color)}
        {px(4, 13, 1, 1, HULL.ink)}
        {px(2, 11, 1, 1, '#ffffff', 'steam', 0.35)}
      </g>
    )
  // a little drone hovering
  return (
    <g className={off ? undefined : 'mx-future-float'}>
      {px(0, 8, 5, 1, STEEL.hi)}
      {px(1, 9, 3, 2, STEEL.top)}
      {px(2, 10, 1, 1, off ? HOLO.off : '#ff5f6d', 'eye')}
      {px(1, 12, 3, 1, color, 'thrust', off ? 0.1 : 0.35)}
    </g>
  )
}

/** The chip above the head: "..." working, "!" waiting for an OK, new results; "z Z" off. */
function StatusChip({ agent: a, status: st, s }: { agent: Agent; status: Status; s: number }) {
  if (st.id === 'off')
    return (
      <span aria-hidden className="absolute flex -translate-y-full items-end gap-0.5 font-mono leading-none font-bold text-[#7f8bb0]" style={{ left: 13 * s, top: 4 * s }}>
        <span className="mx-game-zzz text-[11px]">z</span>
        <span className="mx-game-zzz text-[14px] [animation-delay:0.6s]">Z</span>
      </span>
    )
  const ink = st.id === 'waiting' ? HOLO.waiting : st.id === 'unread' ? HOLO.unread : st.id === 'running' ? HOLO.running : ''
  if (!ink) return null
  const where = { className: 'absolute z-10 -translate-x-1/2 -translate-y-full', style: { left: 11 * s, top: 2 * s } }
  const chip = (
    <>
      <span
        className={cn('flex h-5 min-w-5 items-center justify-center gap-0.5 border px-1 font-mono text-[12px] leading-none font-bold tabular-nums', st.id === 'waiting' && 'mx-game-hop', st.id === 'running' && 'mx-px-dots')}
        style={{ color: ink, borderColor: ink, backgroundColor: 'rgba(6,9,20,0.85)', boxShadow: `0 0 8px ${ink}66, inset 0 0 6px ${ink}33`, textShadow: `0 0 5px ${ink}` }}
      >
        {st.id === 'waiting' ? '!' : st.id === 'unread' ? a.thread_unread : (
          <>
            <i className="size-1" style={{ backgroundColor: ink }} />
            <i className="size-1" style={{ backgroundColor: ink }} />
            <i className="size-1" style={{ backgroundColor: ink }} />
          </>
        )}
      </span>
      {/* the beam down to the head */}
      <span className="mx-auto block h-1 w-0.5" style={{ backgroundColor: ink, opacity: 0.6 }} />
    </>
  )
  // Waiting: the "!" is a button that opens the requests with Allow / Deny (approvals.tsx).
  if (st.id === 'waiting')
    return (
      <WaitingBubble agent={a} {...where}>
        {chip}
      </WaitingBubble>
    )
  return (
    <span aria-hidden {...where}>
      {chip}
    </span>
  )
}

/** What completes the last row of a bay: a server rack, a little robot or a bio-pod. */
function Filler({ kind, s, color }: { kind: number; s: number; color: string }) {
  return (
    <div aria-hidden className="grid justify-items-center" style={{ width: W * s }}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W * s} height={H * s} shapeRendering="crispEdges">
        {kind === 0 ? (
          // a server rack, its lights blinking
          <g>
            {px(8, 3, 14, 25, HULL.ink)}
            {px(9, 4, 12, 23, STEEL.dark)}
            {[5, 10, 15, 20].map((y) => (
              <g key={y}>
                {px(10, y, 10, 4, STEEL.low, `u${y}`)}
                {px(10, y, 10, 1, STEEL.mid, `uh${y}`)}
                {px(15, y + 2, 4, 1, '#000000', `v${y}`, 0.5)}
              </g>
            ))}
            <g className={ledClass(0)}>{[5, 10, 15, 20].map((y) => px(11, y + 2, 1, 1, '#5dffa8', `g${y}`))}</g>
            <g className={ledClass(1)}>{[5, 10, 15, 20].map((y) => px(13, y + 2, 1, 1, color, `c${y}`))}</g>
            {px(9, 26, 12, 1, color, 'base', 0.6)}
            {px(8, 28, 14, 1, color, 'glow', 0.2)}
          </g>
        ) : kind === 1 ? (
          // a little robot on a wheel, its eye scanning
          <g>
            {px(14, 4, 1, 3, STEEL.hi)}
            <g className={ledClass(0)}>{px(13, 3, 3, 1, color)}</g>
            {px(9, 7, 12, 8, HULL.ink)}
            {px(10, 8, 10, 6, STEEL.top)}
            {px(10, 8, 10, 1, STEEL.hi)}
            {px(11, 10, 8, 2, HULL.ink)}
            <rect x={12} y={10} width={2} height={2} fill="#5ee7ff" className="mx-future-scan-x" />
            {px(11, 15, 8, 8, HULL.ink)}
            {px(12, 15, 6, 7, STEEL.mid)}
            {px(13, 17, 4, 2, color, 'core', 0.85)}
            {px(12, 23, 6, 3, HULL.ink)}
            {px(13, 24, 4, 1, STEEL.dark)}
            {px(10, 27, 10, 1, color, 'glow', 0.25)}
          </g>
        ) : (
          // a tall bio-pod: a tube of light with a plant and bubbles
          <g>
            {px(10, 3, 10, 2, STEEL.mid)}
            {px(10, 25, 10, 3, STEEL.mid)}
            {px(11, 26, 8, 1, color, 'ring', 0.9)}
            {px(11, 5, 8, 20, '#5dffa8', 'tube', 0.12)}
            {px(11, 5, 1, 20, '#cfe8ff', 'gl', 0.35)}
            {px(18, 5, 1, 20, '#cfe8ff', 'gr', 0.2)}
            {px(15, 10, 1, 15, '#2f9e5a')}
            {px(12, 12, 3, 3, '#3fd47a')}
            {px(16, 9, 3, 3, '#5dffa8')}
            {px(13, 17, 2, 2, '#5dffa8')}
            {px(16, 15, 2, 3, '#3fd47a')}
            <rect x={13} y={21} width={1} height={1} fill="#e8fff4" className="mx-future-bubble" />
            <rect x={17} y={19} width={1} height={1} fill="#e8fff4" className="mx-future-bubble" style={{ animationDelay: '-1.1s' }} />
          </g>
        )}
      </svg>
    </div>
  )
}
