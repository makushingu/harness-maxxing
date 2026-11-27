import * as React from 'react'
import { ChevronDown } from 'lucide-react'
import { useWorkspace } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Button, Checkbox } from '@/components/ui'

const short = (path: string) => path.replace(/^projects\//, '').replace('/topics/', ' / ')

/** The muted label of a key limited to some projects / topics (nothing when it is given to every topic). */
export function KeyScopeLabel({ topics }: { topics?: string[] }) {
  const t = useT()
  if (!topics?.length) return null
  return (
    <span className="shrink-0 whitespace-pre" title={topics.map(short).join('\n')}>
      {' · '}
      {t('keys.scopeCount', { count: topics.length })}
    </span>
  )
}

function Row({ checked, disabled, onChange, indent, children }: { checked: boolean; disabled?: boolean; onChange: (on: boolean) => void; indent?: boolean; children: React.ReactNode }) {
  return (
    <label className={cn('flex min-w-0 items-center gap-2 px-3 py-1.5 text-[13px]', indent && 'pl-9', disabled && 'text-muted-foreground')}>
      <Checkbox checked={checked} disabled={disabled} onCheckedChange={(v) => onChange(v === true)} />
      <span className="truncate">{children}</span>
    </label>
  )
}

/** "Topics: all" under the expose switch: which projects / topics get the key (`[]` = every topic).
 *  A ticked project covers its topics, present and future. */
export function KeyTopics({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const t = useT()
  const { data } = useWorkspace()
  const [open, setOpen] = React.useState(false)
  const projects = data?.projects ?? []
  const known = new Set(projects.flatMap((p) => [p.path, ...p.topics.map((x) => x.path)]))
  const gone = value.filter((v) => !known.has(v))
  const toggle = (path: string, on: boolean) => {
    // a project replaces the entries of its own topics
    const rest = value.filter((v) => v !== path && !(on && v.startsWith(path + '/')))
    onChange(on ? [...rest, path] : rest)
  }
  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between gap-3 text-[13px]">
        <span className="min-w-0 truncate">
          <span className="font-medium">{t('keys.scope')}</span>
          <span className="text-muted-foreground"> {value.length ? t('keys.scopeCount', { count: value.length }) : t('keys.scopeAll')}</span>
        </span>
        <span className="flex shrink-0 items-center gap-1">
          {value.length > 0 && (
            <Button variant="ghost" size="sm" onClick={() => onChange([])}>
              {t('keys.scopeClear')}
            </Button>
          )}
          <Button variant="outline" size="sm" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {t('keys.scopeChoose')} <ChevronDown className={cn('transition-transform', open && 'rotate-180')} />
          </Button>
        </span>
      </div>
      {open && (
        <div className="max-h-52 overflow-y-auto rounded-lg border py-1">
          {projects.map((p) => {
            const whole = value.includes(p.path)
            return (
              <React.Fragment key={p.path}>
                <Row checked={whole} onChange={(on) => toggle(p.path, on)}>
                  <span className="font-medium">{p.name}</span>
                </Row>
                {p.topics.map((x) => (
                  <Row key={x.path} indent checked={whole || value.includes(x.path)} disabled={whole} onChange={(on) => toggle(x.path, on)}>
                    {x.name}
                  </Row>
                ))}
              </React.Fragment>
            )
          })}
          {gone.map((v) => (
            <Row key={v} checked onChange={() => toggle(v, false)}>
              <span className="text-muted-foreground">{short(v)}</span>
            </Row>
          ))}
          {!projects.length && !gone.length && <p className="px-3 py-1.5 text-[13px] text-muted-foreground">{t('keys.scopeEmpty')}</p>}
        </div>
      )}
      <p className="text-xs text-muted-foreground">{t('keys.scopeHint')}</p>
    </div>
  )
}
