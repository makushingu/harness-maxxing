// The "Front desk" section of an enterprise's settings: whether the desk is live, its label, how long conversations are
// kept, and the public link (anyone holding it can write to the desk). One Save for the fields;
// the link is made or replaced at once.
import * as React from 'react'
import { Link } from 'react-router'
import { KeyRound, RefreshCw } from 'lucide-react'
import { useT } from '@/i18n'
import { errorMessage } from '@/lib/api'
import { agentRoute, useDeskLink, useSaveDeskSettings } from '@/lib/queries'
import type { DeskSettingsPatch, Enterprise } from '@/lib/types'
import { Button, confirm, CopyButton, FormField, Input, Sensitive, Switch, toast } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { SettingsCard } from '@/pages/settings/sections/ui'

type Draft = { enabled: boolean; label: string; retention: string; publicOn: boolean; rate: string; max: string }

function draftOf(e: Enterprise): Draft {
  const d = e.settings.desk
  return {
    enabled: !!d?.enabled,
    label: d?.label || '',
    retention: String(d?.retention_days ?? 30),
    publicOn: !!d?.public?.enabled,
    rate: String(d?.public?.rate_per_hour ?? 20),
    max: String(d?.public?.max_chars ?? 1000),
  }
}
const int = (s: string, min: number, max: number, fallback: number) => {
  const n = Math.round(Number(s))
  return s.trim() === '' || !Number.isFinite(n) ? fallback : Math.min(max, Math.max(min, n))
}
const agentOf = (path: string) => {
  const m = /^projects\/([^/]+)\/topics\/([^/]+)\/agents\/([^/]+)$/.exec(path)
  return { project: m?.[1] || '', topic: m?.[2] || '', name: m?.[3] || '' }
}

