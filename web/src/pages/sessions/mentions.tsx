// The composer's "@" menu: typing "@" (at the start or after a space) lists who the message can name - the other
// sessions, the agents, the Team contacts and groups (GET /api/sessions/{id}/mentions). The pick writes "@Name" in
// the text; when the message is sent, the server tells Claude how to write to each one named (mentions.py), and Claude
// sends if the message asks it to ("summarize and send it to @Lea"). Nothing goes out by itself.
import { Bot, MessageSquare, User, Users } from 'lucide-react'
import type { useT } from '@/i18n'
import type { Mention, MentionTarget } from '@/lib/types'
import { FOLD, fold, type MenuRow } from './SlashMenu'

export type MentionRow = MenuRow & { target?: MentionTarget; /** The "+ N more" row of this group. */ expand?: string }

const KINDS = ['session', 'agent', 'team'] as const

/** The "@" being typed just before the caret: `start` = index of the "@", `q` = what follows it. */
export function mentionAt(text: string, caret: number): { start: number; q: string } | null {
  const m = /(^|\s)@([^\s@]{0,40})$/.exec(text.slice(0, caret))
  return m ? { start: caret - m[2].length - 1, q: m[2] } : null
}

function icon(x: MentionTarget) {
  const c = 'size-3.5 shrink-0 text-muted-foreground'
  if (x.kind === 'agent') return <Bot className={c} />
  if (x.kind === 'team') return x.group ? <Users className={c} /> : <User className={c} />
  return (
    <span className="relative shrink-0">
      <MessageSquare className={c} />
      {x.state === 'running' && <span className="absolute -top-0.5 -right-0.5 size-1.5 rounded-full bg-emerald-500" />}
    </span>
  )
}

/** The rows for `q`, under a title per kind (sessions, agents, Team): names that start with it (or one of their words
 * does) first, then names or places containing it. With nothing typed, a kind over FOLD rows shows its first ones and
 * "+ N more" (unless `expanded` has it). */
export function mentionRows(q: string, targets: MentionTarget[], t: ReturnType<typeof useT>, expanded: string[] = []): MentionRow[] {
  const f = fold(q)
  const starts = (x: MentionTarget) => fold(x.label).startsWith(f) || fold(x.label).split(/\s+/).some((w) => w.startsWith(f))
  const first = targets.filter(starts)
  const then = f ? targets.filter((x) => !starts(x) && (fold(x.label).includes(f) || fold(x.hint).includes(f))) : []
  const found = [...first, ...then]
  const out: MentionRow[] = []
  for (const k of KINDS) {
    const g = `@${k}`
    const rows = found.filter((x) => x.kind === k)
    const folded = !f && rows.length > FOLD && !expanded.includes(g)
    for (const x of folded ? rows.slice(0, FOLD - 1) : rows)
      out.push({
        key: `${x.kind}:${x.ref}`,
        label: `@${x.label}`,
        hint: x.hint,
        badge: x.kind === 'team' && x.group ? t('sessions.mention.kind.group') : undefined,
        icon: <span className="flex size-4 items-center justify-center">{icon(x)}</span>,
        group: g,
        target: x,
      })
    if (folded) out.push({ key: `more:${g}`, label: '', hint: '', group: g, more: rows.length - FOLD + 1, expand: g })
  }
  return out
}

/** The mentions still written in the text when it is sent (a name deleted by hand is no longer one). */
export function usedMentions(text: string, picked: MentionTarget[]): Mention[] {
  const seen = new Set<string>()
  return picked
    .filter((x) => text.includes(`@${x.label}`) && !seen.has(`${x.kind}:${x.ref}`) && !!seen.add(`${x.kind}:${x.ref}`))
    .map((x) => ({ kind: x.kind, ref: x.ref }))
}
