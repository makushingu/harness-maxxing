// Starter packs: ready-made projects for a kind of work (topics with a playbook, no fake data).
// PackCards = the grid (Settings -> Starter pack: one "Add" per pack, plus the default projects). PackChooser = onboarding (all / choose / none).
import * as React from 'react'
import { Check, Clock, Plus, RotateCcw } from 'lucide-react'
import { useInstallPack, usePacks } from '@/lib/queries'
import type { Pack } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Badge, Button, Checkbox, NamedIcon, Segmented, Skeleton, toast } from '@/components/ui'

function PackCard({ p, action, control, selected }: { p: Pack; action?: React.ReactNode; control?: React.ReactNode; selected?: boolean }) {
  const t = useT()
  return (
    <div
      className={cn(
        'flex h-full flex-col gap-3 rounded-xl border bg-card p-4 transition-colors',
        selected && 'border-primary/60 bg-primary/5',
        p.basics && 'md:col-span-2',
      )}
      data-testid="pack"
      data-pack={p.id}
    >
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <NamedIcon name={p.icon || 'folder'} className="size-5" />
        </span>
        <div className="grid min-w-0 flex-1 gap-0.5">
          <div className="text-sm font-medium">{p.title}</div>
          <p className="text-[13px] leading-snug text-muted-foreground">{p.description}</p>
        </div>
        {control && <div className="flex shrink-0 items-center pt-0.5">{control}</div>}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {p.topics.map((tp) => (
          <span key={tp} className="rounded-md border bg-background/40 px-2 py-0.5 text-xs text-muted-foreground">
            {tp}
          </span>
        ))}
      </div>
      {p.crons.length > 0 && (
        <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <Clock className="mt-px size-3.5 shrink-0" />
          {t('packs.jobs', { list: p.crons.join(', ') })}
        </p>
      )}
      {action && <div className="mt-auto flex justify-end pt-1">{action}</div>}
    </div>
  )
}

function useAdd() {
  const t = useT()
  const install = useInstallPack()
  const add = React.useCallback(
    async (p: Pack, quiet = false) => {
      const r = await install.mutateAsync(p.id)
      if (quiet) return r
      if (p.basics) toast.success(r.created_files ? t('packs.restored', { count: r.created_files }) : t('packs.nothingMissing'))
      else toast.success(t('packs.done', { name: r.project, count: p.topics.length }))
      return r
    },
    [install, t],
  )
  return { add, pending: install.isPending, variables: install.variables }
}

/** Settings -> Starter pack: every pack with its own Add button (a pack can be added several times), and the
 *  default projects with "Put back". */
export function PackCards() {
  const t = useT()
  const { data, isPending } = usePacks()
  const { add, pending, variables } = useAdd()
  if (isPending || !data) {
    return (
      <div className="grid gap-3 md:grid-cols-2">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-44 rounded-xl" />
        ))}
      </div>
    )
  }
  return (
    <div className="grid gap-3 md:grid-cols-2" data-testid="packs">
      {data.packs.map((p) => (
        <PackCard
          key={p.id}
          p={p}
          action={
            <Button size="sm" variant={p.basics ? 'outline' : 'default'} loading={pending && variables === p.id} disabled={pending} onClick={() => void add(p).catch(() => {})}>
              {p.basics ? <RotateCcw /> : <Plus />} {p.basics ? t('packs.restore') : t('packs.add')}
            </Button>
          }
        />
      ))}
    </div>
  )
}

/** Onboarding: install all, choose, or none. `onDone` runs after the chosen packs are added. */
export function PackChooser({ onDone, footer }: { onDone: () => void; footer: (next: () => void, busy: boolean) => React.ReactNode }) {
  const t = useT()
  const { data } = usePacks()
  const { add } = useAdd()
  const [mode, setMode] = React.useState<'all' | 'choose' | 'none'>('choose')
  const [picked, setPicked] = React.useState<Set<string>>(new Set())
  const [busy, setBusy] = React.useState(false)
  const packs = (data?.packs || []).filter((p) => !p.basics)
  const todo = packs.filter((p) => !p.installed && (mode === 'all' || (mode === 'choose' && picked.has(p.id))))
  const next = async () => {
    setBusy(true)
    try {
      for (const p of todo) await add(p, true)
      if (todo.length) toast.success(t('packs.doneMany', { count: todo.length }))
      onDone()
    } catch {
      /* the error toast is shown by the mutation */
    } finally {
      setBusy(false)
    }
  }
  const toggle = (id: string) => setPicked((s) => {
    const n = new Set(s)
    if (n.has(id)) n.delete(id)
    else n.add(id)
    return n
  })
  return (
    <div className="grid gap-4">
      <Segmented
        value={mode}
        onChange={setMode}
        aria-label={t('packs.title')}
        options={[
          { value: 'all', label: t('packs.all') },
          { value: 'choose', label: t('packs.choose') },
          { value: 'none', label: t('packs.none') },
        ]}
      />
      {mode !== 'none' && (
        <div className="grid gap-3 md:grid-cols-2" data-testid="pack-chooser">
          {packs.map((p) => (
            <label key={p.id} className={cn('block h-full rounded-xl has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring', mode === 'choose' && !p.installed && 'cursor-pointer')}>
              <PackCard
                p={p}
                selected={!p.installed && (mode === 'all' || picked.has(p.id))}
                control={
                  p.installed ? (
                    <Badge variant="success">
                      <Check /> {t('packs.added')}
                    </Badge>
                  ) : mode === 'all' ? (
                    <span className="flex size-4 items-center justify-center rounded-[4px] bg-primary text-primary-foreground">
                      <Check className="size-3" strokeWidth={3} />
                    </span>
                  ) : (
                    <Checkbox checked={picked.has(p.id)} onCheckedChange={() => toggle(p.id)} aria-label={p.title} />
                  )
                }
              />
            </label>
          ))}
        </div>
      )}
      {footer(() => void next(), busy)}
    </div>
  )
}
