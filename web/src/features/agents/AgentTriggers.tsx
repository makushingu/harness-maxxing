// What starts an agent: its schedules (normal Claude cron jobs in its folder, also on the Crons page), its feed
// triggers (a webhook made for it is a feed source + a trigger on it), and its Telegram thread.
import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Clock, MoreHorizontal, Pencil, Play, Plus, Rss, Send, Trash2, Webhook } from 'lucide-react'
import { useLang, useT } from '@/i18n'
import { agentKeys, useAddAgentCron, useAddAgentWebhook, useDeleteCron, usePatchAgent, usePatchCron, useRunCron } from '@/lib/queries'
import type { AgentDetail, AgentTrigger, AgentTriggerInput, AgentWebhookKind, AgentWebhookResult, Cron } from '@/lib/types'
import { fmtRelative } from '@/lib/format'
import {
  Button, confirm, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DropdownMenu, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger, FormField, Input, Sensitive, Switch, Textarea,
} from '@/components/ui'
import { Callout, SettingRow } from '@/features/common'
import { CronEditor, type EditorSeed } from '@/features/crons/CronEditor'
import { SchedulePicker } from '@/features/crons/SchedulePicker'
import { FeedTriggerFields, WebhookKindSelect, WebhookMade, triggerSummary } from './parts'

function Section({ icon: Icon, title, desc, action, children }: { icon: React.ComponentType<{ className?: string }>; title: string; desc: string; action?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <section className="grid gap-2">
      <div className="flex flex-wrap items-end gap-2">
        <div className="grid min-w-0 flex-1 gap-0.5">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold">
            <Icon className="size-4 text-primary" /> {title}
          </h3>
          <p className="text-xs text-muted-foreground">{desc}</p>
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export function AgentTriggers({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  const patch = usePatchAgent()
  const [cronSeed, setCronSeed] = React.useState<EditorSeed | null>(null)
  const [addCron, setAddCron] = React.useState(false)
  const [feedEdit, setFeedEdit] = React.useState<AgentTriggerInput | null>(null)
  const [hook, setHook] = React.useState(false)
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: agentKeys.all })

  const saveTriggers = (list: AgentTriggerInput[], onSuccess?: () => void) =>
    patch.mutate({ path: a.path, triggers: list.map(({ ...x }) => ({ ...x, kind: 'feed' as const })) }, { onSuccess })
  const toInput = (x: AgentTrigger): AgentTriggerInput => ({ id: x.id, enabled: x.enabled, source: x.source, levels: x.levels, match: x.match, prompt: x.prompt, hook_id: x.hook_id })

  return (
    <div className="grid max-w-3xl gap-8">
      <Section
        icon={Clock}
        title={t('agents.trigger.cronTitle')}
        desc={t('agents.trigger.cronDesc')}
        action={
          <Button size="sm" variant="outline" onClick={() => setAddCron(true)} data-testid="agent-add-cron">
            <Plus /> {t('agents.trigger.addCron')}
          </Button>
        }
      >
        {a.crons.length > 0 ? (
          <ul className="divide-y rounded-xl border bg-card">
            {a.crons.map((j) => (
              <CronRow key={j.id} job={j} onEdit={() => setCronSeed({ mode: 'edit', job: j })} onChanged={refresh} />
            ))}
          </ul>
        ) : (
          <p className="rounded-xl border border-dashed px-4 py-3 text-sm text-muted-foreground">{t('agents.trigger.noCron')}</p>
        )}
      </Section>

      <Section
        icon={Rss}
        title={t('agents.trigger.feedTitle')}
        desc={t('agents.trigger.feedDesc')}
        action={
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => setHook(true)} data-testid="agent-add-hook">
              <Webhook /> {t('agents.trigger.addWebhook')}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setFeedEdit({ enabled: true, source: '', levels: [], match: '', prompt: '' })} data-testid="agent-add-feed">
              <Plus /> {t('agents.trigger.addFeed')}
            </Button>
          </div>
        }
      >
        {a.triggers.length > 0 ? (
          <ul className="divide-y rounded-xl border bg-card">
            {a.triggers.map((x) => (
              <li key={x.id} className="flex items-center gap-3 px-4 py-3">
                {x.hook_id ? <Webhook className="size-4 shrink-0 text-muted-foreground" /> : <Rss className="size-4 shrink-0 text-muted-foreground" />}
                <div className="grid min-w-0 flex-1 gap-0.5">
                  <span className="truncate text-sm">
                    <Sensitive length={10}>{triggerSummary(t, x)}</Sensitive>
                  </span>
                  {x.prompt && (
                    <span className="truncate text-xs text-muted-foreground">
                      <Sensitive length={12}>{x.prompt}</Sensitive>
                    </span>
                  )}
                </div>
                <Switch
                  checked={x.enabled !== false}
                  onCheckedChange={(v) => saveTriggers(a.triggers.map((y) => (y.id === x.id ? { ...toInput(y), enabled: v } : toInput(y))))}
                  aria-label={t('agents.trigger.enabled')}
                />
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon-sm" aria-label={t('common.more')}>
                      <MoreHorizontal />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => setFeedEdit(toInput(x))}>
                      <Pencil /> {t('common.edit')}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      destructive
                      onSelect={async () => {
                        if (!(await confirm({ title: t('agents.trigger.removeTitle'), description: x.hook_id ? t('agents.trigger.removeHookDesc') : undefined, destructive: true, confirmText: t('common.remove') }))) return
                        saveTriggers(a.triggers.filter((y) => y.id !== x.id).map(toInput))
                      }}
                    >
                      <Trash2 /> {t('common.remove')}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </li>
            ))}
          </ul>
        ) : (
          <p className="rounded-xl border border-dashed px-4 py-3 text-sm text-muted-foreground">{t('agents.trigger.noFeed')}</p>
        )}
      </Section>

      <Section icon={Send} title={t('agents.trigger.telegram')} desc={t('agents.trigger.telegramDesc')}>
        <div className="rounded-xl border bg-card p-4">
          <SettingRow label={t('agents.trigger.telegramSwitch')} description={t('agents.trigger.telegramSwitchDesc')} htmlFor="agent-tg">
            <Switch id="agent-tg" checked={a.telegram} onCheckedChange={(v) => patch.mutate({ path: a.path, telegram: v })} />
          </SettingRow>
          {a.telegram && <p className="mt-2 text-xs text-muted-foreground">{t('agents.trigger.telegramNote')}</p>}
        </div>
      </Section>

      <CronEditor seed={cronSeed} onOpenChange={(o) => !o && setCronSeed(null)} onSaved={() => (setCronSeed(null), refresh())} />
      <AddCronDialog open={addCron} onOpenChange={setAddCron} agent={a} />
      <FeedTriggerDialog
        value={feedEdit}
        onClose={() => setFeedEdit(null)}
        pending={patch.isPending}
        onSave={(v) => {
          const list = v.id ? a.triggers.map((y) => (y.id === v.id ? v : toInput(y))) : [...a.triggers.map(toInput), v]
          saveTriggers(list, () => setFeedEdit(null))
        }}
      />
      <WebhookDialog open={hook} onOpenChange={setHook} agent={a} />
    </div>
  )
}

