// A person's pseudo: round badge (photo, else emoji or initials on their color) + name. Used for the user's own
// messages and in Team.
import * as React from 'react'
import { Bot } from 'lucide-react'
import { cn } from '@/lib/utils'
import { projectColor, PROJECT_COLORS } from '@/features/tasks/model'
import type { Profile } from '@/lib/types'

export const PROFILE_COLORS = PROJECT_COLORS

/** Initials of a pseudo ("Léa Martin" -> "LM", "feu" -> "F"). */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  const first = [...parts[0]][0] || ''
  const second = parts.length > 1 ? [...parts[parts.length - 1]][0] || '' : ''
  return (first + second).toUpperCase()
}

export function Avatar({ profile, agent, size = 'md', className }: { profile: Partial<Profile> | null | undefined; agent?: boolean; size?: 'sm' | 'md' | 'lg'; className?: string }) {
  const name = profile?.name || ''
  const dim = size === 'sm' ? 'size-5 text-[10px]' : size === 'lg' ? 'size-10 text-base' : 'size-7 text-[12px]'
  const [broken, setBroken] = React.useState('')
  const photo = profile?.photo_url && profile.photo_url !== broken ? profile.photo_url : ''
  return (
    <span
      aria-hidden
      className={cn('relative inline-flex shrink-0 select-none items-center justify-center rounded-full font-semibold text-white', dim, className)}
      style={{ background: projectColor(profile?.color || 'zinc') }}
    >
      {photo ? (
        <img src={photo} alt="" draggable={false} onError={() => setBroken(photo)} className="size-full rounded-full object-cover" />
      ) : profile?.emoji ? (
        // leading-none + flex: the glyph sits in the middle of the circle, not on the text baseline
        <span className={cn('flex items-center justify-center leading-none', size === 'lg' ? 'text-[22px]' : size === 'sm' ? 'text-[11px]' : 'text-[15px]')}>{profile.emoji}</span>
      ) : (
        initials(name)
      )}
      {agent && (
        <span className="absolute -right-1 -bottom-1 inline-flex size-3.5 items-center justify-center rounded-full bg-background text-foreground ring-1 ring-border">
          <Bot className="size-2.5" />
        </span>
      )}
    </span>
  )
}

/** Avatar + pseudo on one line. */
export function PersonChip({ profile, agent, label, size = 'sm', className }: { profile: Partial<Profile> | null | undefined; agent?: boolean; label?: string; size?: 'sm' | 'md'; className?: string }) {
  return (
    <span className={cn('inline-flex min-w-0 items-center gap-1.5', className)}>
      <Avatar profile={profile} agent={agent} size={size} />
      <span className="truncate font-medium">{label ?? profile?.name}</span>
    </span>
  )
}
