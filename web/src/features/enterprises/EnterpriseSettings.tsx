// An enterprise's settings (tab "Settings"): name and emoji, linked projects, top, how the chain works (communication,
// workers, autonomy, trust, escalation, limits), the digest and reports, the envelope, the departments. The fields wait
// for the Save bar (one PATCH); the linked projects apply at once (PUT, a refusal asks before vacating positions).
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Plus, Trash2 } from 'lucide-react'
import { useT, type TKey } from '@/i18n'
import { errorMessage, isApiError } from '@/lib/api'
import { useDeleteEnterprise, usePatchEnterprise, usePutEnterpriseProjects, useWorkspace } from '@/lib/queries'
import type { Enterprise, EnterpriseAutonomy, EnterpriseCommunication, EnterpriseSettings as Settings, EnterpriseWorkers } from '@/lib/types'
import { cn, slugify } from '@/lib/utils'
import { Button, Checkbox, confirm, FormField, Input, Select, Sensitive, Switch, Textarea, toast } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { SectionStack, SettingsCard } from '@/pages/settings/sections/ui'

const OWNER = 'owner'
const INHERIT = '__inherit'

type DeptDraft = { id: string; name: string; usd: string; communication: string; workers: string; autonomy: string; notes: string }
type Draft = {
  name: string
  emoji: string
  top: string
  communication: EnterpriseCommunication
  allow: string
  workers: EnterpriseWorkers
  autonomy: EnterpriseAutonomy
  trust: boolean
  timeout: string
  limits: Record<keyof Settings['limits'], string>
  digest: Settings['digest'] & { hourText: string }
  weekly: boolean
  monthly: boolean
  usd: string
  keys: string
  domains: string
  departments: DeptDraft[]
}

const COMM_DESC: Record<EnterpriseCommunication, TKey> = { strict: 'ent.settings.communication.strict', leads: 'ent.settings.communication.leads', open: 'ent.settings.communication.open' }
const WORKERS_DESC: Record<EnterpriseWorkers, TKey> = { discreet: 'ent.settings.workers.discreet', visible: 'ent.settings.workers.visible', off: 'ent.settings.workers.off' }
const AUTONOMY_DESC: Record<EnterpriseAutonomy, TKey> = { careful: 'ent.settings.autonomy.careful', balanced: 'ent.settings.autonomy.balanced', autonomous: 'ent.settings.autonomy.autonomous' }
const LIMIT_LABEL: Record<keyof Settings['limits'], TKey> = { depth: 'ent.limit.depth', reports: 'ent.limit.reports', workers_live: 'ent.limit.workers_live', hops_per_task: 'ent.limit.hops_per_task' }

const list = (s: string) => [...new Set(s.split(/[\s,]+/).map((x) => x.trim()).filter(Boolean))]
const listOrNull = (s: string) => (list(s).length ? list(s) : null)
const usdOrNull = (s: string) => {
  const n = Number(s.replace(',', '.'))
  return s.trim() === '' || !Number.isFinite(n) || n < 0 ? null : n
}
const int = (s: string, min: number, max: number, fallback: number) => {
  const n = Math.round(Number(s.replace(',', '.')))
  return s.trim() === '' || !Number.isFinite(n) ? fallback : Math.min(max, Math.max(min, n))
}

function draftOf(e: Enterprise): Draft {
  const s = e.settings
  return {
    name: e.name,
    emoji: e.emoji,
    top: e.top,
    communication: s.communication,
    allow: (s.allow || []).map((x) => x.join(', ')).join('\n'),
    workers: s.workers,
    autonomy: s.autonomy,
    trust: s.trust_chain,
    timeout: String(s.escalation_timeout_h),
    limits: { depth: String(s.limits.depth), reports: String(s.limits.reports), workers_live: String(s.limits.workers_live), hops_per_task: String(s.limits.hops_per_task) },
    digest: { ...s.digest, hourText: String(s.digest.hour) },
    weekly: s.weekly,
    monthly: s.monthly,
    usd: e.envelope.usd_per_day == null ? '' : String(e.envelope.usd_per_day),
    keys: (e.envelope.keys || []).join(', '),
    domains: (e.envelope.domains || []).join(', '),
    departments: Object.entries(e.departments).map(([id, d]) => ({
      id,
      name: d.name || id,
      usd: d.envelope?.usd_per_day == null ? '' : String(d.envelope.usd_per_day),
      communication: d.settings?.communication || '',
      workers: d.settings?.workers || '',
      autonomy: d.settings?.autonomy || '',
      notes: d.notes || '',
    })),
  }
}

