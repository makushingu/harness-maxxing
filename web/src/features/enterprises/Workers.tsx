// The temporary workers of a position (its helpers: live ones can be stopped) and the template they are made from, and the
// position's "Front desk" switch. Parts of the position panel's "Position" tab.
import * as React from 'react'
import { Square, Trash2 } from 'lucide-react'
import { useLang, useT, type TKey } from '@/i18n'
import { errorMessage } from '@/lib/api'
import { useEnterpriseWorkers, useStopWorker } from '@/lib/queries'
import { fmtDate, fmtRelative } from '@/lib/format'
import type { Enterprise, Position } from '@/lib/types'
import { Badge, Button, confirm, FormField, Input, Sensitive, Skeleton, Switch, Textarea, toast } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { ModelSelect } from '@/features/agents/parts'
import { useSavePosition } from './parts'

const STATUS_LABEL: Record<string, TKey> = {
  live: 'ent.worker.live',
  done: 'ent.worker.done',
  stopped: 'ent.worker.stopped',
  expired: 'ent.worker.expired',
}

/** "Front desk": this position is the one visitors talk to (the desk tab appears, the desk settings apply). */
export function DeskSwitch({ enterprise: e, position: p }: { enterprise: Enterprise; position: Position }) {
  const t = useT()
  const { save, pending } = useSavePosition(e)
  return (
    <SettingRow label={t('ent.position.desk')} description={t('ent.position.deskDesc')} htmlFor="ent-position-desk">
      <Switch id="ent-position-desk" checked={!!p.desk} disabled={pending} onCheckedChange={(v) => save(p.id, { desk: v })} data-testid="position-desk" />
    </SettingRow>
  )
}

/** What a worker of this position is made from: its role, model and daily budget. No role = the position has no template. */
export function WorkerTemplateEditor({ enterprise: e, position: p }: { enterprise: Enterprise; position: Position }) {
  const t = useT()
  const { save, pending } = useSavePosition(e)
  const w = p.worker_template
  const [role, setRole] = React.useState(w?.role || '')
  const [model, setModel] = React.useState(w?.model || '')
  const [usd, setUsd] = React.useState(w ? String(w.usd_per_day) : '')
  const n = Number(usd.replace(',', '.'))
  const budget = usd.trim() === '' ? 0 : Number.isFinite(n) && n >= 0 ? n : NaN
  const dirty = role !== (w?.role || '') || model !== (w?.model || '') || usd !== (w ? String(w.usd_per_day) : '')
  const done = () => toast.success(t('ent.settings.saved'))
  return (
    <section className="grid gap-3" aria-label={t('ent.worker.template')} data-testid="worker-template">
      <div className="grid gap-1">
        <h4 className="text-sm font-medium">{t('ent.worker.template')}</h4>
        <p className="text-[13px] text-muted-foreground">{t('ent.worker.templateDesc')}</p>
      </div>
      <FormField label={t('ent.worker.role')}>
        <Textarea value={role} onChange={(ev) => setRole(ev.target.value)} minRows={3} maxRows={10} maxLength={4000} />
      </FormField>
      <FormField label={t('ent.worker.model')}>
        <ModelSelect value={model} onChange={setModel} />
      </FormField>
      <FormField label={t('ent.worker.usd')} hint={t('ent.worker.usdHint')}>
        <Input inputMode="decimal" value={usd} onChange={(ev) => setUsd(ev.target.value)} className="w-32" placeholder="1" aria-invalid={Number.isNaN(budget)} />
      </FormField>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={!dirty || !role.trim() || Number.isNaN(budget)} loading={pending} onClick={() => save(p.id, { worker_template: { role: role.trim(), model, usd_per_day: budget } }, { onDone: done })} data-testid="worker-template-save">
          {t('common.save')}
        </Button>
        {w && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              save(p.id, { worker_template: null }, { onDone: () => (setRole(''), setModel(''), setUsd('')) })
            }}
          >
            <Trash2 /> {t('ent.worker.removeTemplate')}
          </Button>
        )}
      </div>
    </section>
  )
}

/** The position's workers, live first; a live one can be stopped (it is removed). */
export function PositionWorkers({ enterprise: e, position: p }: { enterprise: Enterprise; position: Position }) {
  const t = useT()
  const lang = useLang()
  const { data, isLoading } = useEnterpriseWorkers(e.id)
  const stop = useStopWorker()
  const items = (data || []).filter((x) => x.position === p.id)
  const ask = async (wid: string) => {
    const ok = await confirm({ title: t('ent.worker.stopTitle'), description: t('ent.worker.stopDesc'), confirmText: t('ent.worker.stop'), destructive: true })
    if (ok) stop.mutate({ id: e.id, wid }, { onError: (err) => toast.error(errorMessage(err)) })
  }
  return (
    <section className="grid gap-2" aria-label={t('ent.worker.title')} data-testid="position-workers">
      <div className="flex items-center gap-2">
        <h4 className="text-sm font-medium">{t('ent.worker.title')}</h4>
        <Badge variant="muted">{items.filter((x) => x.status === 'live').length}</Badge>
      </div>
      {isLoading ? (
        <Skeleton className="h-10" />
      ) : items.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t('ent.worker.none')}</p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {items.slice(0, 12).map((x) => (
            <li key={x.id} className="flex items-start justify-between gap-3 px-3 py-2 text-[13px]">
              <span className="grid min-w-0 gap-0.5">
                <span className="line-clamp-2">
                  <Sensitive length={20}>{x.text || x.id}</Sensitive>
                </span>
                <span className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                  <Badge variant={x.status === 'live' ? 'success' : 'muted'}>{t(STATUS_LABEL[x.status] || 'ent.worker.done')}</Badge>
                  <span>{x.status === 'live' ? t('ent.worker.expires', { when: fmtRelative(x.expires, lang) }) : fmtDate(x.ended || x.created, lang)}</span>
                </span>
              </span>
              {x.status === 'live' && (
                <Button size="sm" variant="outline" onClick={() => void ask(x.id)} loading={stop.isPending && stop.variables?.wid === x.id} aria-label={t('ent.worker.stop')} data-testid="worker-stop">
                  <Square /> {t('ent.worker.stop')}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
