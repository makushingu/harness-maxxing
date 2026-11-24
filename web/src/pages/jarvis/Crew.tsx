// The sessions at work beside Jarvis's conversation, drawn as the Agents page draws its agents: a pixel character per
// session (a stable face from its id, its outfit the colour of its project) that moves while its turn runs, a "!" that
// hops when Jarvis's work there waits for the owner, a check once it just finished. Three looks (`CrewStyle`): desks,
// speech bubbles, a running track. Every animation stops at rest under reduced motion (globals.css).
import * as React from 'react'
import { Link } from 'react-router'
import { Check } from 'lucide-react'
import { useLang, useT } from '@/i18n'
import { useSessions } from '@/lib/queries'
import type { AgentAvatar, JarvisWork, Session } from '@/lib/types'
import { cn } from '@/lib/utils'
import { fmtRelative } from '@/lib/format'
import { AgentAvatarIcon, AVATAR_OPTIONS, AVATAR_PARTS, projectColor } from '@/features/agents/Avatar'
import { sessionsUrl } from '@/pages/sessions/util'

export type CrewStyle = 'desk' | 'chat' | 'track'
export const CREW_STYLES: CrewStyle[] = ['desk', 'chat', 'track']
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

/** A stable character for a session: its id picks each part, its project the outfit. */
const faces = new Map<string, AgentAvatar>()
function faceOf(s: Session): AgentAvatar {
  let a = faces.get(s.id)
  if (a) return a
  let h = 0x811c9dc5
  for (let i = 0; i < s.id.length; i++) h = Math.imul(h ^ s.id.charCodeAt(i), 0x01000193) >>> 0
  a = {} as AgentAvatar
  for (const k of AVATAR_PARTS) {
    const opts = AVATAR_OPTIONS[k]
    a[k] = opts[h % opts.length]
    h = Math.imul(h ^ (h >>> 13), 0x5bd1e995) >>> 0
  }
  if (h % 2) a.accessory = 'none'
  a.color = projectColor(s.path.split('/')[1] || s.path)
  faces.set(s.id, a)
  return a
}
const whereOf = (s: Session) => s.path.replace(/^projects\//, '').replace('/topics/', '/')

export function Crew({ crew, look }: { crew: Crewmate[]; look: CrewStyle }) {
  const t = useT()
  if (!crew.length)
    return (
      <div className="flex flex-col items-center gap-3 px-4 py-10 text-center">
        <AgentAvatarIcon avatar={{ color: 'blue', face: 'sleepy', hair: 'short' }} size={48} tile={false} mood="sleep" />
        <span className="mx-game-zzz text-xs font-semibold text-muted-foreground">z z</span>
        <p className="text-[13px] text-muted-foreground">{t('jarvis.live.empty')}</p>
      </div>
    )
  if (look === 'desk')
    return (
      <div className="grid grid-cols-2 gap-2">
        {crew.map((c, i) => (
          <Desk key={c.s.id} c={c} i={i} />
        ))}
      </div>
    )
  return (
    <div className={look === 'chat' ? 'space-y-3' : 'space-y-2'}>
      {crew.map((c, i) => (look === 'chat' ? <Chat key={c.s.id} c={c} i={i} /> : <Track key={c.s.id} c={c} i={i} />))}
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

function Person({ c, size, i }: { c: Crewmate; size: number; i: number }) {
  return (
    <span className={cn('block', c.mood === 'work' && 'mx-game-bob')} style={{ '--s': `${Math.max(1, size / 24)}px`, animationDelay: `${-(i % 4) * 0.22}s` } as React.CSSProperties}>
      <AgentAvatarIcon avatar={faceOf(c.s)} size={size} tile={false} animate mood={c.mood === 'done' ? 'idle' : 'idle'} />
    </span>
  )
}

function Tag({ c }: { c: Crewmate }) {
  const t = useT()
  if (c.mood === 'ask') return <span className="text-warning">{t('jarvis.crew.ask')}</span>
  if (c.mood === 'done') return <span className="text-success">{t('jarvis.crew.done')}</span>
  return c.work ? <span className="text-primary">#{c.work.id}</span> : null
}

/* ---- desks: a little office, one desk per session, its screen glowing while it works */
function Desk({ c, i }: { c: Crewmate; i: number }) {
  return (
    <Link
      to={sessionsUrl(c.s)}
      className="mx-rise group relative flex flex-col items-center rounded-lg border bg-card px-2 pt-5 pb-2 text-center outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
      style={{ '--i': Math.min(i, 8) } as React.CSSProperties}
      data-testid="jarvis-crew"
    >
      <span className="relative">
        <Person c={c} size={48} i={i} />
        <Mark mood={c.mood} className="absolute -top-2 -right-5" />
      </span>
      {/* the desk and its screen */}
      <span className="relative -mt-1 flex h-3 w-16 items-end justify-center">
        {c.mood === 'work' && <span className="mx-game-glow absolute -top-1.5 h-3 w-10 rounded-full bg-primary" />}
        <span className="relative h-2 w-16 rounded-sm bg-muted-foreground/30" />
      </span>
      <span className="mt-2 w-full truncate text-xs font-medium">{c.s.title || whereOf(c.s)}</span>
      <span className="w-full truncate text-[11px] text-muted-foreground">
        {whereOf(c.s)} <Tag c={c} />
      </span>
    </Link>
  )
}

/* ---- speech bubbles: each character says what it is doing now (its last words), live */
function Chat({ c, i }: { c: Crewmate; i: number }) {
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
        <Person c={c} size={36} i={i} />
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

/* ---- running track: the character runs back and forth while it works, waits at the end once done or asking */
function Track({ c, i }: { c: Crewmate; i: number }) {
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
            <Person c={c} size={24} i={i} />
          </span>
        ) : (
          <span className="absolute right-0 bottom-0 flex items-end gap-1">
            <Mark mood={c.mood} className="mb-4" />
            <Person c={c} size={24} i={i} />
          </span>
        )}
      </span>
    </Link>
  )
}