/** The PATCH body of a draft; what the form does not know (desk, unknown keys) is kept from the server's copy. */
function patchOf(e: Enterprise, d: Draft) {
  const settings: Settings = {
    ...e.settings,
    communication: d.communication,
    allow: d.communication === 'open' ? d.allow.split('\n').map((l) => list(l)).filter((x) => x.length === 2).map((x) => [x[0], x[1]] as [string, string]) : e.settings.allow || [],
    workers: d.workers,
    autonomy: d.autonomy,
    trust_chain: d.trust,
    escalation_timeout_h: int(d.timeout, 1, 72, e.settings.escalation_timeout_h),
    limits: {
      depth: int(d.limits.depth, 1, 6, e.settings.limits.depth),
      reports: int(d.limits.reports, 1, 12, e.settings.limits.reports),
      workers_live: int(d.limits.workers_live, 0, 50, e.settings.limits.workers_live),
      hops_per_task: int(d.limits.hops_per_task, 1, 20, e.settings.limits.hops_per_task),
    },
    digest: { enabled: d.digest.enabled, hour: int(d.digest.hourText, 0, 23, e.settings.digest.hour), per_lead: d.digest.per_lead, titles_only: d.digest.titles_only },
    weekly: d.weekly,
    monthly: d.monthly,
  }
  const departments = Object.fromEntries(
    d.departments.map((x) => {
      const old = e.departments[x.id] || { name: x.name }
      const { communication: _c, workers: _w, autonomy: _a, ...rest } = old.settings || {}
      void _c, void _w, void _a
      const over = { ...rest, ...(x.communication ? { communication: x.communication as EnterpriseCommunication } : {}), ...(x.workers ? { workers: x.workers as EnterpriseWorkers } : {}), ...(x.autonomy ? { autonomy: x.autonomy as EnterpriseAutonomy } : {}) }
      return [x.id, { ...old, name: x.name.trim() || x.id, envelope: { ...old.envelope, usd_per_day: usdOrNull(x.usd) }, settings: over, notes: x.notes }]
    }),
  )
  return {
    name: d.name.trim(),
    emoji: d.emoji.trim(),
    top: d.top,
    settings,
    envelope: { ...e.envelope, usd_per_day: usdOrNull(d.usd), keys: listOrNull(d.keys), domains: listOrNull(d.domains) },
    departments,
  }
}

