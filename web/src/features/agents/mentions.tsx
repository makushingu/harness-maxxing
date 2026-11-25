// @names in a group: a known `@handle` (or @all) is drawn as a chip with the member's face and name, in the owner's
// messages, in the agents' answers (Markdown text, never inside code) and above the box (who the message goes to).
// Same pattern as the server's MENTION_RE (agent_rooms.py), so a chip is exactly a name the server reads.
import * as React from 'react'
import type { Components } from 'react-markdown'
import { useT } from '@/i18n'
import type { AgentGroupMember } from '@/lib/types'
import { Chip, withChips, type ChipData, type ChipSpan, type ChipTone } from '@/features/chips/Chip'

const ALL_WORDS = ['all', 'everyone', 'tous']
const MENTION_RE = /(?<![\w@./-])@([a-z0-9][a-z0-9-]{0,47})\b/gi
// "stop @bob" pauses Bob: the server (STOP_RE of agent_rooms.py) takes these out before reading who is named
const STOP_RE = /(?<![\w-])stop\s+@([a-z0-9][a-z0-9-]{0,47})\b/gi

/** handle -> member; `null` = @all. */
export type MentionMap = Map<string, AgentGroupMember | null>

export function useMentionMap(members: AgentGroupMember[]): MentionMap {
  return React.useMemo(() => {
    const map: MentionMap = new Map(ALL_WORDS.map((w) => [w, null]))
    for (const m of members) map.set(m.handle.toLowerCase(), m)
    return map
  }, [members])
}

/** The members named in a text, in order (@all = every member), without repeats; not those it stops ("stop @bob"). */
export function namedIn(text: string, map: MentionMap, members: AgentGroupMember[]): AgentGroupMember[] {
  const out: AgentGroupMember[] = []
  for (const m of text.replace(STOP_RE, ' ').matchAll(MENTION_RE)) {
    const h = m[1].toLowerCase()
    if (!map.has(h)) continue
    const who = map.get(h)
    for (const x of who ? [who] : members) if (!out.includes(x)) out.push(x)
  }
  return out
}

/** A member (null = @all) as a chip: the same one as the sessions' @ and the "/" commands. */
function memberChip(member: AgentGroupMember | null, handle: string, allLabel: string): ChipData {
  return member
    ? { kind: 'agent', label: member.display_name || handle, raw: `@${handle}`, avatar: member.avatar ?? null }
    : { kind: 'all', label: allLabel, raw: `@${handle}` }
}

export function MentionChip({ member, handle, tone = 'card', className }: { member: AgentGroupMember | null; handle: string; tone?: ChipTone; className?: string }) {
  const t = useT()
  return <Chip chip={memberChip(member, handle, t('groups.mention.all'))} tone={tone} className={className} />
}

/** Where the known @names of a text are (unknown ones stay as typed). */
export function mentionSpans(text: string, map: MentionMap, allLabel: string): ChipSpan[] {
  if (!text.includes('@')) return []
  const out: ChipSpan[] = []
  for (const m of text.matchAll(MENTION_RE)) {
    const h = m[1].toLowerCase()
    if (map.has(h)) out.push({ start: m.index, end: m.index + m[0].length, chip: memberChip(map.get(h) ?? null, h, allLabel) })
  }
  return out
}

/** A text with its known @names as chips. */
function MentionText({ text, map, tone }: { text: string; map: MentionMap; tone?: ChipTone }) {
  const t = useT()
  return <>{withChips(text, mentionSpans(text, map, t('groups.mention.all')), tone)}</>
}

/** For places without hooks (Markdown overrides): the chips' "@all" is labelled by MentionChip. */
export function mentionNodes(text: string, map: MentionMap, tone?: ChipTone): React.ReactNode {
  return text.includes('@') ? <MentionText text={text} map={map} tone={tone} /> : text
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
