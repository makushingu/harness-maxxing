// Right click (a long press on a phone) on an agent of the list or the Office: a menu at the pointer with its quick
// properties - silent, switched on, run now -, its role, its name and look (the character at its desk), Properties…
// (its settings sheet) and Delete… (the same confirmation as in its settings).
import * as React from 'react'
import { useNavigate } from 'react-router'
import { BellOff, NotebookPen, Palette, Play, Power, Settings2, Trash2 } from 'lucide-react'
import { useT } from '@/i18n'
import { agentRoute, usePatchAgent } from '@/lib/queries'
import type { Agent } from '@/lib/types'
import { useLongPress } from '@/lib/long-press'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Textarea, toast } from '@/components/ui'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { AppearanceDialog } from './Appearance'
import { useDeleteAgentAsk, useRunNow } from './parts'

/** Spread `props` on the agent's element (it must be `relative`: the menu opens where it was clicked) and render `menu` inside it. */
export function useAgentMenu(a: Agent) {
  const t = useT()
  const navigate = useNavigate()
  const patch = usePatchAgent()
  const run = useRunNow()
  const del = useDeleteAgentAsk()
  // the dialogs opened from the menu; mounted once asked for (not one per agent of the list before that)
  const [dialog, setDialog] = React.useState<'role' | 'look' | null>(null)
  const [asked, setAsked] = React.useState(false)
  const show = (d: 'role' | 'look') => (setAsked(true), setDialog(d))
  // the menu closing gives the focus back to the agent's element, which shows its tooltip over the dialog: not then
  const keepFocus = (e: Event) => dialog && e.preventDefault()
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
      {/* the agent's element opens its page on a click and shows a tooltip on hover: nothing in the menu reaches it */}
      <DropdownMenuContent align="start" className="w-56" onCloseAutoFocus={keepFocus} onClick={stop} onKeyDown={stop} onPointerMove={stop} onFocus={stop} aria-label={t('agents.menu.label', { name: a.display_name })} data-testid="agent-menu">
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
        <DropdownMenuItem onSelect={() => show('role')} data-testid="agent-menu-role">
          <NotebookPen /> {t('agents.menu.role')}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => show('look')} data-testid="agent-menu-look">
          <Palette /> {t('agents.menu.look')}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => navigate(`${agentRoute(a)}?settings=1`)} data-testid="agent-menu-properties">
          <Settings2 /> {t('agents.menu.properties')}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem destructive disabled={del.pending} onSelect={() => del.ask(a)} data-testid="agent-menu-delete">
          <Trash2 /> {t('agents.menu.delete')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
  // React events of the dialogs (portals) still bubble to the agent's element: a click there must not open the agent,
  // a long press must not open this menu again, a focus or a move must not show the desk's tooltip
  const dialogs = asked && (
    <span
      className="contents"
      onClick={stop}
      onKeyDown={stop}
      onContextMenu={stop}
      onTouchStart={stop}
      onTouchMove={stop}
      onTouchEnd={stop}
      onDragStart={stop}
      onPointerDown={stop}
      onPointerMove={stop}
      onFocus={stop}
      onBlur={stop}
    >
      <RoleDialog agent={a} open={dialog === 'role'} onOpenChange={(o) => setDialog(o ? 'role' : null)} />
      <AppearanceDialog agent={a} open={dialog === 'look'} onOpenChange={(o) => setDialog(o ? 'look' : null)} />
    </span>
  )
  return {
    props,
    menu: (
      <>
        {menu}
        {dialogs}
      </>
    ),
  }
}

/** The role (the first paragraph of its CLAUDE.md) in a small dialog, as in its profile. */
function RoleDialog({ agent: a, open, onOpenChange }: { agent: Agent; open: boolean; onOpenChange: (o: boolean) => void }) {
  const t = useT()
  const patch = usePatchAgent()
  const [v, setV] = React.useState(a.description)
  React.useEffect(() => {
    if (open) setV(a.description)
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="md:max-w-xl" data-testid="agent-role-dialog">
        <DialogHeader>
          <DialogTitle>{t('agents.menu.roleTitle', { name: a.display_name })}</DialogTitle>
          <DialogDescription>{t('agents.menu.roleDesc')}</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            patch.mutate({ path: a.path, description: v }, { onSuccess: () => (toast.success(t('agents.role.saved')), onOpenChange(false)) })
          }}
        >
          <Textarea autoFocus minRows={5} maxRows={20} value={v} onChange={(e) => setV(e.target.value)} placeholder={t('agents.create.rolePlaceholder')} data-testid="agent-role-dialog-edit" />
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={patch.isPending} data-testid="agent-role-dialog-save">
              {t('common.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** The small bell-off next to a silent agent's name. */
export function SilentMark({ agent: a }: { agent: Pick<Agent, 'silent'> }) {
  const t = useT()
  if (!a.silent) return null
  return <BellOff className="inline size-3 shrink-0 text-muted-foreground" aria-label={t('agents.silentBadge')} role="img" data-testid="agent-silent" />
}
