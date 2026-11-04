// Picks each part of an agent's pixel character with small previews, grouped (face, hair, style), or all at random.
// `project` = the agent's project: Random keeps its outfit colour, and that colour is marked in the outfit row.
import { Dices } from 'lucide-react'
import { tDyn, useT } from '@/i18n'
import { cn } from '@/lib/utils'
import type { AgentAvatar } from '@/lib/types'
import { Button } from '@/components/ui'
import { AVATAR_OPTIONS, AgentAvatarIcon, HAIR, SKIN, SWATCH, projectColor, randomAvatar, type AvatarPart } from './Avatar'

const GROUPS: { id: 'face' | 'hair' | 'style'; parts: AvatarPart[] }[] = [
  { id: 'face', parts: ['skin', 'head', 'eyes', 'mouth'] },
  { id: 'hair', parts: ['hair', 'hair_color'] },
  { id: 'style', parts: ['hat', 'color', 'bg'] },
]
/** The size of the preview in a 40 px button: zoomed on the face for the small parts, whole for the others. */
const ZOOM: Partial<Record<AvatarPart, number>> = { eyes: 80, mouth: 80, head: 60 }

export function AvatarEditor({ value, onChange, project, className }: { value: AgentAvatar; onChange: (a: AgentAvatar) => void; project?: string; className?: string }) {
  const t = useT()
  return (
    <div className={cn('grid gap-4 sm:grid-cols-[auto_minmax(0,1fr)]', className)} data-testid="avatar-editor">
      <div className="flex items-center gap-3 sm:flex-col sm:items-center">
        <div className="rounded-2xl border bg-card p-2">
          <AgentAvatarIcon avatar={value} size={100} animate />
        </div>
        <Button type="button" variant="outline" size="sm" onClick={() => onChange(randomAvatar(project))} data-testid="avatar-random">
          <Dices /> {t('agents.avatar.random')}
        </Button>
      </div>
      <div className="grid min-w-0 gap-4">
        {GROUPS.map((g) => (
          <fieldset key={g.id} className="grid min-w-0 gap-2.5">
            <legend className="mb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">{t(`agents.avatar.group.${g.id}` as 'agents.avatar.group.face')}</legend>
            {g.parts.map((part) => (
              <PartRow key={part} part={part} value={value} onChange={onChange} project={project} />
            ))}
          </fieldset>
        ))}
      </div>
    </div>
  )
}

function swatchOf(part: AvatarPart, opt: string): string | null {
  if (part === 'color' || part === 'bg') return part === 'bg' ? SWATCH[opt].tile : SWATCH[opt].body
  if (part === 'skin') return SKIN[opt][0]
  if (part === 'hair_color') return HAIR[opt][0]
  return null
}

function PartRow({ part, value, onChange, project }: { part: AvatarPart; value: AgentAvatar; onChange: (a: AgentAvatar) => void; project?: string }) {
  const t = useT()
  const label = t(`agents.avatar.${part}` as 'agents.avatar.color')
  const mine = part === 'color' && project ? projectColor(project) : null
  return (
    <div className="grid gap-1.5" role="radiogroup" aria-label={label}>
      <span className="text-xs font-medium text-muted-foreground">
        {label}
        {mine && <span className="font-normal"> · {t('agents.avatar.colorHint')}</span>}
      </span>
      <div className="flex flex-wrap gap-1.5">
        {AVATAR_OPTIONS[part].map((opt) => {
          const selected = value[part] === opt
          const base = tDyn(t, `agents.avatar.${part === 'bg' ? 'color' : part}.${opt}`, opt)
          const name = opt === mine ? `${base} (${t('agents.avatar.projectColor')})` : base
          const swatch = swatchOf(part, opt)
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
                'relative flex size-10 items-center justify-center overflow-hidden rounded-lg border bg-card transition-colors hover:border-primary/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none max-md:size-11',
                selected && 'border-primary ring-2 ring-primary/40',
              )}
              data-testid={`avatar-${part}-${opt}`}
            >
              {swatch ? (
                <span className={cn('size-6 border border-black/15', part === 'bg' ? 'rounded-md' : 'rounded-full')} style={{ background: swatch }} />
              ) : (
                <AgentAvatarIcon avatar={{ ...value, [part]: opt }} size={ZOOM[part] || 40} tile={!ZOOM[part]} />
              )}
              {opt === mine && <span className="absolute top-0.5 right-0.5 size-1.5 rounded-full bg-foreground" aria-hidden />}
            </button>
          )
        })}
      </div>
    </div>
  )
}
