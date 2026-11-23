// One chip for every name a message points at: a session, an agent, a Team contact or group, a member of an agent
// group ("@all" too) and a "/" command or skill. Drawn in sent messages and answers (with its face or icon), and
// behind the composer's text (ChipBackdrop: the same colour, the text stays the textarea's own).
import * as React from 'react'
import { Link } from 'react-router'
import { Bot, MessageSquare, Slash, User, Users, UsersRound } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Sensitive } from '@/components/ui'
import type { AgentAvatar } from '@/lib/types'
import { AgentAvatarIcon } from '@/features/agents/Avatar'

export type ChipKind = 'session' | 'agent' | 'team' | 'group' | 'all' | 'command'

export type ChipData = {
  kind: ChipKind
  /** What the chip says ("Lea", "Blog writer", "seo-audit"). */
  label: string
  /** The text it stands for ("@Lea", "/seo-audit"): its tooltip. */
  raw?: string
  avatar?: Partial<AgentAvatar> | null
  /** A session that is running: a green dot on its icon. */
  running?: boolean
  /** Where a click goes (a session, an agent's page). */
  to?: string
}

export type ChipTone = 'card' | 'primary'

/** The chip's colours (also the composer's backdrop): commands stay grey, names take the accent. */
const chipColor = (kind: ChipKind, tone: ChipTone = 'card') =>
  tone === 'primary'
    ? 'bg-primary-foreground/20 text-primary-foreground'
    : kind === 'command'
      ? 'bg-foreground/[0.07] text-foreground ring-1 ring-foreground/10 ring-inset'
      : 'bg-primary/10 text-primary ring-1 ring-primary/20 ring-inset'

function ChipIcon({ c }: { c: ChipData }) {
  const k = 'size-3 text-current opacity-75'
  if (c.kind === 'agent' && c.avatar !== undefined) return <AgentAvatarIcon avatar={c.avatar as AgentAvatar} size={16} className="rounded-full" />
  const icon =
    c.kind === 'agent' ? <Bot className={k} />
    : c.kind === 'team' ? <User className={k} />
    : c.kind === 'group' ? <Users className={k} />
    : c.kind === 'all' ? <UsersRound className={k} />
    : c.kind === 'command' ? <Slash className={k} />
    : <MessageSquare className={k} />
  return (
    <span className="relative grid size-4 shrink-0 place-items-center rounded-full bg-background/60">
      {icon}
      {c.running && <span className="absolute -top-px -right-px size-1.5 rounded-full bg-emerald-500" />}
    </span>
  )
}

export function Chip({ chip: c, tone = 'card', className }: { chip: ChipData; tone?: ChipTone; className?: string }) {
  const cls = cn(
    'inline-flex max-w-full items-center gap-1 rounded-full py-px pr-1.5 pl-0.5 align-[-0.2em] text-[0.92em] font-medium whitespace-nowrap no-underline',
    chipColor(c.kind, tone),
    c.to && 'transition-[filter] hover:brightness-110',
    className,
  )
  const body = (
    <>
      <ChipIcon c={c} />
      <span className="truncate">{c.kind === 'command' ? c.label : <Sensitive length={6}>{c.label}</Sensitive>}</span>
    </>
  )
  const props = { className: cls, title: c.raw, 'data-chip': c.kind }
  return c.to ? (
    <Link to={c.to} {...props} onClick={(e) => e.stopPropagation()}>
      {body}
    </Link>
  ) : (
    <span {...props}>{body}</span>
  )
}

