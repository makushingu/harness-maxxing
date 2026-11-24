// The sessions at work beside Jarvis's conversation: a small animated pictogram per session, in the colour of its
// project (`Glyph`: a glowing orb, a terminal typing, sound bars) that moves while its turn runs, a "!" that hops when
// Jarvis's work there waits for the owner, a check once it just finished. Three layouts (`CrewStyle`): cards, speech
// bubbles, a track. Every animation stops at rest under reduced motion (globals.css).
import * as React from 'react'
import { Link } from 'react-router'
import { Check } from 'lucide-react'
import { useLang, useT } from '@/i18n'
import { useSessions } from '@/lib/queries'
import type { JarvisWork, Session } from '@/lib/types'
import { cn } from '@/lib/utils'
import { fmtRelative } from '@/lib/format'
import { OUTFIT, projectColor } from '@/features/agents/pixels'
import { sessionsUrl } from '@/pages/sessions/util'

export type CrewStyle = 'desk' | 'chat' | 'track'
export const CREW_STYLES: CrewStyle[] = ['desk', 'chat', 'track']
export type GlyphKind = 'orb' | 'term' | 'wave'
export const GLYPHS: GlyphKind[] = ['orb', 'term', 'wave']
type Mood = 'work' | 'ask' | 'done'
export type Crewmate = { s: Session; work?: JarvisWork; mood: Mood }

/** A session finished this recently, not read yet: still shown, with a check. */
const DONE_S = 15 * 60

/** Who is on screen: running sessions, those where Jarvis's work waits for the owner, those that just finished (not
 *  read yet); never Jarvis's own folder nor archived ones. Waiting first, then at work, then done; newest first. */
export function useCrew(own: string, work: JarvisWork[] | undefined): Crewmate[] {
  const { data } = useSessions()
  return React.useMemo(() => {
    const open = (work || []).filter((w) => w.state !== 'closed')
    const byS = new Map(open.map((w) => [w.session, w]))
    const asks = new Set(open.filter((w) => w.state === 'replied' && w.question).map((w) => w.session))
    const now = Date.now() / 1000
    const rank: Record<Mood, number> = { ask: 0, work: 1, done: 2 }
    return (data || [])
      .filter((s) => s.path !== own && !s.archived)
      .map((s): Crewmate | null => {
        const mood: Mood | null = s.state === 'running' ? 'work' : asks.has(s.id) ? 'ask' : s.unread && now - s.updated < DONE_S ? 'done' : null
        return mood && { s, work: byS.get(s.id), mood }
      })
      .filter((c): c is Crewmate => !!c)
      .sort((a, b) => rank[a.mood] - rank[b.mood] || b.s.updated - a.s.updated)
  }, [data, own, work])
}