export function EnterpriseSettings({ enterprise: e }: { enterprise: Enterprise }) {
  const t = useT()
  const navigate = useNavigate()
  const patch = usePatchEnterprise({ errorToast: false })
  const del = useDeleteEnterprise()
  const initial = React.useMemo(() => draftOf(e), [e])
  const [d, setD] = React.useState<Draft>(initial)
  const dirty = JSON.stringify(d) !== JSON.stringify(initial)
  // the server's copy (another tab, the command line) replaces the form while nothing is being edited
  const dirtyRef = React.useRef(dirty)
  dirtyRef.current = dirty
  React.useEffect(() => {
    if (!dirtyRef.current) setD(initial)
  }, [initial])
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }))
  const setLimit = (k: keyof Settings['limits'], v: string) => setD((x) => ({ ...x, limits: { ...x.limits, [k]: v } }))
  const setDigest = (v: Partial<Draft['digest']>) => setD((x) => ({ ...x, digest: { ...x.digest, ...v } }))
  const setDept = (id: string, v: Partial<DeptDraft>) => setD((x) => ({ ...x, departments: x.departments.map((y) => (y.id === id ? { ...y, ...v } : y)) }))
  const roots = e.positions.filter((p) => !p.reports_to)
  const [newDept, setNewDept] = React.useState('')

  const save = () => patch.mutate({ id: e.id, ...patchOf(e, d) }, { onSuccess: () => toast.success(t('ent.settings.saved')) })
  const remove = async () => {
    const ok = await confirm({ title: t('ent.delete.title', { name: e.name }), description: t('ent.delete.desc'), confirmText: t('ent.delete.action'), destructive: true })
    if (ok) del.mutate({ id: e.id }, { onSuccess: () => navigate('/enterprises') })
  }
  const addDept = () => {
    const id = slugify(newDept)
    if (!id || d.departments.some((x) => x.id === id)) return
    setD((x) => ({ ...x, departments: [...x.departments, { id, name: newDept.trim(), usd: '', communication: '', workers: '', autonomy: '', notes: '' }] }))
    setNewDept('')
  }
  const err = patch.error ? errorMessage(patch.error) : undefined
  const sel = <T extends string>(value: string, on: (v: T) => void, items: [string, TKey][], extra?: { value: string; label: string }) => (
    <Select value={value || INHERIT} onValueChange={(v) => on((v === INHERIT ? '' : v) as T)} options={[...(extra ? [extra] : []), ...items.map(([v, k]) => ({ value: v, label: t(k) }))]} className="w-56 max-w-full" />
  )

  return (
    <div className="grid gap-6" data-testid="enterprise-settings">
      <SectionStack>
        <SettingsCard title={t('ent.settings.general')} description={t('ent.settings.generalDesc')}>
          <div className="grid gap-4">
            <div className="grid grid-cols-[minmax(0,1fr)_5rem] gap-3">
              <FormField label={t('ent.new.name')}>
                <Input value={d.name} onChange={(ev) => set('name', ev.target.value)} maxLength={60} autoComplete="off" />
              </FormField>
              <FormField label={t('ent.new.emoji')}>
                <Input value={d.emoji} onChange={(ev) => set('emoji', ev.target.value)} maxLength={4} className="text-center" autoComplete="off" />
              </FormField>
            </div>
            <FormField label={t('ent.settings.top')} hint={t('ent.settings.topHint')}>
              <Select value={d.top} onValueChange={(v) => set('top', v)} options={[{ value: OWNER, label: t('ent.settings.topOwner') }, ...roots.map((p) => ({ value: p.id, label: p.title }))]} className="w-72 max-w-full" />
            </FormField>
          </div>
        </SettingsCard>

        <ProjectsCard enterprise={e} />

        <SettingsCard title={t('ent.settings.chain')} description={t('ent.settings.chainDesc')}>
          <div className="divide-y">
            <SettingRow label={t('ent.settings.communication')} description={t(COMM_DESC[d.communication])}>
              {sel<EnterpriseCommunication>(d.communication, (v) => set('communication', v), [['strict', 'ent.opt.strict'], ['leads', 'ent.opt.leads'], ['open', 'ent.opt.open']])}
            </SettingRow>
            {d.communication === 'open' && (
              <div className="py-4">
                <FormField label={t('ent.settings.allow')} hint={t('ent.settings.allowHint')}>
                  <Textarea value={d.allow} onChange={(ev) => set('allow', ev.target.value)} minRows={2} maxRows={8} placeholder="writer, designer" />
                </FormField>
              </div>
            )}
            <SettingRow label={t('ent.settings.workers')} description={t(WORKERS_DESC[d.workers])}>
              {sel<EnterpriseWorkers>(d.workers, (v) => set('workers', v), [['discreet', 'ent.opt.discreet'], ['visible', 'ent.opt.visible'], ['off', 'ent.opt.off']])}
            </SettingRow>
            <SettingRow label={t('ent.settings.autonomy')} description={t(AUTONOMY_DESC[d.autonomy])}>
              {sel<EnterpriseAutonomy>(d.autonomy, (v) => set('autonomy', v), [['careful', 'ent.opt.careful'], ['balanced', 'ent.opt.balanced'], ['autonomous', 'ent.opt.autonomous']])}
            </SettingRow>
            <SettingRow label={t('ent.settings.trust')} description={t('ent.settings.trustDesc')} htmlFor="ent-trust">
              <Switch id="ent-trust" checked={d.trust} onCheckedChange={(v) => set('trust', v)} />
            </SettingRow>
            <SettingRow label={t('ent.settings.timeout')} description={t('ent.settings.timeoutDesc')} htmlFor="ent-timeout">
              <Input id="ent-timeout" inputMode="numeric" value={d.timeout} onChange={(ev) => set('timeout', ev.target.value)} className="w-24" />
            </SettingRow>
          </div>
        </SettingsCard>

        <SettingsCard title={t('ent.settings.limits')} description={t('ent.settings.limitsDesc')}>
          <div className="grid gap-3 sm:grid-cols-2">
            {(Object.keys(LIMIT_LABEL) as (keyof Settings['limits'])[]).map((k) => (
              <FormField key={k} label={t(LIMIT_LABEL[k])}>
                <Input inputMode="numeric" value={d.limits[k]} onChange={(ev) => setLimit(k, ev.target.value)} />
              </FormField>
            ))}
          </div>
        </SettingsCard>

        <SettingsCard title={t('ent.settings.digest')} description={t('ent.settings.digestDesc')}>
          <div className="divide-y">
            <SettingRow label={t('ent.settings.digestOn')} htmlFor="ent-digest">
              <Switch id="ent-digest" checked={d.digest.enabled} onCheckedChange={(v) => setDigest({ enabled: v })} />
            </SettingRow>
            {d.digest.enabled && (
              <>
                <SettingRow label={t('ent.settings.digestHour')} description={t('ent.settings.digestHourDesc')} htmlFor="ent-digest-hour">
                  <Input id="ent-digest-hour" inputMode="numeric" value={d.digest.hourText} onChange={(ev) => setDigest({ hourText: ev.target.value })} className="w-24" />
                </SettingRow>
                <SettingRow label={t('ent.settings.digestLead')} description={t('ent.settings.digestLeadDesc')} htmlFor="ent-digest-lead">
                  <Switch id="ent-digest-lead" checked={d.digest.per_lead} onCheckedChange={(v) => setDigest({ per_lead: v })} />
                </SettingRow>
                <SettingRow label={t('ent.settings.digestTitles')} description={t('ent.settings.digestTitlesDesc')} htmlFor="ent-digest-titles">
                  <Switch id="ent-digest-titles" checked={d.digest.titles_only} onCheckedChange={(v) => setDigest({ titles_only: v })} />
                </SettingRow>
              </>
            )}
            <SettingRow label={t('ent.settings.weekly')} description={t('ent.settings.weeklyDesc')} htmlFor="ent-weekly">
              <Switch id="ent-weekly" checked={d.weekly} onCheckedChange={(v) => set('weekly', v)} />
            </SettingRow>
            <SettingRow label={t('ent.settings.monthly')} description={t('ent.settings.monthlyDesc')} htmlFor="ent-monthly">
              <Switch id="ent-monthly" checked={d.monthly} onCheckedChange={(v) => set('monthly', v)} />
            </SettingRow>
          </div>
        </SettingsCard>

        <SettingsCard title={t('ent.settings.envelope')} description={t('ent.settings.envelopeDesc')}>
          <div className="grid gap-4">
            <FormField label={t('ent.settings.usd')} hint={t('ent.settings.usdHint')}>
              <Input inputMode="decimal" value={d.usd} onChange={(ev) => set('usd', ev.target.value)} className="w-40" placeholder={t('ent.settings.noLimit')} />
            </FormField>
            <FormField label={t('ent.settings.keys')} hint={t('ent.settings.keysHint')}>
              <Input value={d.keys} onChange={(ev) => set('keys', ev.target.value)} placeholder={t('ent.settings.noLimit')} autoComplete="off" />
            </FormField>
            <FormField label={t('ent.settings.domains')} hint={t('ent.settings.domainsHint')}>
              <Input value={d.domains} onChange={(ev) => set('domains', ev.target.value)} placeholder="*.example.com" autoComplete="off" />
            </FormField>
          </div>
        </SettingsCard>

        <SettingsCard title={t('ent.settings.departments')} description={t('ent.settings.departmentsDesc')}>
          <div className="grid gap-4">
            {d.departments.length === 0 && <p className="text-[13px] text-muted-foreground">{t('ent.settings.departmentsNone')}</p>}
            {d.departments.map((x) => (
              <div key={x.id} className="grid gap-3 rounded-lg border p-3" data-testid="department">
                <div className="flex items-end gap-2">
                  <FormField label={t('ent.settings.deptName')} className="flex-1">
                    <Input value={x.name} onChange={(ev) => setDept(x.id, { name: ev.target.value })} maxLength={60} autoComplete="off" />
                  </FormField>
                  <Button variant="ghost" size="icon" aria-label={t('ent.settings.deptRemove', { name: x.name })} onClick={() => set('departments', d.departments.filter((y) => y.id !== x.id))}>
                    <Trash2 />
                  </Button>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <FormField label={t('ent.settings.usd')}>
                    <Input inputMode="decimal" value={x.usd} onChange={(ev) => setDept(x.id, { usd: ev.target.value })} placeholder={t('ent.settings.noLimit')} />
                  </FormField>
                  <FormField label={t('ent.settings.communication')}>
                    {sel<string>(x.communication, (v) => setDept(x.id, { communication: v }), [['strict', 'ent.opt.strict'], ['leads', 'ent.opt.leads'], ['open', 'ent.opt.open']], { value: INHERIT, label: t('ent.settings.inherit') })}
                  </FormField>
                  <FormField label={t('ent.settings.workers')}>
                    {sel<string>(x.workers, (v) => setDept(x.id, { workers: v }), [['discreet', 'ent.opt.discreet'], ['visible', 'ent.opt.visible'], ['off', 'ent.opt.off']], { value: INHERIT, label: t('ent.settings.inherit') })}
                  </FormField>
                  <FormField label={t('ent.settings.autonomy')}>
                    {sel<string>(x.autonomy, (v) => setDept(x.id, { autonomy: v }), [['careful', 'ent.opt.careful'], ['balanced', 'ent.opt.balanced'], ['autonomous', 'ent.opt.autonomous']], { value: INHERIT, label: t('ent.settings.inherit') })}
                  </FormField>
                </div>
                <FormField label={t('ent.settings.deptNotes')} hint={t('ent.settings.deptNotesHint')}>
                  <Textarea value={x.notes} onChange={(ev) => setDept(x.id, { notes: ev.target.value })} minRows={2} maxRows={8} />
                </FormField>
              </div>
            ))}
            <div className="flex items-end gap-2">
              <FormField label={t('ent.settings.deptAdd')} className="flex-1">
                <Input
                  value={newDept}
                  onChange={(ev) => setNewDept(ev.target.value)}
                  onKeyDown={(ev) => {
                    if (ev.key === 'Enter') {
                      ev.preventDefault()
                      addDept()
                    }
                  }}
                  maxLength={60}
                  placeholder={t('ent.settings.deptPh')}
                  autoComplete="off"
                />
              </FormField>
              <Button variant="outline" onClick={addDept} disabled={!slugify(newDept)}>
                <Plus /> {t('common.add')}
              </Button>
            </div>
          </div>
        </SettingsCard>

        <SettingsCard title={t('ent.settings.danger')} danger>
          <SettingRow label={t('ent.delete.action')} description={t('ent.delete.desc')}>
            <Button variant="destructive" onClick={remove} loading={del.isPending} data-testid="enterprise-delete">
              <Trash2 /> {t('ent.delete.action')}
            </Button>
          </SettingRow>
        </SettingsCard>
      </SectionStack>

      <div className={cn('sticky bottom-0 z-10 -mx-4 flex flex-wrap items-center justify-end gap-3 border-t bg-background/95 px-4 py-3 md:-mx-6 md:px-6', !dirty && !err && 'hidden')} data-testid="settings-bar">
        {err && (
          <p role="alert" className="mr-auto text-[13px] text-destructive">
            {err}
          </p>
        )}
        <Button variant="outline" onClick={() => setD(initial)} disabled={!dirty}>
          {t('common.cancel')}
        </Button>
        <Button onClick={save} loading={patch.isPending} disabled={!dirty || !d.name.trim()} data-testid="settings-save">
          {t('common.save')}
        </Button>
      </div>
    </div>
  )
}

