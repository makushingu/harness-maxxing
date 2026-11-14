// What a browser shows while it sleeps: a backdrop in its project's colour (the outfit colour of the project's agents
// on the Agents page) with a small white window on it (window buttons, a moon, "Asleep"). No project (the General
// profile) = a neutral backdrop.
import * as React from 'react'
import { Moon } from 'lucide-react'
import { OUTFIT } from '@/features/agents/Avatar'
import { useProjectColorOf } from '@/features/agents/layout'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'

/** "projects/acme/..." or "acme" -> "acme"; "" stays "". */
const projectName = (p: string) => p.match(/^projects\/([^/]+)/)?.[1] ?? p

export function AsleepScene({ project, label, size = 'sm', className, children }: {
  /** the project (its name or a path inside it), "" for none */
  project: string
  /** the line under "Asleep" */
  label?: string
  size?: 'sm' | 'lg'
  className?: string
  /** under the window (a button) */
  children?: React.ReactNode
}) {
  const t = useT()
  const colorOf = useProjectColorOf()
  const name = projectName(project)
  const hex = name ? OUTFIT[colorOf(name)] : ''
  const big = size === 'lg'
  return (
    <div
      className={cn('grid size-full place-items-center content-center gap-4 overflow-hidden', !hex && 'bg-muted', big ? 'p-8' : 'p-3', className)}
      style={hex ? { background: `linear-gradient(135deg, color-mix(in oklab, ${hex} 70%, white), ${hex})` } : undefined}
      data-testid="browser-asleep"
    >
      <div className={cn('grid w-full overflow-hidden rounded-md bg-white text-zinc-500 shadow-lg ring-1 ring-black/10', big ? 'max-w-sm' : 'max-w-[78%]')}>
        <div className={cn('flex items-center border-b border-zinc-200 bg-zinc-50', big ? 'gap-1.5 px-2.5 py-2' : 'gap-1 px-1.5 py-1')} aria-hidden>
          {['#ff5f57', '#febc2e', '#28c840'].map((c) => (
            <span key={c} className={cn('rounded-full', big ? 'size-2.5' : 'size-1.5')} style={{ background: c }} />
          ))}
        </div>
        <div className={cn('grid justify-items-center text-center', big ? 'gap-1.5 px-4 py-6' : 'gap-0.5 px-2 py-2.5')}>
          <span className={cn('inline-flex items-center gap-1.5 font-medium text-zinc-700', big ? 'text-sm' : 'text-[12px]')}>
            <Moon className={big ? 'size-4' : 'size-3.5'} /> {t('browser.asleepTitle')}
          </span>
          {label && <span className={cn('leading-snug', big ? 'text-[12px]' : 'text-[10.5px]')}>{label}</span>}
        </div>
      </div>
      {children}
    </div>
  )
}
