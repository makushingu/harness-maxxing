// Job editor (create / edit / duplicate). Errors from the server are mapped to their field.
import * as React from 'react'
import { Bot, Terminal } from 'lucide-react'
import { useT } from '@/i18n'
import { isApiError } from '@/lib/api'
import { useClaudeStatus, useSaveCron, useTelegram, useWorkspace } from '@/lib/queries'
import type { Cron, CronKind, CronNotify, CronPermissionMode } from '@/lib/types'
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  Label,
  Segmented,
  Select,
  Switch,
  Textarea,
  toast,
  useMask,
  usePresentation,
} from '@/components/ui'
import { Combobox } from '@/components/ui/combobox'
import { Callout } from '@/features/common'
import { SchedulePicker } from './SchedulePicker'
import { UNIT_S, splitTimeout, type TimeoutUnit } from './schedule'

export type EditorSeed = { mode: 'new' } | { mode: 'edit'; job: Cron } | { mode: 'duplicate'; job: Cron }

type Form = {
  name: string
  kind: CronKind
  command: string
  topic_path: string | null
  prompt: string
  model: string
  reuse_session: boolean
  permission_mode: CronPermissionMode
  schedule: string
  enabled: boolean
  notify: CronNotify
  timeout: string
  unit: TimeoutUnit
}
type Field = 'name' | 'command' | 'topic' | 'prompt' | 'schedule' | 'timeout' | 'form'

function initial(seed: EditorSeed, copyName: (n: string) => string): Form {
  if (seed.mode === 'new')
    return {
      name: '',
      kind: 'shell',
      command: '',
      topic_path: null,
      prompt: '',
      model: '',
      reuse_session: false,
      permission_mode: '',
      schedule: '0 7 * * *',
      enabled: true,
      notify: 'failure',
      timeout: '1',
      unit: 'h',
    }
  const j = seed.job
  const to = splitTimeout(j.timeout_s || 3600)
  return {
    name: seed.mode === 'duplicate' ? copyName(j.name) : j.name,
    kind: j.kind,
    command: j.command,
    topic_path: j.kind === 'claude' ? j.topic_path : null,
    prompt: j.prompt,
    model: j.model,
    reuse_session: j.reuse_session,
    permission_mode: j.permission_mode || '',
    schedule: j.schedule,
    enabled: seed.mode === 'duplicate' ? false : j.enabled,
    notify: j.notify,
    timeout: String(to.value),
    unit: to.unit,
  }
}

const CODE_FIELD: Record<string, Field> = {
  invalid_name: 'name',
  invalid_command: 'command',
  invalid_prompt: 'prompt',
  invalid_topic: 'topic',
  invalid_timeout: 'timeout',
  invalid: 'schedule',
}