/** A place in a text drawn as a chip: [start, end) of its raw text. */
export type ChipSpan = { start: number; end: number; chip: ChipData }

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Where each `@label` is written as a whole name ("@Leah" is not Lea), never overlapping; the longest first ("@Lea
 *  Martin" wins over "@Lea"). Two names written the same (two sessions called "Blog") take the places in turn. */
export function findNames(text: string, names: { raw: string; chip: ChipData }[]): ChipSpan[] {
  const out: ChipSpan[] = []
  const byRaw = new Map<string, ChipData[]>()
  for (const n of names) byRaw.set(n.raw, [...(byRaw.get(n.raw) || []), n.chip])
  for (const [raw, chips] of [...byRaw].sort((a, b) => b[0].length - a[0].length)) {
    const re = new RegExp(`(?<![\\p{L}\\p{N}_@./-])${esc(raw)}(?![\\p{L}\\p{N}_-])`, 'gu')
    let k = 0
    for (const m of text.matchAll(re)) {
      const s = m.index, e = s + m[0].length
      if (out.some((o) => s < o.end && e > o.start)) continue
      out.push({ start: s, end: e, chip: chips[Math.min(k++, chips.length - 1)] })
    }
  }
  return out.sort((a, b) => a.start - b.start)
}

/** "/name" at the very start of a message, when `known` says it is a command or a skill ("/tmp is full" is not). */
export function findCommand(text: string, known: (name: string) => boolean): ChipSpan | null {
  const m = /^\/([a-z0-9][\w:.-]{0,63})(?=\s|$)/i.exec(text)
  if (!m || !known(m[1])) return null
  return { start: 0, end: m[0].length, chip: { kind: 'command', label: m[1], raw: m[0] } }
}

/** A text with its spans as chips (the rest stays text). */
export function withChips(text: string, spans: ChipSpan[], tone?: ChipTone): React.ReactNode {
  if (!spans.length) return text
  const out: React.ReactNode[] = []
  let at = 0
  for (const s of spans) {
    if (s.start < at) continue
    if (s.start > at) out.push(text.slice(at, s.start))
    out.push(<Chip key={s.start} chip={s.chip} tone={tone} />)
    at = s.end
  }
  if (at < text.length) out.push(text.slice(at))
  return out
}

/** The composer's backdrop colours: the chip's tint, a little wider than its letters (a shadow, never a padding:
 *  the backdrop's letters must fall exactly under the textarea's). */
const BACK: Record<'name' | 'command', string> = {
  name: 'bg-primary/20 shadow-[0_0_0_2px_color-mix(in_oklab,var(--primary)_20%,transparent)]',
  command: 'bg-foreground/12 shadow-[0_0_0_2px_color-mix(in_oklab,var(--foreground)_12%,transparent)]',
}
const MIRROR = ['fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'letterSpacing', 'lineHeight', 'wordSpacing', 'tabSize',
  'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'borderTopWidth', 'borderLeftWidth', 'textIndent'] as const

/** Behind a textarea: the same text, invisible, with a chip's tint under each span. The textarea still draws the text,
 *  the caret and the selection on top: a backdrop a pixel off never hides a letter. Its font, padding and width are
 *  copied from the textarea (its width without the scrollbar), and it follows the textarea's scroll. */
export function ChipBackdrop({ text, spans, target }: { text: string; spans: ChipSpan[]; target: HTMLTextAreaElement | null }) {
  const box = React.useRef<HTMLDivElement>(null)
  const inner = React.useRef<HTMLDivElement>(null)
  const on = spans.length > 0 && !!target
  const sync = React.useCallback(() => {
    const el = target, b = box.current, i = inner.current, parent = el?.offsetParent
    if (!el || !b || !i || !parent) return
    const cs = getComputedStyle(el)
    for (const k of MIRROR) i.style[k] = cs[k]
    i.style.borderStyle = 'solid'
    i.style.borderColor = 'transparent'
    i.style.borderRightWidth = i.style.borderBottomWidth = '0px'
    // exact (fractional) sizes: a width rounded down by a pixel wraps a word the textarea keeps on its line
    const r = el.getBoundingClientRect(), pr = parent.getBoundingClientRect()
    const bl = parseFloat(cs.borderLeftWidth) || 0, br = parseFloat(cs.borderRightWidth) || 0
    const bar = Math.max(0, el.offsetWidth - el.clientWidth - bl - br) // its scrollbar, when it has one
    b.style.top = `${r.top - pr.top - parent.clientTop}px`
    b.style.left = `${r.left - pr.left - parent.clientLeft}px`
    b.style.width = `${r.width}px`
    b.style.height = `${r.height}px`
    i.style.width = `${r.width - br - bar}px`
    i.style.transform = `translateY(${-el.scrollTop}px)`
  }, [target])
  // Size, place and scroll follow the textarea and its box (an attachment strip above moves it without resizing it).
  React.useLayoutEffect(() => {
    const el = target
    if (!on || !el) return
    const ro = new ResizeObserver(sync)
    ro.observe(el)
    if (el.offsetParent) ro.observe(el.offsetParent)
    el.addEventListener('scroll', sync, { passive: true })
    return () => {
      ro.disconnect()
      el.removeEventListener('scroll', sync)
    }
  }, [on, target, sync])
  React.useLayoutEffect(() => {
    if (on) sync()
  })
  if (!on) return null
  const out: React.ReactNode[] = []
  let at = 0
  for (const s of spans) {
    if (s.start < at) continue
    if (s.start > at) out.push(text.slice(at, s.start))
    out.push(
      <mark key={s.start} className={cn('rounded-[0.35em] text-transparent [box-decoration-break:clone]', BACK[s.chip.kind === 'command' ? 'command' : 'name'])}>
        {text.slice(s.start, s.end)}
      </mark>,
    )
    at = s.end
  }
  out.push(text.slice(at) + '\u200b') // a last newline needs a character after it to take its line
  return (
    <div ref={box} aria-hidden data-chip-backdrop="" className="pointer-events-none absolute overflow-hidden">
      <div ref={inner} className="box-border whitespace-pre-wrap text-transparent [overflow-wrap:break-word]">
        {out}
      </div>
    </div>
  )
}
