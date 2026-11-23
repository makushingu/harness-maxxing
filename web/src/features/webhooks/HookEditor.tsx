// The small form of Settings -> Webhooks / Events (new or change), like the cron editor. It covers the common case:
// a source (or a Harness event) and one action. What it does not show (filters, headers, stored fields, queue, size)
// is kept as it is on a change; Harness sets those from a session (`maxxing webhooks`, docs 37 / 38).
import * as React from 'react'
import { useT, type TKey } from '@/i18n'
import { isApiError } from '@/lib/api'
import { useAgents, useCrons, useSaveWebhook } from '@/lib/queries'
import type { Webhook, WebhookAction, WebhookSource } from '@/lib/types'
import {
  Button,
  CopyButton,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  Label,
  SecretInput,
  Segmented,
  Select,
  Sensitive,
  Switch,
  useMask,
  usePresentation,
} from '@/components/ui'
import { Combobox } from '@/components/ui/combobox'
import { Callout } from '@/features/common'

type Kind = 'in' | 'event'
export type HookSeed = { mode: 'new'; kind: Kind } | { mode: 'edit'; kind: Kind; hook: Webhook }

type ActionKind = WebhookAction['kind']
type On = 'feed' | 'agent' | 'cron'
type When = 'any' | 'ok' | 'fail'
type Report = Webhook['report']
type Form = {
  name: string
  description: string
  source: WebhookSource
  secret: string
  wait: boolean
  on: On
  feedSource: string
  contains: string
  target: string
  when: When
  action: ActionKind
  command: string
  url: string
  method: string
  title: string
  body: string
  level: string
  report: Report
}
type Field = 'name' | 'command' | 'url' | 'form'

const SOURCES: WebhookSource[] = ['stripe', 'shopify', 'github', 'generic', 'phone']
const SIGNED: WebhookSource[] = ['stripe', 'shopify', 'github']
const ANY = '__any'

function initial(seed: HookSeed): Form {
  const f: Form = {
    name: '',
    description: '',
    source: 'generic',
    secret: '',
    wait: false,
    on: 'feed',
    feedSource: '',
    contains: '',
    target: ANY,
    when: 'any',
    action: seed.kind === 'in' ? 'shell' : 'notify',
    command: '',
    url: '',
    method: 'POST',
    title: '',
    body: '',
    level: 'info',
    report: 'fail',
  }
  if (seed.mode === 'new') return f
  const h = seed.hook
  const tr = h.trigger
  const a = h.action
  f.name = h.name
  f.description = h.description
  f.report = h.report
  if (tr.kind === 'in') {
    f.source = tr.source
    f.wait = tr.reply === 'wait'
  } else if (tr.on === 'feed') {
    f.on = 'feed'
    f.feedSource = tr.source || ''
    f.contains = tr.contains || ''
  } else {
    f.on = tr.on
    f.target = (tr.on === 'agent' ? tr.agent : tr.cron) || ANY
    f.when = tr.when
  }
  f.action = a.kind
  if (a.kind === 'shell') f.command = a.command
  if (a.kind === 'call') {
    f.url = a.url
    f.method = a.method
  }
  if (a.kind === 'notify') {
    f.title = a.title || ''
    f.body = a.body || ''
    f.level = a.level || 'info'
  }
  return f
}

/** The trigger and the action to send: the form's fields over the hook's own (kept: filters, headers, fields...). */
function build(seed: HookSeed, f: Form): { trigger: object; action: object } {
  const old = seed.mode === 'edit' ? seed.hook : null
  let trigger: object
  if (seed.kind === 'in') {
    const was = old?.trigger.kind === 'in' && old.trigger.source === f.source ? old.trigger : null
    const methods = f.source === 'phone' || f.source === 'generic' ? (was?.methods ?? (f.source === 'phone' ? ['GET', 'POST'] : ['POST'])) : ['POST']
    trigger = { ...(was ?? {}), kind: 'in', source: f.source, methods, reply: f.wait ? 'wait' : 'now' }
  } else if (f.on === 'feed') {
    const was = old?.trigger.kind === 'event' && old.trigger.on === 'feed' ? old.trigger : null
    trigger = { ...(was ?? {}), kind: 'event', on: 'feed', source: f.feedSource.trim(), contains: f.contains.trim() }
  } else {
    const target = f.target === ANY ? '' : f.target
    trigger = { kind: 'event', on: f.on, [f.on]: target, when: f.when }
  }
  const same = old?.action.kind === f.action ? old.action : null
  let action: object
  if (f.action === 'shell') action = { ...(same ?? {}), kind: 'shell', command: f.command.trim() }
  else if (f.action === 'call') action = { ...(same ?? {}), kind: 'call', url: f.url.trim(), method: f.method }
  else if (f.action === 'notify') action = { ...(same ?? {}), kind: 'notify', title: f.title, body: f.body, level: f.level }
  else action = { ...(same ?? {}), kind: 'store' }
  return { trigger, action }
}

