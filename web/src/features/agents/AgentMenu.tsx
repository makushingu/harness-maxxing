// Right click (a long press on a phone) on an agent of the list or the Office: a menu at the pointer with its quick
// properties - silent, switched on, run now - and Properties… (its settings sheet).
import * as React from 'react'
import { useNavigate } from 'react-router'
import { BellOff, Play, Power, Settings2 } from 'lucide-react'
import { useT } from '@/i18n'
import { agentRoute, usePatchAgent } from '@/lib/queries'
import type { Agent } from '@/lib/types'
import { useLongPress } from '@/lib/long-press'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useRunNow } from './parts'

/** Spread `props` on the agent's element (it must be `relative`: the menu opens where it was clicked) and render `menu` inside it. */
export function useAgentMenu(a: Agent) {
  const t = useT()
  const navigate = useNavigate()
  const patch = usePatchAgent()
  const run = useRunNow()
  const [at, setAt] = React.useState<{ x: number; y: number } | null>(null)
  const el = React.useRef<HTMLElement | null>(null)
  const last = React.useRef<{ x: number; y: number }>({ x: 0, y: 0 })
  const openAt = (target: HTMLElement, x: number, y: number) => {
    const r = target.getBoundingClientRect()
    setAt({ x: x - r.left, y: y - r.top })
  }
  const press = useLongPress(() => el.current && openAt(el.current, last.current.x, last.current.y))
  const props = {
    onContextMenu: (e: React.MouseEvent<HTMLElement>) => {
      e.preventDefault()
      openAt(e.currentTarget, e.clientX, e.clientY)
    },
    ...press,
    onTouchStart: (e: React.TouchEvent<HTMLElement>) => {
      el.current = e.currentTarget
      const p = e.touches[0]
      if (p) last.current = { x: p.clientX, y: p.clientY }
      press.onTouchStart?.(e)
    },
  }
  const stop = (e: React.SyntheticEvent) => e.stopPropagation()
  const menu = (
    <DropdownMenu open={!!at} onOpenChange={(o) => !o && setAt(null)}>
      <DropdownMenuTrigger asChild>
        <span aria-hidden tabIndex={-1} className="pointer-events-none absolute size-0" style={{ left: at?.x ?? 0, top: at?.y ?? 0 }} />
      </DropdownMenuTrigger>
      {/* the agent's element opens its page on a click: nothing in the menu reaches it */}
      <DropdownMenuContent align="start" className="w-56" onClick={stop} onKeyDown={stop} aria-label={t('agents.menu.label', { name: a.display_name })} data-testid="agent-menu">
        <DropdownMenuLabel className="truncate">{a.display_name}</DropdownMenuLabel>
        <DropdownMenuCheckboxItem checked={a.silent} onCheckedChange={(v) => patch.mutate({ path: a.path, silent: v })} data-testid="agent-menu-silent">
          <BellOff /> {t('agents.menu.silent')}
        </DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem checked={a.enabled} onCheckedChange={(v) => patch.mutate({ path: a.path, enabled: v })} data-testid="agent-menu-enabled">
          <Power /> {t('agents.menu.enabled')}
        </DropdownMenuCheckboxItem>
        <DropdownMenuItem disabled={!a.enabled} onSelect={() => run.go(a)} data-testid="agent-menu-run">
          <Play /> {t('agents.run.now')}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => navigate(`${agentRoute(a)}?settings=1`)} data-testid="agent-menu-properties">
          <Settings2 /> {t('agents.menu.properties')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
  return { props, menu }
}

/** The small bell-off next to a silent agent's name. */
export function SilentMark({ agent: a }: { agent: Pick<Agent, 'silent'> }) {
  const t = useT()
  if (!a.silent) return null
  return <BellOff className="inline size-3 shrink-0 text-muted-foreground" aria-label={t('agents.silentBadge')} role="img" data-testid="agent-silent" />
}