/** A session's colour: its project's (the outfit colour its agents wear). */
const colorOf = (s: Session) => OUTFIT[projectColor(s.path.split('/')[1] || s.path)]
const whereOf = (s: Session) => s.path.replace(/^projects\//, '').replace('/topics/', '/')

export function Crew({ crew, look, glyph }: { crew: Crewmate[]; look: CrewStyle; glyph: GlyphKind }) {
  const t = useT()
  if (!crew.length)
    return (
      <div className="flex flex-col items-center gap-3 px-4 py-10 text-center">
        <Glyph kind={glyph} color="#8b8b99" mood="done" still size={40} i={0} />
        <p className="text-[13px] text-muted-foreground">{t('jarvis.live.empty')}</p>
      </div>
    )
  if (look === 'desk')
    return (
      <div className="grid grid-cols-2 gap-2">
        {crew.map((c, i) => (
          <Desk key={c.s.id} c={c} i={i} g={glyph} />
        ))}
      </div>
    )
  return (
    <div className={look === 'chat' ? 'space-y-3' : 'space-y-2'}>
      {crew.map((c, i) => (look === 'chat' ? <Chat key={c.s.id} c={c} i={i} g={glyph} /> : <Track key={c.s.id} c={c} i={i} g={glyph} />))}
    </div>
  )
}

/** Over the character: dots while it works, a hopping "!" when it waits for the owner, a check once done. */
function Mark({ mood, className }: { mood: Mood; className?: string }) {
  if (mood === 'ask')
    return <span className={cn('mx-game-hop text-[20px] leading-none font-black text-[#ffcc4d] [paint-order:stroke_fill] [-webkit-text-stroke:3px_#3b2a00]', className)}>!</span>
  if (mood === 'done')
    return (
      <span className={cn('flex size-5 items-center justify-center rounded-full border bg-popover text-success shadow-xs', className)}>
        <Check className="size-3" strokeWidth={3} />
      </span>
    )
  return (
    <span className={cn('mx-px-dots flex h-5 items-center gap-0.5 rounded-full border bg-popover px-1.5 shadow-xs', className)}>
      {[0, 1, 2].map((k) => (
        <i key={k} className="size-1 rounded-full bg-muted-foreground" />
      ))}
    </span>
  )
}

/** The pictogram of a session. `still`: drawn at rest (done, waiting, the empty panel). */
export function Glyph({ kind, color, mood, size, i, still }: { kind: GlyphKind; color: string; mood: Mood; size: number; i: number; still?: boolean }) {
  const on = mood === 'work' && !still
  const d = { animationDelay: `${-(i % 5) * 0.37}s` } as React.CSSProperties
  const box = { width: size, height: size, '--c': color } as React.CSSProperties
  if (kind === 'orb')
    return (
      <span className="relative inline-flex shrink-0 items-center justify-center" style={box} aria-hidden>
        {on && <span className="mx-orb-ring absolute inset-0 rounded-full" style={d} />}
        <span
          className={cn('rounded-full', on && 'mx-orb-pulse')}
          style={{ ...d, width: size * 0.62, height: size * 0.62, background: 'radial-gradient(circle at 35% 30%, color-mix(in oklab, var(--c) 35%, white), var(--c) 60%, color-mix(in oklab, var(--c) 70%, black))', boxShadow: on ? '0 0 12px color-mix(in oklab, var(--c) 60%, transparent)' : undefined, opacity: mood === 'done' ? 0.55 : 1 }}
        />
      </span>
    )
  if (kind === 'term')
    return (
      <span className="inline-flex shrink-0 flex-col overflow-hidden rounded-[5px] border bg-[#15141b]" style={{ ...box, height: size * 0.78 }} aria-hidden>
        <span className="flex h-[18%] shrink-0 items-center gap-[2px] px-[10%]" style={{ background: 'color-mix(in oklab, var(--c) 35%, #15141b)' }}>
          {[0, 1, 2].map((k) => (
            <i key={k} className="size-[3px] rounded-full bg-white/50" />
          ))}
        </span>
        <span className="flex flex-1 flex-col justify-center gap-[3px] px-[12%]">
          {[0.8, 0.55, 0.7].map((w, k) => (
            <span key={k} className="flex h-[2px] items-center">
              <span className={cn('h-full rounded-full', on && 'mx-term-type')} style={{ width: `${w * 100}%`, background: k === 1 ? 'var(--c)' : 'rgb(255 255 255 / 0.55)', animationDelay: `${-(i % 5) * 0.37 - k * 0.6}s` }} />
              {on && k === 2 && <span className="mx-game-blink ml-[2px] h-[5px] w-[2px] bg-white/80" />}
            </span>
          ))}
        </span>
      </span>
    )
  return (
    <span className="inline-flex shrink-0 items-end justify-center gap-[12%] px-[8%]" style={{ ...box, height: size * 0.7 }} aria-hidden>
      {[0.55, 0.9, 0.7, 1, 0.6].map((h, k) => (
        <span
          key={k}
          className={cn('w-[11%] origin-bottom rounded-full', on && 'mx-eq')}
          style={{ height: `${(on ? h : 0.25) * 100}%`, background: 'var(--c)', opacity: mood === 'done' ? 0.5 : 1, animationDelay: `${-(i % 5) * 0.37 - k * 0.23}s`, animationDuration: `${0.9 + (k % 3) * 0.25}s` }}
        />
      ))}
    </span>
  )
}

function Tag({ c }: { c: Crewmate }) {
  const t = useT()
  if (c.mood === 'ask') return <span className="text-warning">{t('jarvis.crew.ask')}</span>
  if (c.mood === 'done') return <span className="text-success">{t('jarvis.crew.done')}</span>
  return c.work ? <span className="text-primary">#{c.work.id}</span> : null
}

/* ---- cards: a grid, one card per session */
function Desk({ c, i, g }: { c: Crewmate; i: number; g: GlyphKind }) {
  return (
    <Link
      to={sessionsUrl(c.s)}
      className="mx-rise group relative flex flex-col items-center rounded-lg border bg-card px-2 pt-5 pb-2 text-center outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
      style={{ '--i': Math.min(i, 8) } as React.CSSProperties}
      data-testid="jarvis-crew"
    >
      <span className="relative flex h-12 items-center">
        <Glyph kind={g} color={colorOf(c.s)} mood={c.mood} size={44} i={i} />
        <Mark mood={c.mood} className="absolute -top-2 -right-5" />
      </span>
      <span className="mt-2 w-full truncate text-xs font-medium">{c.s.title || whereOf(c.s)}</span>
      <span className="w-full truncate text-[11px] text-muted-foreground">
        {whereOf(c.s)} <Tag c={c} />
      </span>
    </Link>
  )
}

/* ---- speech bubbles: each session says what it is doing now (its last words), live */
function Chat({ c, i, g }: { c: Crewmate; i: number; g: GlyphKind }) {
  const t = useT()
  const lang = useLang()
  return (
    <Link
      to={sessionsUrl(c.s)}
      className="mx-rise group flex items-end gap-2 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring"
      style={{ '--i': Math.min(i, 8) } as React.CSSProperties}
      data-testid="jarvis-crew"
    >
      <span className="relative shrink-0 pb-1">
        <Glyph kind={g} color={colorOf(c.s)} mood={c.mood} size={32} i={i} />
      </span>
      <span className="relative min-w-0 flex-1 rounded-xl rounded-bl-sm border bg-card px-3 py-2 transition-colors group-hover:bg-muted">
        <span className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{c.s.title || whereOf(c.s)}</span>
          <Mark mood={c.mood} />
        </span>
        <span className="block truncate text-[11px] text-muted-foreground">
          {whereOf(c.s)} <Tag c={c} />
        </span>
        <span className="mt-1 line-clamp-2 block text-xs text-foreground/80">
          {c.s.last_text || (c.mood === 'work' ? '…' : t('jarvis.live.since', { when: fmtRelative(c.s.updated, lang) }))}
        </span>
      </span>
    </Link>
  )
}

/* ---- track: the pictogram goes back and forth while it works, waits at the end once done or asking */
function Track({ c, i, g }: { c: Crewmate; i: number; g: GlyphKind }) {
  return (
    <Link
      to={sessionsUrl(c.s)}
      className="mx-rise group block rounded-lg border bg-card px-3 pt-2 pb-1 outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
      style={{ '--i': Math.min(i, 8) } as React.CSSProperties}
      data-testid="jarvis-crew"
    >
      <span className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{c.s.title || whereOf(c.s)}</span>
        <span className="shrink-0 truncate text-[11px] text-muted-foreground">
          <Tag c={c} />
        </span>
      </span>
      <span className="block truncate text-[11px] text-muted-foreground">{whereOf(c.s)}</span>
      <span className="relative mt-1 block h-8 border-b border-dashed border-muted-foreground/40">
        {c.mood === 'work' ? (
          <span className="mx-crew-run absolute bottom-0" style={{ animationDelay: `${-(i * 1.7) % 7}s` } as React.CSSProperties}>
            <Glyph kind={g} color={colorOf(c.s)} mood={c.mood} size={24} i={i} />
          </span>
        ) : (
          <span className="absolute right-0 bottom-0 flex items-end gap-1">
            <Mark mood={c.mood} className="mb-4" />
            <Glyph kind={g} color={colorOf(c.s)} mood={c.mood} size={24} i={i} />
          </span>
        )}
      </span>
    </Link>
  )
}
