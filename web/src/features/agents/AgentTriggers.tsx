// What starts an agent ("When it works" in its profile panel): its schedules (normal Claude cron jobs in its folder,
// also on the Crons page), its feed triggers (a webhook made for it is a feed source + a trigger on it: its address,
// what came in, a test), and its Telegram thread.
import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Clock, MoreHorizontal, Pencil, Play, Rss, Send, Trash2, Webhook } from 'lucide-react'
import { useLang, useT } from '@/i18n'
import { agentKeys, useAddAgentCron, useAddAgentWebhook, useDeleteCron, usePatchAgent, usePatchCron, useRunCron, useTestAgentTrigger } from '@/lib/queries'
import type { AgentDetail, AgentTrigger, AgentTriggerInput, AgentWebhookKind, AgentWebhookResult, Cron } from '@/lib/types'
import { fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import {
  Button, confirm, CopyButton, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DropdownMenu, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger, FormField, Input, Sensitive, Switch, Textarea, toast,
} from '@/components/ui'
import { Callout } from '@/features/common'
import { CronEditor, type EditorSeed } from '@/features/crons/CronEditor'
import { SchedulePicker } from '@/features/crons/SchedulePicker'
import { FeedTriggerFields, WebhookKindSelect, WebhookMade, triggerSummary } from './parts'

/** A dashed "add" row of the panel. */
function AddRow({ icon: Icon, label, onClick, testId }: { icon: React.ComponentType<{ className?: string }>; label: string; onClick: () => void; testId?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testId}
      className="flex w-full items-center gap-2 rounded-xl border border-dashed px-3 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground pointer-coarse:min-h-11"
    >
      <Icon className="size-4 shrink-0" /> {label}
    </button>
  )
}

/** "When it works": the agent's triggers as sentences (schedules, webhooks with their address and what came in,
 * feed filters, Telegram), each switchable, then the rows that add one. */
export function AgentTriggers({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  const lang = useLang()
  const patch = usePatchAgent()
  const test = useTestAgentTrigger()
  const [cronSeed, setCronSeed] = React.useState<EditorSeed | null>(null)
  const [addCron, setAddCron] = React.useState(false)
  const [feedEdit, setFeedEdit] = React.useState<AgentTriggerInput | null>(null)
  const [hook, setHook] = React.useState(false)
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: agentKeys.all })

  const saveTriggers = (list: AgentTriggerInput[], onSuccess?: () => void) =>
    patch.mutate({ path: a.path, triggers: list.map(({ ...x }) => ({ ...x, kind: 'feed' as const })) }, { onSuccess })
  const toInput = (x: AgentTrigger): AgentTriggerInput => ({ id: x.id, enabled: x.enabled, source: x.source, levels: x.levels, match: x.match, prompt: x.prompt, hook_id: x.hook_id })
  const hooks = new Map((a.webhooks || []).map((h) => [h.id, h]))

  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2" data-testid="agent-triggers">
      {a.crons.map((j) => (
        <CronRow key={j.id} job={j} onEdit={() => setCronSeed({ mode: 'edit', job: j })} onChanged={refresh} />
      ))}
      {a.triggers.map((x) => {
        const h = x.hook_id ? hooks.get(x.hook_id) : undefined
        const st = a.trigger_stats?.[x.id]
        return (
          <div key={x.id} className="grid gap-2 rounded-xl border bg-card px-3 py-2.5" data-testid="agent-trigger">
            <div className="flex items-center gap-2">
              {x.hook_id ? <Webhook className="size-4 shrink-0 text-primary" /> : <Rss className="size-4 shrink-0 text-primary" />}
              <span className="min-w-0 flex-1 text-sm">
                <Sensitive length={10}>
                  {x.hook_id
                    ? !h || h.kind === 'generic'
                      ? t('agents.when.webhookAny')
                      : t('agents.when.webhook', { service: t(`agents.hook.${h.kind}` as 'agents.hook.generic') })
                    : t('agents.when.feed', { source: triggerSummary(t, x) })}
                </Sensitive>
              </span>
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
            </div>
            {h && (
              <div className="flex items-center gap-1 rounded-lg bg-muted/60 py-0.5 pr-0.5 pl-2">
                <code className="min-w-0 flex-1 truncate font-mono text-[11px]" data-testid="agent-trigger-url">
                  <Sensitive>{h.url}</Sensitive>
                </code>
                <CopyButton text={h.url} />
              </div>
            )}
            {h && h.kind !== 'generic' && !h.has_secret && <p className="text-xs text-warning">{t('agents.when.noSecret')}</p>}
            {x.prompt && (
              <p className="truncate text-xs text-muted-foreground">
                <Sensitive length={12}>{x.prompt}</Sensitive>
              </p>
            )}
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              <span className={cn('size-1.5 rounded-full', st?.events ? 'bg-success' : 'bg-muted-foreground/40')} aria-hidden />
              <span className="min-w-0 flex-1">
                {st?.events && st.last_event_at
                  ? t('agents.when.received', { count: st.events, when: fmtRelative(st.last_event_at, lang) })
                  : t('agents.when.noneReceived')}
              </span>
              <Button
                variant="link"
                size="sm"
                className="h-auto p-0 text-xs"
                loading={test.isPending && test.variables?.tid === x.id}
                disabled={!a.enabled || x.enabled === false}
                onClick={() => test.mutate({ path: a.path, tid: x.id }, { onSuccess: () => toast.success(t('agents.when.testSent')) })}
                data-testid="agent-trigger-test"
              >
                {t('agents.when.test')}
              </Button>
            </div>
            {h?.kind === 'generic' && (
              <details className="text-xs text-muted-foreground">
                <summary className="cursor-pointer hover:text-foreground">{t('agents.when.howTo')}</summary>
                <p className="mt-1">{t('agents.when.howToGeneric')}</p>
                <code className="mt-1 block rounded-md bg-muted/60 px-2 py-1 font-mono text-[11px] break-all">{'{"title": "…", "body": "…", "level": "info", "id": "unique-id"}'}</code>
              </details>
            )}
          </div>
        )
      })}
      <div className="flex items-center gap-2 rounded-xl border bg-card px-3 py-2.5">
        <Send className="size-4 shrink-0 text-primary" />
        <span className="min-w-0 flex-1 text-sm">{t('agents.when.telegram')}</span>
        <Switch checked={a.telegram} onCheckedChange={(v) => patch.mutate({ path: a.path, telegram: v })} aria-label={t('agents.trigger.telegramSwitch')} data-testid="agent-telegram-switch" />
      </div>
      {a.telegram && <p className="px-1 text-xs text-muted-foreground">{t('agents.trigger.telegramNote')}</p>}
      <AddRow icon={Clock} label={t('agents.when.addCron')} onClick={() => setAddCron(true)} testId="agent-add-cron" />
      <AddRow icon={Webhook} label={t('agents.when.addHook')} onClick={() => setHook(true)} testId="agent-add-hook" />
      <AddRow icon={Rss} label={t('agents.when.addFeed')} onClick={() => setFeedEdit({ enabled: true, source: '', levels: [], match: '', prompt: '' })} testId="agent-add-feed" />

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
    <div className="flex items-center gap-2 rounded-xl border bg-card px-3 py-2.5" data-testid="agent-cron">
      <Clock className="size-4 shrink-0 text-primary" />
      <div className="grid min-w-0 flex-1 gap-0.5">
        <span className="text-sm">{t('agents.when.cron', { when: j.human || j.schedule })}</span>
        <span className="truncate text-xs text-muted-foreground">
          <Sensitive length={8}>{j.name}</Sensitive>
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
    </div>
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
