// The composer's "/" menu, as in Claude Code: typing "/" at the start of the message lists the commands - the
// session's own (model, intelligence, plan mode, compact...) and the skills its topic sees (GET /api/skills?path=).
// ↑/↓ choose, Tab completes, Enter runs (a command that needs a value shows its values next), Esc closes.
// A skill is sent as typed ("/name args"): Claude Code starts it. A session command never reaches Claude.
import * as React from 'react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'

/** The menu's groups, in this order: the session's commands, the skills of this topic / project, the others. */
export type SlashGroup = 'session' | 'here' | 'other'
const GROUPS: SlashGroup[] = ['session', 'here', 'other']
/** A group of skills longer than this is folded when nothing is typed: its first rows, then "+ N more". */
export const FOLD = 6

export type SlashArg = { value: string; label: string; hint?: string; current?: boolean }
export type SlashCommand = {
  name: string
  description: string
  kind: 'action' | 'skill'
  group?: SlashGroup
  /** Values offered after "/name " (model ids, levels); free text is accepted too when `freeArg`. */
  args?: SlashArg[]
  freeArg?: boolean
  /** Session command: runs instead of sending (`arg` = what follows the name, trimmed). */
  run?: (arg: string) => void
}

/** A row of the composer's menus ("/" commands, "@" mentions). */
export type MenuRow = { key: string; label: string; hint: string; badge?: string; current?: boolean; icon?: React.ReactNode; /** Title shown above the first row of its group ("@session"...: the @ menu's). */ group?: string; /** "+ N more": unfolds the group. */ more?: number }
export type SlashItem = MenuRow & { cmd: SlashCommand; arg?: string; /** The "+ N more" row of this group. */ expand?: SlashGroup }

export const fold = (s: string) => s.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase()

/** What the menu shows for the text typed so far (null: no menu). */
export function slashItems(text: string, commands: SlashCommand[], expanded: string[] = []): { stage: 'name' | 'arg'; items: SlashItem[] } | null {
  if (!text.startsWith('/') || text.includes('\n')) return null
  const named = /^\/(\S*)$/.exec(text)
  if (named) {
    const q = fold(named[1])
    const starts = commands.filter((c) => fold(c.name).startsWith(q))
    // then the names containing it; the descriptions only when no name matches ("/se" is /seo-audit, not every
    // command whose description says "session")
    const inName = q ? commands.filter((c) => !fold(c.name).startsWith(q) && fold(c.name).includes(q)) : []
    const inside = !q ? [] : starts.length || inName.length ? inName : commands.filter((c) => fold(c.description).includes(q))
    const found = [...starts, ...inside]
    const items: SlashItem[] = []
    for (const g of GROUPS) {
      const rows = found.filter((c) => (c.group || (c.kind === 'skill' ? 'other' : 'session')) === g)
      const fold = !q && g !== 'session' && rows.length > FOLD && !expanded.includes(g)
      for (const c of fold ? rows.slice(0, FOLD - 1) : rows)
        items.push({ key: `${c.kind}:${c.name}`, label: `/${c.name}`, hint: c.description, group: g, cmd: c })
      if (fold) items.push({ key: `more:${g}`, label: '', hint: '', group: g, more: rows.length - FOLD + 1, expand: g, cmd: { name: '', kind: 'action', description: '' } })
    }
    return items.length ? { stage: 'name', items } : null
  }
  const withArg = /^\/(\S+) (.*)$/.exec(text)
  if (!withArg) return null
  const cmd = commands.find((c) => c.name === withArg[1])
  if (!cmd?.args?.length) return null
  const q = fold(withArg[2].trim())
  const items = cmd.args
    .filter((a) => !q || fold(a.value).includes(q) || fold(a.label).includes(q))
    .map((a) => ({ key: a.value || '-', label: a.label, hint: a.hint || '', current: a.current, cmd, arg: a.value }))
  return items.length ? { stage: 'arg', items } : null
}

/** The session command typed in full ("/model opus"), if any: it runs instead of being sent. */
export function slashAction(text: string, commands: SlashCommand[]): { cmd: SlashCommand; arg: string } | null {
  const m = /^\/(\S+)(?:\s+([\s\S]*))?$/.exec(text.trim())
  if (!m) return null
  const cmd = commands.find((c) => c.kind === 'action' && c.name === m[1])
  return cmd?.run ? { cmd, arg: (m[2] || '').trim() } : null
}

function groupTitle(g: string, t: ReturnType<typeof useT>): string {
  const titles: Record<string, string> = {
    session: t('sessions.slash.group.session'),
    here: t('sessions.slash.group.here'),
    other: t('sessions.slash.group.other'),
    '@session': t('sessions.mention.group.session'),
    '@agent': t('sessions.mention.group.agent'),
    '@team': t('sessions.mention.group.team'),
  }
  return titles[g] || g
}

export function SlashMenu({ items, active, onPick, onHover, stage, label, keys }: { items: MenuRow[]; active: number; onPick: (i: number) => void; onHover: (i: number) => void; stage: 'name' | 'arg'; label?: string; keys?: string }) {
  const t = useT()
  const list = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    list.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [active])
  return (
    <div
      role="listbox"
      aria-label={label || t('sessions.slash.label')}
      data-testid="slash-menu"
      className="absolute inset-x-0 bottom-full z-30 mb-1.5 overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-lg"
    >
      <div ref={list} className="max-h-72 overflow-y-auto overscroll-contain p-1 [scrollbar-width:thin]">
        {items.map((it, i) => (
          <React.Fragment key={it.key}>
          {it.group && it.group !== items[i - 1]?.group && (
            <div className={cn('px-2.5 pt-1.5 pb-0.5 text-[10px] font-medium tracking-wide text-muted-foreground uppercase', i > 0 && 'mt-1 border-t pt-2')}>
              {groupTitle(it.group, t)}
            </div>
          )}
          <div
            role="option"
            aria-selected={i === active}
            data-index={i}
            onMouseDown={(e) => {
              e.preventDefault() // keep the focus (and the caret) in the textarea
              onPick(i)
            }}
            onMouseMove={() => i !== active && onHover(i)}
            className={cn('flex cursor-pointer items-baseline gap-3 rounded-md px-2.5 py-1.5 text-sm', it.icon && 'items-center', i === active && 'bg-accent text-accent-foreground')}
          >
            {it.icon}
            {it.more ? (
              // "+ N more"

              <span className="text-xs text-muted-foreground">{t('sessions.slash.more', { count: it.more })}</span>
            ) : (
              <span className={cn('shrink-0', stage === 'name' && 'font-mono text-[13px]', it.current && 'font-semibold')}>
                {it.label}
                {it.current && <span className="ml-1.5 text-[10px] font-normal text-muted-foreground">✓</span>}
              </span>
            )}
            <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{it.hint}</span>
            {it.badge && <span className="shrink-0 rounded bg-muted px-1 text-[10px] text-muted-foreground">{it.badge}</span>}
          </div>
          </React.Fragment>
        ))}
      </div>
      <div className="border-t px-2.5 py-1 text-[10px] text-muted-foreground max-md:hidden">{keys || t('sessions.slash.keys')}</div>
    </div>
  )
}