function CronRow({ job: j, onEdit, onChanged }: { job: Cron; onEdit: () => void; onChanged: () => void }) {
  const t = useT()
  const lang = useLang()
  const patch = usePatchCron()
  const run = useRunCron()
  const del = useDeleteCron()
  return (
    <li className="flex items-center gap-3 px-4 py-3">
      <Clock className="size-4 shrink-0 text-muted-foreground" />
      <div className="grid min-w-0 flex-1 gap-0.5">
        <span className="truncate text-sm font-medium">
          <Sensitive length={8}>{j.name}</Sensitive>
        </span>
        <span className="truncate text-xs text-muted-foreground">
          {j.human || j.schedule}
          {j.next_run && j.enabled ? ` · ${t('agents.trigger.next', { when: fmtRelative(j.next_run, lang) })}` : ''}
        </span>
      </div>
      <Switch checked={j.enabled} onCheckedChange={(v) => patch.mutate({ id: j.id, enabled: v }, { onSuccess: onChanged })} aria-label={t('agents.trigger.enabled')} />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label={t('common.more')}>
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => run.mutate(j.id, { onSuccess: onChanged })}>
            <Play /> {t('agents.trigger.runNow')}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={onEdit}>
            <Pencil /> {t('common.edit')}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            destructive
            onSelect={async () => {
              if (!(await confirm({ title: t('agents.trigger.deleteCron', { name: j.name }), destructive: true, confirmText: t('common.delete') }))) return
              del.mutate(j.id, { onSuccess: onChanged })
            }}
          >
            <Trash2 /> {t('common.delete')}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  )
}