export function HookEditor({ seed, onOpenChange }: { seed: HookSeed | null; onOpenChange: (o: boolean) => void }) {
  const t = useT()
  const [made, setMade] = React.useState<Webhook | null>(null)
  React.useEffect(() => {
    if (!seed) setMade(null)
  }, [seed])
  const kind = seed?.kind ?? 'in'
  return (
    <Dialog open={!!seed} onOpenChange={onOpenChange}>
      <DialogContent className="md:max-w-2xl" data-testid="hook-editor">
        {seed && made ? (
          <Ready hook={made} onClose={() => onOpenChange(false)} />
        ) : (
          seed && (
            <>
              <DialogHeader>
                <DialogTitle>{t(seed.mode === 'edit' ? (kind === 'in' ? 'webhooks.form.editTitle' : 'webhooks.form.editTitleEvent') : kind === 'in' ? 'webhooks.form.newTitle' : 'webhooks.form.newTitleEvent')}</DialogTitle>
                <DialogDescription>{t(kind === 'in' ? 'webhooks.form.desc' : 'webhooks.form.descEvent')}</DialogDescription>
              </DialogHeader>
              <EditorForm
                key={seed.mode === 'new' ? `new:${kind}` : `edit:${seed.hook.id}`}
                seed={seed}
                onCancel={() => onOpenChange(false)}
                onSaved={(h) => (seed.mode === 'new' && h.trigger.kind === 'in' ? setMade(h) : onOpenChange(false))}
              />
            </>
          )
        )}
      </DialogContent>
    </Dialog>
  )
}

/** After creating an incoming webhook: its URL, and where to paste it. */
function Ready({ hook, onClose }: { hook: Webhook; onClose: () => void }) {
  const t = useT()
  const src = hook.trigger.kind === 'in' ? hook.trigger.source : 'generic'
  return (
    <>
      <DialogHeader>
        <DialogTitle>{t('webhooks.form.ready')}</DialogTitle>
        <DialogDescription>{t(`webhooks.form.where.${src}` as TKey)}</DialogDescription>
      </DialogHeader>
      <div className="flex min-w-0 items-center gap-2 rounded-md border bg-background py-1 pr-1 pl-3 font-mono text-[13px]">
        <span className="min-w-0 flex-1 break-all select-all" data-testid="hook-url">
          <Sensitive length={24}>{hook.url}</Sensitive>
        </span>
        <CopyButton text={hook.url} label={t('webhooks.copyUrl')} />
      </div>
      {hook.needs_secret && <Callout tone="warning">{t('webhooks.needsSecretDesc')}</Callout>}
      <DialogFooter>
        <Button onClick={onClose}>{t('common.done')}</Button>
      </DialogFooter>
    </>
  )
}