export function CronEditor({ seed, onOpenChange, onSaved }: { seed: EditorSeed | null; onOpenChange: (o: boolean) => void; onSaved: (job: Cron) => void }) {
  const t = useT()
  return (
    <Dialog open={!!seed} onOpenChange={onOpenChange}>
      <DialogContent className="md:max-w-2xl">
        {seed && (
          <>
            <DialogHeader>
              <DialogTitle>{seed.mode === 'edit' ? t('crons.editTitle') : seed.mode === 'duplicate' ? t('crons.duplicateTitle') : t('crons.newTitle')}</DialogTitle>
              <DialogDescription>{t('crons.editorDesc')}</DialogDescription>
            </DialogHeader>
            <EditorForm key={seed.mode === 'new' ? 'new' : `${seed.mode}:${seed.job.id}`} seed={seed} onCancel={() => onOpenChange(false)} onSaved={onSaved} />
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

function EditorForm({ seed, onCancel, onSaved }: { seed: EditorSeed; onCancel: () => void; onSaved: (job: Cron) => void }) {
  const t = useT()
  const mask = useMask()
  const presentation = usePresentation()
  const [f, setF] = React.useState<Form>(() => initial(seed, (n) => t('crons.copyOf', { name: n })))
  const [errors, setErrors] = React.useState<Partial<Record<Field, string>>>({})
  const save = useSaveCron()
  const { data: claude } = useClaudeStatus()
  const { data: ws } = useWorkspace()
  const { data: tg } = useTelegram()
  const set = <K extends keyof Form>(k: K, v: Form[K]) => {
    setF((cur) => ({ ...cur, [k]: v }))
    const fk = (k === 'topic_path' ? 'topic' : k === 'unit' ? 'timeout' : k) as Field
    if (errors[fk] || errors.form) setErrors((e) => ({ ...e, [fk]: undefined, form: undefined }))
  }

  const topicOptions = React.useMemo(() => {
    const out = [{ value: '__root', label: t('crons.workspaceRoot'), hint: '' }]
    for (const p of ws?.projects || []) {
      out.push({ value: p.path, label: mask(p.name, 6), hint: t('crons.projectHint') })
      for (const tp of p.topics) out.push({ value: tp.path, label: mask(`${p.name} / ${tp.name}`, 9), hint: '' })
    }
    return out
  }, [ws, t, mask])
  const topicValue = f.topic_path === null ? '' : f.topic_path === '' ? '__root' : f.topic_path
  const models = claude?.models || []
  const modelOptions = [
    { value: '__default', label: claude?.default_model ? t('crons.modelDefaultNamed', { model: models.find((m) => m.id === claude.default_model)?.label || claude.default_model }) : t('crons.modelDefault') },
    ...models.map((m) => ({ value: m.id, label: m.label })),
    ...(f.model && !models.some((m) => m.id === f.model) ? [{ value: f.model, label: f.model }] : []),
  ]

  const validate = (): boolean => {
    const e: Partial<Record<Field, string>> = {}
    if (!f.name.trim()) e.name = t('crons.err.name')
    if (f.kind === 'shell' && !f.command.trim()) e.command = t('crons.err.command')
    if (f.kind === 'claude') {
      if (!f.prompt.trim()) e.prompt = t('crons.err.prompt')
      if (f.topic_path === null) e.topic = t('crons.err.topic')
    }
    if (!f.schedule.trim()) e.schedule = t('crons.err.schedule')
    const secs = Number(f.timeout) * UNIT_S[f.unit]
    if (!Number.isFinite(secs) || secs < 10 || secs > 7 * 86400) e.timeout = t('crons.err.timeout')
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return
    const body = {
      name: f.name.trim(),
      kind: f.kind,
      schedule: f.schedule.trim(),
      enabled: f.enabled,
      notify: f.notify,
      timeout_s: Math.round(Number(f.timeout) * UNIT_S[f.unit]),
      ...(f.kind === 'shell'
        ? { command: f.command }
        : { topic_path: f.topic_path || '', prompt: f.prompt, model: f.model, reuse_session: f.reuse_session, permission_mode: f.permission_mode }),
    }
    save.mutate(
      { id: seed.mode === 'edit' ? seed.job.id : undefined, ...body },
      {
        onSuccess: (job) => {
          toast.success(seed.mode === 'edit' ? t('crons.saved') : t('crons.created'))
          onSaved(job)
        },
        onError: (err) => {
          const field = isApiError(err) ? CODE_FIELD[err.code] : undefined
          setErrors({ [field || 'form']: err.message })
        },
      },
    )
  }

  return (
    <form onSubmit={submit} className="grid gap-5" noValidate data-testid="cron-editor">
      <FormField label={t('crons.field.name')} error={errors.name}>
        <Input value={presentation ? mask(f.name) : f.name} readOnly={presentation} onChange={(e) => set('name', e.target.value)} maxLength={80} placeholder={t('crons.namePlaceholder')} autoFocus={seed.mode === 'new'} />
      </FormField>

      <div className="grid gap-2">
        <Label>{t('crons.field.kind')}</Label>
        <Segmented<CronKind>
          value={f.kind}
          onChange={(k) => set('kind', k)}
          aria-label={t('crons.field.kind')}
          options={[
            { value: 'shell', label: t('crons.kind.shell'), icon: <Terminal /> },
            { value: 'claude', label: t('crons.kind.claude'), icon: <Bot /> },
          ]}
        />
      </div>

      {f.kind === 'shell' ? (
        <FormField label={t('crons.field.command')} error={errors.command} hint={t('crons.commandHint')}>
          <Textarea
            value={presentation ? mask(f.command, 12) : f.command}
            readOnly={presentation}
            onChange={(e) => set('command', e.target.value)}
            minRows={2}
            maxRows={12}
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
            placeholder="/root/maxxing/projects/acme/scripts/report.sh"
            className="font-mono text-[13px]"
            data-testid="cron-command"
          />
        </FormField>
      ) : (
        <div className="grid gap-5">
          <FormField label={t('crons.field.topic')} error={errors.topic} hint={t('crons.topicHint')}>
            <Combobox value={topicValue} onChange={(v) => set('topic_path', v === '__root' ? '' : v)} options={topicOptions} placeholder={t('crons.pickTopic')} searchPlaceholder={t('tasks.searchTopic')} />
          </FormField>
          <FormField label={t('crons.field.prompt')} error={errors.prompt}>
            <Textarea
              value={presentation ? mask(f.prompt, 12) : f.prompt}
              readOnly={presentation}
              onChange={(e) => set('prompt', e.target.value)}
              minRows={4}
              maxRows={14}
              placeholder={t('crons.promptPlaceholder')}
              data-testid="cron-prompt"
            />
          </FormField>
          <div className="grid gap-5 sm:grid-cols-2">
            <FormField label={t('crons.field.model')}>
              <Select value={f.model || '__default'} onValueChange={(v) => set('model', v === '__default' ? '' : v)} options={modelOptions} />
            </FormField>
            <div className="grid content-start gap-2">
              <Label htmlFor="cron-reuse">{t('crons.field.reuse')}</Label>
              <div className="flex min-h-9 items-center gap-3">
                <Switch id="cron-reuse" checked={f.reuse_session} onCheckedChange={(v) => set('reuse_session', v)} />
                <span className="text-[13px] text-muted-foreground">{f.reuse_session ? t('crons.reuseOn') : t('crons.reuseOff')}</span>
              </div>
            </div>
          </div>
          <FormField label={t('crons.field.permission')} hint={t('crons.permissionHint')}>
            <Select
              value={f.permission_mode || '__inherit'}
              onValueChange={(v) => set('permission_mode', (v === '__inherit' ? '' : v) as CronPermissionMode)}
              options={[
                { value: '__inherit', label: t('crons.permissionInherit') },
                { value: 'bypass', label: t('claude.mode.bypass') },
                { value: 'acceptEdits', label: t('claude.mode.acceptEdits') },
                { value: 'default', label: t('claude.mode.default') },
              ]}
              className="sm:max-w-sm"
              data-testid="cron-permission"
            />
          </FormField>
        </div>
      )}

      <div className="grid gap-2">
        <Label>{t('crons.field.schedule')}</Label>
        <SchedulePicker value={f.schedule} onChange={(v) => set('schedule', v)} error={errors.schedule} />
        {errors.schedule && (
          <p className="text-[13px] text-destructive" role="alert">
            {errors.schedule}
          </p>
        )}
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <FormField label={t('crons.field.timeout')} error={errors.timeout} hint={t('crons.timeoutHint')}>
          <div className="flex gap-2">
            <Input type="number" min={1} inputMode="numeric" value={f.timeout} onChange={(e) => set('timeout', e.target.value)} className="w-24 tabular-nums" aria-label={t('crons.field.timeout')} />
            <Select
              value={f.unit}
              onValueChange={(v) => set('unit', v as TimeoutUnit)}
              aria-label={t('crons.timeoutUnit')}
              className="w-32"
              options={[
                { value: 's', label: t('crons.unit.s') },
                { value: 'min', label: t('crons.unit.min') },
                { value: 'h', label: t('crons.unit.h') },
              ]}
            />
          </div>
        </FormField>
        <div className="grid content-start gap-2">
          <Label htmlFor="cron-enabled">{t('crons.field.enabled')}</Label>
          <div className="flex min-h-9 items-center gap-3">
            <Switch id="cron-enabled" checked={f.enabled} onCheckedChange={(v) => set('enabled', v)} />
            <span className="text-[13px] text-muted-foreground">{f.enabled ? t('crons.enabledOn') : t('crons.enabledOff')}</span>
          </div>
        </div>
      </div>

      <div className="grid gap-2">
        <Label>{t('crons.field.notify')}</Label>
        <Segmented<CronNotify>
          value={f.notify}
          onChange={(v) => set('notify', v)}
          aria-label={t('crons.field.notify')}
          options={[
            { value: 'never', label: t('crons.notify.never') },
            { value: 'failure', label: t('crons.notify.failure') },
            { value: 'always', label: t('crons.notify.always') },
          ]}
        />
        <p className="text-[13px] text-muted-foreground">{tg?.chat ? t('crons.notifyHint') : t('crons.notifyHintNoTelegram')}</p>
      </div>

      {errors.form && <Callout tone="error">{errors.form}</Callout>}

      <DialogFooter>
        <Button variant="outline" onClick={onCancel}>
          {t('common.cancel')}
        </Button>
        <Button type="submit" loading={save.isPending} disabled={presentation}>
          {seed.mode === 'edit' ? t('common.save') : t('crons.create')}
        </Button>
      </DialogFooter>
    </form>
  )
}