function AddCronDialog({ open, onOpenChange, agent: a }: { open: boolean; onOpenChange: (o: boolean) => void; agent: AgentDetail }) {
  const t = useT()
  const add = useAddAgentCron()
  const [schedule, setSchedule] = React.useState('0 8 * * *')
  const [prompt, setPrompt] = React.useState('')
  const [name, setName] = React.useState('')
  React.useEffect(() => {
    if (open) {
      setSchedule('0 8 * * *')
      setPrompt('')
      setName('')
      add.reset()
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('agents.trigger.addCron')}</DialogTitle>
          <DialogDescription>{t('agents.trigger.cronDesc')}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <FormField label={t('agents.trigger.cronName')}>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('agents.trigger.cronNamePlaceholder', { name: a.display_name })} />
          </FormField>
          <SchedulePicker value={schedule} onChange={setSchedule} error={add.error ? add.error.message : undefined} />
          <FormField label={t('agents.trigger.prompt')} hint={t('agents.trigger.cronPromptHint')}>
            <Textarea minRows={2} maxRows={8} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder={t('agents.create.cronDefaultPrompt')} />
          </FormField>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button
            loading={add.isPending}
            onClick={() => add.mutate({ path: a.path, name: name.trim() || undefined, schedule, prompt: prompt.trim() || t('agents.create.cronDefaultPrompt') }, { onSuccess: () => onOpenChange(false) })}
            data-testid="agent-cron-save"
          >
            {t('common.add')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function FeedTriggerDialog({ value, onClose, onSave, pending }: { value: AgentTriggerInput | null; onClose: () => void; onSave: (v: AgentTriggerInput) => void; pending: boolean }) {
  const t = useT()
  const [v, setV] = React.useState<AgentTriggerInput>({})
  React.useEffect(() => {
    if (value) setV(value)
  }, [value])
  return (
    <Dialog open={!!value} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{value?.id ? t('agents.trigger.editFeed') : t('agents.trigger.addFeed')}</DialogTitle>
          <DialogDescription>{t('agents.trigger.feedDesc')}</DialogDescription>
        </DialogHeader>
        <FeedTriggerFields value={v} onChange={setV} sourceLocked={!!v.hook_id} />
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button loading={pending} onClick={() => onSave(v)} data-testid="agent-feed-save">
            {t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function WebhookDialog({ open, onOpenChange, agent: a }: { open: boolean; onOpenChange: (o: boolean) => void; agent: AgentDetail }) {
  const t = useT()
  const add = useAddAgentWebhook()
  const [kind, setKind] = React.useState<AgentWebhookKind>('generic')
  const [prompt, setPrompt] = React.useState('')
  const [made, setMade] = React.useState<AgentWebhookResult['hook'] | null>(null)
  React.useEffect(() => {
    if (open) {
      setKind('generic')
      setPrompt('')
      setMade(null)
      add.reset()
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{made ? t('agents.hook.madeTitle') : t('agents.trigger.addWebhook')}</DialogTitle>
          <DialogDescription>{made ? t('agents.hook.madeDesc') : t('agents.trigger.webhookDesc')}</DialogDescription>
        </DialogHeader>
        {made ? (
          <WebhookMade hook={made} />
        ) : (
          <div className="grid gap-3">
            <FormField label={t('agents.hook.kind')}>
              <WebhookKindSelect value={kind} onChange={setKind} />
            </FormField>
            <FormField label={t('agents.trigger.prompt')} hint={t('agents.trigger.promptHint')}>
              <Textarea minRows={2} maxRows={8} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder={t('agents.trigger.promptPlaceholder')} />
            </FormField>
            {add.error && <Callout tone="error">{add.error.message}</Callout>}
          </div>
        )}
        <DialogFooter>
          {made ? (
            <Button onClick={() => onOpenChange(false)}>{t('agents.done')}</Button>
          ) : (
            <>
              <Button variant="ghost" onClick={() => onOpenChange(false)}>
                {t('common.cancel')}
              </Button>
              <Button loading={add.isPending} onClick={() => add.mutate({ path: a.path, kind, prompt: prompt.trim() }, { onSuccess: (r) => setMade(r.hook) })} data-testid="agent-hook-save">
                {t('agents.hook.create')}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