function EditorForm({ seed, onCancel, onSaved }: { seed: HookSeed; onCancel: () => void; onSaved: (h: Webhook) => void }) {
  const t = useT()
  const mask = useMask()
  const presentation = usePresentation()
  const [f, setF] = React.useState<Form>(() => initial(seed))
  const [errors, setErrors] = React.useState<Partial<Record<Field, string>>>({})
  const save = useSaveWebhook()
  const isIn = seed.kind === 'in'
  const agents = useAgents(!isIn && f.on === 'agent')
  const crons = useCrons()
  const set = <K extends keyof Form>(k: K, v: Form[K]) => {
    setF((cur) => ({ ...cur, [k]: v }))
    if (Object.keys(errors).length) setErrors({})
  }

  const targets = React.useMemo(() => {
    const any = { value: ANY, label: t(f.on === 'agent' ? 'webhooks.form.anyAgent' : 'webhooks.form.anyCron') }
    if (f.on === 'agent') return [any, ...(agents.data?.agents ?? []).map((a) => ({ value: a.path, label: mask(a.display_name || a.name, 6), hint: mask(a.path.split('/')[1] || '', 6) }))]
    return [any, ...(crons.data?.jobs ?? []).map((j) => ({ value: j.id, label: mask(j.name, 6) }))]
  }, [f.on, agents.data, crons.data, t, mask])

  const actions: ActionKind[] = isIn ? ['shell', 'call', 'store', 'notify'] : ['notify', 'call', 'shell', 'store']

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const errs: Partial<Record<Field, string>> = {}
    if (!f.name.trim()) errs.name = t('webhooks.form.nameRequired')
    if (f.action === 'shell' && !f.command.trim()) errs.command = t('webhooks.form.commandRequired')
    if (f.action === 'call' && !/^(https?:\/\/|\{\{key:)/.test(f.url.trim())) errs.url = t('webhooks.form.urlRequired')
    if (Object.keys(errs).length) return setErrors(errs)
    const { trigger, action } = build(seed, f)
    const body = {
      ...(seed.mode === 'edit' ? { id: seed.hook.id } : {}),
      name: f.name.trim(),
      description: f.description.trim(),
      trigger,
      action,
      report: f.report,
      ...(seed.mode === 'new' && isIn && f.secret.trim() ? { secret: f.secret.trim() } : {}),
    }
    save.mutate(body, {
      onSuccess: onSaved,
      onError: (err) => setErrors({ form: isApiError(err) ? err.message : String(err) }),
    })
  }

  return (
    <form className="grid gap-5" onSubmit={submit} noValidate>
      <div className="grid gap-5 sm:grid-cols-2">
        <FormField label={t('webhooks.form.name')} error={errors.name}>
          <Input value={f.name} onChange={(e) => set('name', e.target.value)} maxLength={60} autoFocus placeholder={t(isIn ? 'webhooks.form.namePh' : 'webhooks.form.namePhEvent')} data-testid="hook-name" />
        </FormField>
        <FormField label={t('webhooks.form.description')} hint={t('webhooks.form.descriptionHint')}>
          <Input value={f.description} onChange={(e) => set('description', e.target.value)} maxLength={200} />
        </FormField>
      </div>

      {isIn ? (
        <div className="grid gap-5 sm:grid-cols-2">
          <FormField label={t('webhooks.form.source')} hint={t(`webhooks.form.sourceHint.${f.source}` as TKey)}>
            <Select value={f.source} onValueChange={(v) => set('source', v as WebhookSource)} options={SOURCES.map((s) => ({ value: s, label: t(`webhooks.form.src.${s}` as TKey) }))} aria-label={t('webhooks.form.source')} />
          </FormField>
          {seed.mode === 'new' && (
            <FormField label={t(f.source === 'phone' ? 'webhooks.form.key' : 'webhooks.form.secret')} hint={t(SIGNED.includes(f.source) ? 'webhooks.form.secretSigned' : f.source === 'phone' ? 'webhooks.form.keyHint' : 'webhooks.form.secretHint')}>
              <SecretInput value={f.secret} onChange={(e) => set('secret', e.target.value)} placeholder={t('webhooks.secretPlaceholder')} />
            </FormField>
          )}
        </div>
      ) : (
        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label>{t('webhooks.form.on')}</Label>
            <Segmented<On>
              value={f.on}
              onChange={(v) => setF((c) => ({ ...c, on: v, target: ANY }))}
              aria-label={t('webhooks.form.on')}
              options={[
                { value: 'feed', label: t('webhooks.form.on.feed') },
                { value: 'agent', label: t('webhooks.form.on.agent') },
                { value: 'cron', label: t('webhooks.form.on.cron') },
              ]}
            />
          </div>
          {f.on === 'feed' ? (
            <div className="grid gap-5 sm:grid-cols-2">
              <FormField label={t('webhooks.form.feedSource')} hint={t('webhooks.form.feedSourceHint')}>
                <Input value={f.feedSource} onChange={(e) => set('feedSource', e.target.value)} placeholder="stripe" />
              </FormField>
              <FormField label={t('webhooks.form.contains')} hint={t('webhooks.form.containsHint')}>
                <Input value={f.contains} onChange={(e) => set('contains', e.target.value)} />
              </FormField>
            </div>
          ) : (
            <div className="grid gap-5 sm:grid-cols-2">
              <FormField label={t(f.on === 'agent' ? 'webhooks.form.agent' : 'webhooks.form.cron')}>
                <Combobox value={f.target} onChange={(v) => set('target', v)} options={targets} aria-label={t(f.on === 'agent' ? 'webhooks.form.agent' : 'webhooks.form.cron')} />
              </FormField>
              <div className="grid content-start gap-2">
                <Label>{t('webhooks.form.when')}</Label>
                <Segmented<When>
                  value={f.when}
                  onChange={(v) => set('when', v)}
                  aria-label={t('webhooks.form.when')}
                  options={[
                    { value: 'any', label: t('webhooks.form.when.any') },
                    { value: 'ok', label: t('webhooks.form.when.ok') },
                    { value: 'fail', label: t('webhooks.form.when.fail') },
                  ]}
                />
              </div>
            </div>
          )}
        </div>
      )}

      <div className="grid gap-4 rounded-lg border bg-fill-1 p-4">
        <FormField label={t('webhooks.form.action')}>
          <Select value={f.action} onValueChange={(v) => set('action', v as ActionKind)} options={actions.map((a) => ({ value: a, label: t(`webhooks.form.act.${a}` as TKey) }))} aria-label={t('webhooks.form.action')} data-testid="hook-action" />
        </FormField>
        {f.action === 'shell' && (
          <FormField label={t('webhooks.form.command')} error={errors.command} hint={t('webhooks.form.commandHint')}>
            <Input value={f.command} onChange={(e) => set('command', e.target.value)} className="font-mono text-[13px]" placeholder="/home/me/workspace/projects/acme/scripts/deploy.sh" spellCheck={false} data-testid="hook-command" />
          </FormField>
        )}
        {f.action === 'call' && (
          <div className="grid gap-5 sm:grid-cols-[8rem_minmax(0,1fr)]">
            <FormField label={t('webhooks.form.method')}>
              <Select value={f.method} onValueChange={(v) => set('method', v)} options={['POST', 'GET', 'PUT', 'PATCH', 'DELETE'].map((m) => ({ value: m, label: m }))} aria-label={t('webhooks.form.method')} />
            </FormField>
            <FormField label={t('webhooks.form.url')} error={errors.url} hint={t(isIn ? 'webhooks.form.urlHint' : 'webhooks.form.urlHintEvent')}>
              <Input value={f.url} onChange={(e) => set('url', e.target.value)} className="font-mono text-[13px]" placeholder="https://hooks.example.com/…" spellCheck={false} />
            </FormField>
          </div>
        )}
        {f.action === 'store' && <p className="text-[13px] text-muted-foreground">{t('webhooks.form.storeHint')}</p>}
        {f.action === 'notify' && (
          <div className="grid gap-5 sm:grid-cols-[minmax(0,1fr)_10rem]">
            <FormField label={t('webhooks.form.title')} hint={t(isIn && SIGNED.includes(f.source) ? 'webhooks.form.titleHintSigned' : 'webhooks.form.titleHint')}>
              <Input value={f.title} onChange={(e) => set('title', e.target.value)} placeholder="{{title}}" />
            </FormField>
            <FormField label={t('webhooks.form.level')}>
              <Select value={f.level} onValueChange={(v) => set('level', v)} options={['info', 'success', 'warning', 'error'].map((l) => ({ value: l, label: t(`webhooks.form.lvl.${l}` as TKey) }))} aria-label={t('webhooks.form.level')} />
            </FormField>
            <FormField label={t('webhooks.form.body')} className="sm:col-span-2">
              <Input value={f.body} onChange={(e) => set('body', e.target.value)} />
            </FormField>
          </div>
        )}
        {isIn && (f.action === 'shell' || f.action === 'call') && (f.source === 'generic' || f.source === 'phone') && (
          <div className="flex items-start justify-between gap-4">
            <div className="grid gap-0.5">
              <Label htmlFor="hook-wait">{t('webhooks.form.wait')}</Label>
              <p className="text-[13px] text-muted-foreground">{t('webhooks.form.waitHint')}</p>
            </div>
            <Switch id="hook-wait" checked={f.wait} onCheckedChange={(v) => set('wait', v)} />
          </div>
        )}
      </div>

      <div className="grid gap-2">
        <Label>{t('webhooks.form.report')}</Label>
        <Segmented<Report>
          value={f.report}
          onChange={(v) => set('report', v)}
          aria-label={t('webhooks.form.report')}
          options={[
            { value: 'never', label: t('webhooks.form.report.never') },
            { value: 'fail', label: t('webhooks.form.report.fail') },
            { value: 'always', label: t('webhooks.form.report.always') },
          ]}
        />
        <p className="text-[13px] text-muted-foreground">{t('webhooks.form.reportHint')}</p>
      </div>

      <p className="text-[13px] text-muted-foreground">{t('webhooks.form.more')}</p>

      {errors.form && <Callout tone="error">{errors.form}</Callout>}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>
          {t('common.cancel')}
        </Button>
        <Button type="submit" loading={save.isPending} disabled={presentation} data-testid="hook-save">
          {seed.mode === 'edit' ? t('common.save') : t('webhooks.form.create')}
        </Button>
      </DialogFooter>
    </form>
  )
}
