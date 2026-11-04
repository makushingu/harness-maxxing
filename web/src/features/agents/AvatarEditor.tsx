// Picks each of the 6 parts of an agent's pixel character (one compact row each: a label, then swatches or small
// previews), or all at random. `project` = the agent's project: Random keeps its outfit colour, marked by a dot.
import { Dices } from 'lucide-react'
import { tDyn, useT } from '@/i18n'
import { cn } from '@/lib/utils'
import type { AgentAvatar } from '@/lib/types'
import { Button } from '@/components/ui'
import { AVATAR_OPTIONS, AVATAR_PARTS, AgentAvatarIcon, HAIR, OUTFIT, SKIN, randomAvatar, type AvatarPart } from './Avatar'
import { useProjectColorOf } from './layout'

const SWATCHES: Partial<Record<AvatarPart, Record<string, string>>> = { color: OUTFIT, skin: SKIN, hair_color: HAIR }

/** `preview` false = the rows only (the caller shows the character and Random, as the creation form does). */
export function AvatarEditor({ value, onChange, project, className, preview = true }: { value: AgentAvatar; onChange: (a: AgentAvatar) => void; project?: string; className?: string; preview?: boolean }) {
  const t = useT()
  const colorOf = useProjectColorOf()
  return (
    <div className={cn('@container', className)} data-testid="avatar-editor">
      <div className={cn('grid gap-4', preview && '@lg:grid-cols-[auto_minmax(0,1fr)] @lg:gap-6')}>
        <div className={cn('flex items-center gap-3 @lg:flex-col', !preview && 'hidden')}>
          <AgentAvatarIcon avatar={value} size={96} animate />
          <Button type="button" variant="outline" size="sm" onClick={() => onChange(randomAvatar(project ? colorOf(project) : undefined))} data-testid="avatar-random">
            <Dices /> {t('agents.avatar.random')}
          </Button>
        </div>
        <div className="grid min-w-0 content-start gap-2.5">
          {AVATAR_PARTS.map((part) => (
            <PartRow key={part} part={part} value={value} onChange={onChange} project={project} />
          ))}
        </div>
      </div>
    </div>
  )
}

function PartRow({ part, value, onChange, project }: { part: AvatarPart; value: AgentAvatar; onChange: (a: AgentAvatar) => void; project?: string }) {
  const t = useT()
  const label = t(`agents.avatar.${part}` as 'agents.avatar.color')
  const colorOf = useProjectColorOf()
  const mine = part === 'color' && project ? colorOf(project) : null
  const swatches = SWATCHES[part]
  return (
    <div className="grid items-center gap-1.5 @sm:grid-cols-[6rem_minmax(0,1fr)]" role="radiogroup" aria-label={label}>
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div className="flex flex-wrap gap-1.5">
        {AVATAR_OPTIONS[part].map((opt) => {
          const selected = value[part] === opt
          const base = tDyn(t, `agents.avatar.${part}.${opt}`, opt)
          const name = opt === mine ? `${base} (${t('agents.avatar.projectColor')})` : base
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
                'relative grid place-items-center rounded-md border border-transparent transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                swatches ? 'size-8 max-md:size-10' : 'size-10 max-md:size-11',
                selected && 'border-primary bg-accent',
              )}
              data-testid={`avatar-${part}-${opt}`}
            >
              {swatches ? (
                <span className="size-5 rounded-full border border-black/15" style={{ background: swatches[opt] }} />
              ) : (
                <AgentAvatarIcon avatar={{ ...value, [part]: opt }} size={32} tile={false} />
              )}
              {opt === mine && <span className="absolute top-0.5 right-0.5 size-1.5 rounded-full bg-foreground" aria-hidden />}
            </button>
          )
        })}
      </div>
    </div>
  )
}
