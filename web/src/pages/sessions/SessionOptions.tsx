// The session's options: its "..." and a right click (a long press) on its header open this window
// (a bottom sheet on a phone). Switches apply at once and keep it open; an action runs and closes it.
import * as React from 'react'
import { Link } from 'react-router'
import { Archive, ArchiveRestore, Bell, FolderOpen, ListChecks, Minimize2, PictureInPicture2, Sparkles, Trash2, type LucideIcon } from 'lucide-react'
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Switch } from '@/components/ui/switch'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import type { Session } from '@/lib/types'

export type OptionAction = { key: string; label: string; icon: LucideIcon; disabled?: boolean; run: () => void }

export function SessionOptions({
  open,
  onOpenChange,
  session,
  tgLinked,
  running,
  agentRun,
  onPlan,
  onNotify,
  onCompact,
  onHandoff,
  onFolder,
  onHud,
  onArchive,
  onDelete,
  column,
  keepFocus,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  session: Session
  tgLinked: boolean
  running: boolean
  /** A run of an agent: it is neither archived nor deleted from here. */
  agentRun?: boolean
  onPlan: () => void
  onNotify: () => void
  onCompact: () => void
  onHandoff: () => void
  onFolder?: () => void
  onHud?: () => void
  onArchive: () => void
  onDelete: () => void
  /** Desktop columns: open in a window, stack, layouts (absent on a phone). */
  column?: OptionAction[]
  /** On close, the focus stays where an action put it (the layout picker) instead of going back to "...". */
  keepFocus?: () => boolean
}) {
  const t = useT()
  const run = (f: () => void) => () => {
    onOpenChange(false)
    f()
  }
  const idle = !running && !!session.turns
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-0 p-0 sm:max-w-sm" onCloseAutoFocus={(e) => keepFocus?.() && e.preventDefault()} data-testid="session-options">
        <div className="px-5 pt-5 pb-3 max-md:pt-1">
          <DialogTitle className="truncate pr-6">{session.title || t('sessions.options.title')}</DialogTitle>
          <DialogDescription className="sr-only">{t('sessions.options.desc')}</DialogDescription>
        </div>

        <div className="border-t px-2 py-2">
          <Toggle icon={ListChecks} label={t('plan.toggle')} hint={t('sessions.options.planHint')} checked={!!session.plan_mode} onChange={onPlan} />
          {tgLinked ? (
            <Toggle icon={Bell} label={t('sessions.options.notify')} hint={t('sessions.options.notifyHint')} checked={!!session.notify} onChange={onNotify} />
          ) : (
            <div className="flex items-center gap-3 rounded-lg px-3 py-2.5">
              <Bell className="size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <div className="text-sm">{t('sessions.options.notify')}</div>
                <div className="text-xs text-muted-foreground">{t('sessions.options.notifyOff')}</div>
              </div>
              <Button asChild size="sm" variant="outline" onClick={() => onOpenChange(false)}>
                <Link to="/settings/telegram">{t('sessions.options.linkTelegram')}</Link>
              </Button>
            </div>
          )}
        </div>

        <div className="border-t px-2 py-2">
          <Row icon={Minimize2} label={t('sessions.menu.compact')} disabled={!idle} onClick={run(onCompact)} />
          <Row icon={Sparkles} label={t('sessions.menu.handoff')} disabled={!idle} onClick={run(onHandoff)} />
          {onFolder && <Row icon={FolderOpen} label={t('sessions.menu.openFolder')} onClick={run(onFolder)} />}
          {onHud && <Row icon={PictureInPicture2} label={t('hud.open')} onClick={run(onHud)} />}
        </div>

        {!!column?.length && (
          <div className="border-t px-2 py-2">
            {column.map((a) => (
              <Row key={a.key} icon={a.icon} label={a.label} disabled={a.disabled} onClick={run(a.run)} />
            ))}
          </div>
        )}

        {!agentRun && (
          <div className="flex items-center justify-between border-t px-3 py-2.5">
            <Button size="sm" variant="ghost" onClick={run(onArchive)}>
              {session.archived ? <ArchiveRestore /> : <Archive />} {session.archived ? t('sessions.menu.unarchive') : t('sessions.menu.archive')}
            </Button>
            <Button size="sm" variant="ghost" className="text-destructive hover:bg-destructive/10 hover:text-destructive" onClick={run(onDelete)}>
              <Trash2 /> {t('common.delete')}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function Toggle({ icon: Icon, label, hint, checked, onChange }: { icon: LucideIcon; label: string; hint: string; checked: boolean; onChange: () => void }) {
  const id = React.useId()
  return (
    <label htmlFor={id} className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 hover:bg-accent/60">
      <Icon className={cn('size-4 shrink-0', checked ? 'text-primary' : 'text-muted-foreground')} />
      <span className="min-w-0 flex-1">
        <span className="block text-sm">{label}</span>
        <span className="block text-xs text-muted-foreground">{hint}</span>
      </span>
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
    </label>
  )
}

function Row({ icon: Icon, label, disabled, onClick }: { icon: LucideIcon; label: string; disabled?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm outline-none hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 pointer-coarse:py-2.5"
    >
      <Icon className="size-4 shrink-0 text-muted-foreground" /> {label}
    </button>
  )
}
