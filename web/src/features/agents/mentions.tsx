// @names in a group: a known `@handle` (or @all) is drawn as a chip with the member's face and name, in the owner's
// messages, in the agents' answers (Markdown text, never inside code) and above the box (who the message goes to).
// Same pattern as the server's MENTION_RE (agent_rooms.py), so a chip is exactly a name the server reads.
import * as React from 'react'
import type { Components } from 'react-markdown'
import { UsersRound } from 'lucide-react'
import { useT } from '@/i18n'
import type { AgentGroupMember } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Sensitive } from '@/components/ui'
import { AgentAvatarIcon } from './Avatar'

export const ALL_WORDS = ['all', 'everyone', 'tous']
const MENTION_RE = /(?<![\w@./-])@([a-z0-9][a-z0-9-]{0,47})\b/gi

/** handle -> member; `null` = @all. */
export type MentionMap = Map<string, AgentGroupMember | null>

export function useMentionMap(members: AgentGroupMember[]): MentionMap {
  return React.useMemo(() => {
    const map: MentionMap = new Map(ALL_WORDS.map((w) => [w, null]))
    for (const m of members) map.set(m.handle.toLowerCase(), m)
    return map
  }, [members])
}

/** The members named in a text, in order (@all = every member), without repeats. */
export function namedIn(text: string, map: MentionMap, members: AgentGroupMember[]): AgentGroupMember[] {
  const out: AgentGroupMember[] = []
  for (const m of text.matchAll(MENTION_RE)) {
    const h = m[1].toLowerCase()
    if (!map.has(h)) continue
    const who = map.get(h)
    for (const x of who ? [who] : members) if (!out.includes(x)) out.push(x)
  }
  return out
}

export function MentionChip({ member, handle, tone = 'card', className }: { member: AgentGroupMember | null; handle: string; tone?: 'card' | 'primary'; className?: string }) {
  const t = useT()
  return (
    <span
      className={cn(
        'inline-flex max-w-full items-center gap-1 rounded-full py-px pr-1.5 pl-0.5 align-[-0.2em] text-[0.92em] font-medium whitespace-nowrap',
        tone === 'primary' ? 'bg-primary-foreground/20 text-primary-foreground' : 'border bg-primary/10 text-primary',
        className,
      )}
      title={`@${handle}`}
      data-mention={handle}
    >
      {member ? (
        <AgentAvatarIcon avatar={member.avatar} size={16} className="rounded-full" />
      ) : (
        <span className="grid size-4 place-items-center rounded-full bg-muted">
          <UsersRound className="size-2.5 text-muted-foreground" />
        </span>
      )}
      <span className="truncate">
        <Sensitive length={6}>{member?.display_name || (member === null ? t('groups.mention.all') : handle)}</Sensitive>
      </span>
    </span>
  )
}

/** A text with its known @names as chips (unknown ones stay as typed). */
export function mentionNodes(text: string, map: MentionMap, tone?: 'card' | 'primary'): React.ReactNode {
  if (!text.includes('@')) return text
  const out: React.ReactNode[] = []
  let at = 0
  for (const m of text.matchAll(MENTION_RE)) {
    const h = m[1].toLowerCase()
    if (!map.has(h)) continue
    if (m.index > at) out.push(text.slice(at, m.index))
    out.push(<MentionChip key={m.index} member={map.get(h) ?? null} handle={h} tone={tone} />)
    at = m.index + m[0].length
  }
  if (!out.length) return text
  if (at < text.length) out.push(text.slice(at))
  return out
}

/** Every string child (deep) through mentionNodes; elements such as `code` are left alone. */
function mapText(node: React.ReactNode, map: MentionMap): React.ReactNode {
  return React.Children.map(node, (c) => {
    if (typeof c === 'string') return mentionNodes(c, map)
    if (React.isValidElement<{ children?: React.ReactNode }>(c) && c.type !== 'code' && c.props.children != null)
      return React.cloneElement(c, undefined, mapText(c.props.children, map))
    return c
  })
}

const TAGS = ['p', 'li', 'td', 'th', 'h1', 'h2', 'h3', 'h4'] as const

/** Markdown overrides that draw the @names of an answer as chips. */
export function mentionComponents(map: MentionMap): Components {
  const out: Record<string, (p: { children?: React.ReactNode; node?: unknown }) => React.ReactElement> = {}
  for (const tag of TAGS)
    out[tag] = ({ children, node: _n, ...rest }) => React.createElement(tag, rest, mapText(children, map))
  return out as Components
}
