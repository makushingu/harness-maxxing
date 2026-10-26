// Team people: faces, names and presence, shared by the chats, the friends and the dialogs.
import { cn } from '@/lib/utils'
import { fmtRelative } from '@/lib/format'
import { useLang, useT } from '@/i18n'
import type { TeamChat, TeamPerson, TeamState } from '@/lib/queries'
import { Avatar } from '@/features/profile/Avatar'

const STATUS_DOT: Record<TeamPerson['status'], string> = { online: 'bg-emerald-500', away: 'bg-amber-400', offline: 'bg-zinc-400' }

export function personOf(team: TeamState | undefined, id: string): TeamPerson {
  return team?.people[id] || { name: id, color: 'zinc', emoji: '', server: '', status: 'offline' }
}

export function chatTitle(team: TeamState | undefined, chat: TeamChat): string {
  if (chat.kind === 'dm') return personOf(team, chat.members[0]).name
  return chat.name || chat.members.map((m) => personOf(team, m).name).join(', ')
}

/** The people of the user's friends list (accepted contacts): online first, then the most recently seen. */
export function friendsOf(team: TeamState | undefined): [string, TeamPerson][] {
  const rank = { online: 0, away: 1, offline: 2 }
  return Object.entries(team?.people || {})
    .filter(([id, p]) => id !== team?.me && p.contact)
    .sort(([, a], [, b]) => rank[a.status] - rank[b.status] || (b.last_seen || 0) - (a.last_seen || 0) || a.name.localeCompare(b.name))
}

/** "Online", "Seen 5 min ago", "Offline": what a person's server last told us (a message, a reaction, writing...). */
export function usePresence() {
  const t = useT()
  const lang = useLang()
  return (p: TeamPerson) => {
    if (p.status === 'online') return t('team.status.online')
    if (p.last_seen) return t('team.seen', { when: fmtRelative(p.last_seen, lang) })
    return t('team.status.offline')
  }
}

export function PersonAvatar({ person, size = 'md', status, className }: { person: TeamPerson; size?: 'sm' | 'md' | 'lg'; status?: boolean; className?: string }) {
  return (
    <span className={cn('relative inline-flex shrink-0', className)}>
      <Avatar profile={person} size={size} />
      {status && (
        <span className={cn('absolute -right-0.5 -bottom-0.5 rounded-full ring-2 ring-background', size === 'lg' ? 'size-3' : 'size-2.5', STATUS_DOT[person.status])} />
      )}
    </span>
  )
}

/** The chat's face: the person of a direct chat, else the group's emoji or its first members stacked. */
export function ChatAvatar({ team, chat, size = 'lg' }: { team: TeamState | undefined; chat: TeamChat; size?: 'md' | 'lg' }) {
  if (chat.kind === 'dm') return <PersonAvatar person={personOf(team, chat.members[0])} size={size} status />
  if (chat.emoji)
    return (
      <span className={cn('inline-flex shrink-0 items-center justify-center rounded-xl bg-muted', size === 'lg' ? 'size-10 text-xl' : 'size-7 text-sm')}>{chat.emoji}</span>
    )
  const two = chat.members.slice(0, 2)
  return (
    <span className={cn('relative inline-flex shrink-0', size === 'lg' ? 'size-10' : 'size-7')}>
      {two.map((m, i) => (
        <Avatar key={m} profile={personOf(team, m)} size={size === 'lg' ? 'md' : 'sm'} className={cn('absolute ring-2 ring-background', i ? 'right-0 bottom-0' : 'top-0 left-0')} />
      ))}
    </span>
  )
}

/** Three dots that bounce: someone is writing. */
export function TypingDots({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-[3px]', className)} aria-hidden>
      {[0, 1, 2].map((i) => (
        <span key={i} className="size-[5px] animate-bounce rounded-full bg-current" style={{ animationDelay: `${i * 150}ms`, animationDuration: '1s' }} />
      ))}
    </span>
  )
}

/** "Léa is writing", "Léa and Tom are writing", "3 people are writing". */
export function useTypingLabel() {
  const t = useT()
  return (team: TeamState | undefined, ids: string[]) => {
    const names = ids.map((id) => personOf(team, id).name.split(' ')[0])
    if (names.length === 1) return t('team.typing.one', { name: names[0] })
    if (names.length === 2) return t('team.typing.two', { a: names[0], b: names[1] })
    return t('team.typing.many', { count: names.length })
  }
}
