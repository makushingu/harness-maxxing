// Picks each part of an agent's face (colour, eyes, mouth, hat, background) with small previews, or all at random.
import { Dices } from 'lucide-react'
import { tDyn, useT } from '@/i18n'
import { cn } from '@/lib/utils'
import type { AgentAvatar } from '@/lib/types'
import { Button } from '@/components/ui'
import { AVATAR_OPTIONS, AVATAR_PARTS, AgentAvatarIcon, SWATCH, randomAvatar, type AvatarPart } from './Avatar'

export function AvatarEditor({ value, onChange, className }: { value: AgentAvatar; onChange: (a: AgentAvatar) => void; className?: string }) {
  const t = useT()
  return (
    <div className={cn('grid gap-4 sm:grid-cols-[auto_minmax(0,1fr)]', className)} data-testid="avatar-editor">
      <div className="flex items-center gap-3 sm:flex-col sm:items-center">
        <div className="rounded-2xl border bg-card p-2">
          <AgentAvatarIcon avatar={value} size={80} />
        </div>
        <Button type="button" variant="outline" size="sm" onClick={() => onChange(randomAvatar())} data-testid="avatar-random">
          <Dices /> {t('agents.avatar.random')}
        </Button>
      </div>
      <div className="grid min-w-0 gap-3">
        {AVATAR_PARTS.map((part) => (
          <PartRow key={part} part={part} value={value} onChange={onChange} />
        ))}
      </div>
    </div>
  )
}

function PartRow({ part, value, onChange }: { part: AvatarPart; value: AgentAvatar; onChange: (a: AgentAvatar) => void }) {
  const t = useT()
  const label = t(`agents.avatar.${part}` as 'agents.avatar.color')
  return (
    <div className="grid gap-1.5" role="radiogroup" aria-label={label}>
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div className="flex flex-wrap gap-1.5">
        {AVATAR_OPTIONS[part].map((opt) => {
          const selected = value[part] === opt
          const name = tDyn(t, `agents.avatar.${part === 'bg' ? 'color' : part}.${opt}`, opt)
          return (
            <button
              key={opt}
              type="button"
              role="radio"
              aria-checked={selected}
              aria-label={name}
              title={name}
              onClick={() => onChange({ ...value, [part]: opt })}
              className={cn(
                'relative flex size-9 items-center justify-center rounded-lg border bg-card transition-colors hover:border-primary/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none max-md:size-11',
                selected && 'border-primary ring-2 ring-primary/40',
              )}
            >
              {part === 'color' || part === 'bg' ? (
                part === 'bg' ? (
                  <span className="size-6 rounded-md" style={{ background: SWATCH[opt].body, opacity: 0.55 }} />
                ) : (
                  <span className="size-6 rounded-full" style={{ background: SWATCH[opt].body }} />
                )
              ) : (
                <AgentAvatarIcon avatar={{ ...value, [part]: opt }} size={28} />
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
