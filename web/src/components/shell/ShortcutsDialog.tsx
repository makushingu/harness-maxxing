import { useT, type TKey } from '@/i18n'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, Kbd, MOD } from '@/components/ui'
import { useNav } from './nav'
import { useShortcutsDialog } from './shortcuts-store'


/** Extra shortcuts registered by pages (shown in the dialog under the page's group). */
export type ShortcutDoc = { keys: string[]; label: TKey }
export const GLOBAL_SHORTCUTS: ShortcutDoc[] = [
  { keys: [MOD, 'K'], label: 'shortcuts.palette' },
  { keys: ['?'], label: 'shortcuts.help' },
  { keys: [MOD, '\\'], label: 'shortcuts.sidebar' },
  { keys: ['Shift', 'P'], label: 'shortcuts.presentation' },
]

export function ShortcutsDialog() {
  const t = useT()
  const nav = useNav()
  const { open, setOpen } = useShortcutsDialog()
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="md:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('shortcuts.title')}</DialogTitle>
          <DialogDescription>{t('shortcuts.description')}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-6 sm:grid-cols-2">
          <Group title={t('shortcuts.general')} rows={GLOBAL_SHORTCUTS.map((s) => ({ keys: s.keys, label: t(s.label) }))} />
          <Group title={t('shortcuts.navigation')} rows={nav.map((n) => ({ keys: ['G', n.key.toUpperCase()], label: t(n.label) }))} />
        </div>
      </DialogContent>
    </Dialog>
  )
}

function Group({ title, rows }: { title: string; rows: { keys: string[]; label: string }[] }) {
  return (
    <div className="grid content-start gap-2">
      <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{title}</h3>
      <ul className="grid gap-1.5">
        {rows.map((r) => (
          <li key={r.label} className="flex items-center justify-between gap-3 text-sm">
            <span>{r.label}</span>
            <span className="flex gap-1">
              {r.keys.map((k) => (
                <Kbd key={k}>{k}</Kbd>
              ))}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