/** The linked projects: ticking one applies at once. Unlinking a project whose agents hold positions asks first. */
function ProjectsCard({ enterprise: e }: { enterprise: Enterprise }) {
  const t = useT()
  const { data: ws } = useWorkspace()
  const put = usePutEnterpriseProjects()
  const apply = async (projects: string[]) => {
    try {
      await put.mutateAsync({ id: e.id, projects })
    } catch (err) {
      if (isApiError(err, 'occupied')) {
        const ok = await confirm({ title: t('ent.projects.vacateTitle'), description: t('ent.projects.vacateDesc', { detail: err.message }), confirmText: t('ent.projects.vacate'), destructive: true })
        if (ok) await put.mutateAsync({ id: e.id, projects, vacate: true }).catch((x) => toast.error(errorMessage(x)))
      } else toast.error(errorMessage(err))
    }
  }
  const known = new Set((ws?.projects || []).map((p) => p.name))
  return (
    <SettingsCard title={t('ent.settings.projects')} description={t('ent.settings.projectsDesc')}>
      <div className="grid gap-1" data-testid="enterprise-projects">
        {(ws?.projects || []).length === 0 && <p className="text-[13px] text-muted-foreground">{t('ent.new.noProjects')}</p>}
        {[...(ws?.projects || []).map((p) => p.name), ...e.projects.filter((p) => !known.has(p))].map((name) => (
          <label key={name} className="flex min-h-9 items-center gap-2.5 rounded-md px-2 text-sm hover:bg-accent">
            <Checkbox checked={e.projects.includes(name)} disabled={put.isPending} onCheckedChange={(v) => void apply(v ? [...e.projects, name] : e.projects.filter((x) => x !== name))} />
            <Sensitive length={8}>{name}</Sensitive>
          </label>
        ))}
      </div>
    </SettingsCard>
  )
}