export function DeskSettings({ enterprise: e }: { enterprise: Enterprise }) {
  const t = useT()
  const save = useSaveDeskSettings()
  const link = useDeskLink()
  const initial = React.useMemo(() => draftOf(e), [e])
  const [d, setD] = React.useState<Draft>(initial)
  const dirty = JSON.stringify(d) !== JSON.stringify(initial)
  const dirtyRef = React.useRef(dirty)
  dirtyRef.current = dirty
  React.useEffect(() => {
    if (!dirtyRef.current) setD(initial)
  }, [initial])
  const set = (v: Partial<Draft>) => setD((x) => ({ ...x, ...v }))
  const token = e.settings.desk?.public?.token || ''
  const url = token ? `${window.location.origin}/desk/${token}` : ''
  // the occupants that are not Protected (sandboxed): the desk cannot be live while one exists
  const unprotected = e.positions.filter((p) => p.occupant && !p.occupant.sandbox)

  const patch: DeskSettingsPatch = {
    enabled: d.enabled,
    label: d.label.trim(),
    retention_days: int(d.retention, 1, 365, 30),
    public: { enabled: d.publicOn, rate_per_hour: int(d.rate, 1, 600, 20), max_chars: int(d.max, 50, 4000, 1000) },
  }
  const submit = () => save.mutate({ id: e.id, desk: patch }, { onSuccess: () => toast.success(t('ent.settings.saved')) })
  const makeLink = async (regenerate: boolean) => {
    if (regenerate) {
      const ok = await confirm({ title: t('ent.deskSettings.regenTitle'), description: t('ent.deskSettings.regenDesc'), confirmText: t('ent.deskSettings.regen'), destructive: true })
      if (!ok) return
    }
    link.mutate({ id: e.id, regenerate }, { onError: (err) => toast.error(errorMessage(err)) })
  }

  return (
    <SettingsCard
      title={t('ent.deskSettings.title')}
      description={t('ent.deskSettings.desc')}
      actions={
        <Button size="sm" onClick={submit} disabled={!dirty} loading={save.isPending} data-testid="desk-save">
          {t('common.save')}
        </Button>
      }
    >
      <div className="grid gap-4" data-testid="desk-settings">
        <div className="divide-y">
          <SettingRow label={t('ent.deskSettings.enabled')} description={t('ent.deskSettings.enabledDesc')} htmlFor="ent-desk-on">
            <Switch id="ent-desk-on" checked={d.enabled} onCheckedChange={(v) => set({ enabled: v })} />
          </SettingRow>
        </div>
        {d.enabled && unprotected.length > 0 && (
          <div role="status" className="grid gap-2 rounded-lg border border-warning/30 bg-warning/10 p-3 text-[13px]" data-testid="desk-unprotected">
            <p className="font-medium">{t('ent.deskSettings.unprotected')}</p>
            <p className="text-muted-foreground">{t('ent.deskSettings.unprotectedHint')}</p>
            <ul className="grid gap-1">
              {unprotected.map((p) => (
                <li key={p.id} className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">
                    <Sensitive length={10}>{p.title}</Sensitive>
                  </span>
                  <Button asChild size="sm" variant="outline">
                    <Link to={agentRoute(agentOf(p.agent || ''))}>{t('ent.deskSettings.openAgent')}</Link>
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {save.error && (
          <p role="alert" className="text-[13px] text-destructive" data-testid="desk-error">
            {errorMessage(save.error)}
          </p>
        )}
        <FormField label={t('ent.deskSettings.label')} hint={t('ent.deskSettings.labelHint')}>
          <Input value={d.label} onChange={(ev) => set({ label: ev.target.value })} maxLength={60} autoComplete="off" />
        </FormField>
        <FormField label={t('ent.deskSettings.retention')} hint={t('ent.deskSettings.retentionHint')}>
          <Input inputMode="numeric" value={d.retention} onChange={(ev) => set({ retention: ev.target.value })} className="w-28" />
        </FormField>

        <div className="grid gap-3 border-t pt-4">
          <SettingRow label={t('ent.deskSettings.public')} description={t('ent.deskSettings.publicDesc')} htmlFor="ent-desk-public" className="py-0">
            <Switch id="ent-desk-public" checked={d.publicOn} onCheckedChange={(v) => set({ publicOn: v })} />
          </SettingRow>
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField label={t('ent.deskSettings.rate')} hint={t('ent.deskSettings.rateHint')}>
              <Input inputMode="numeric" value={d.rate} onChange={(ev) => set({ rate: ev.target.value })} className="w-28" />
            </FormField>
            <FormField label={t('ent.deskSettings.maxChars')} hint={t('ent.deskSettings.maxCharsHint')}>
              <Input inputMode="numeric" value={d.max} onChange={(ev) => set({ max: ev.target.value })} className="w-28" />
            </FormField>
          </div>
          {url && (
            <FormField label={t('ent.deskSettings.link')}>
              <div className="flex items-center gap-1">
                <Input readOnly value={url} onFocus={(ev) => ev.target.select()} className="font-mono text-xs" data-testid="desk-link" />
                <CopyButton text={url} label={t('ent.deskSettings.copy')} />
              </div>
            </FormField>
          )}
          <p role="note" className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-[13px]" data-testid="desk-link-warning">
            {t('ent.deskSettings.warning')}
          </p>
          <div className="flex flex-wrap gap-2">
            {token ? (
              <Button size="sm" variant="outline" onClick={() => void makeLink(true)} loading={link.isPending} data-testid="desk-link-regen">
                <RefreshCw /> {t('ent.deskSettings.regen')}
              </Button>
            ) : (
              <Button size="sm" variant="outline" onClick={() => void makeLink(false)} loading={link.isPending} data-testid="desk-link-create">
                <KeyRound /> {t('ent.deskSettings.create')}
              </Button>
            )}
          </div>
          {link.error && (
            <p role="alert" className="text-[13px] text-destructive">
              {errorMessage(link.error)}
            </p>
          )}
        </div>
      </div>
    </SettingsCard>
  )
}
