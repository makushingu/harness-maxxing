// Create an agent, in a side sheet (bottom sheet on touch screens). First "in a sentence" (or a template): a new
// session gets the request and Claude prepares the agent (skill maxxing-agents). "Set it up by hand" = 3 steps:
// Where (project, then topic) -> Who (name, face, role, model, permission mode) -> When (first triggers, guards).
// The agent is created at the end; its cron and webhook triggers are added right after (webhook: its URL shown).
import * as React from 'react'
import { useNavigate } from 'react-router'
import { ArrowLeft, ArrowRight, Check, Clock, Rss, Send, ShieldCheck, Sparkles, Webhook } from 'lucide-react'
import { useT } from '@/i18n'
import { isApiError } from '@/lib/api'
import { agentRoute, useAddAgentCron, useAddAgentWebhook, useCreateAgent, useCreateSession, useWorkspace } from '@/lib/queries'
import type { Agent, AgentAvatar, AgentLimits, AgentTriggerInput, AgentWebhookKind, AgentWebhookResult, PermissionMode } from '@/lib/types'
import { SLUG_RE, cn, slugify } from '@/lib/utils'
import { Button, FormField, Input, Select, Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle, Switch, Textarea, toast, useMask } from '@/components/ui'
import { Callout } from '@/features/common'
import { SchedulePicker } from '@/features/crons/SchedulePicker'
import { AgentAvatarIcon, randomAvatar } from './Avatar'
import { sessionsUrl } from '@/pages/sessions/util'
import { AvatarEditor } from './AvatarEditor'
import { DEFAULT_LIMITS, FeedTriggerFields, LimitsFields, ModelSelect, PermissionSelect, WebhookKindSelect, WebhookMade } from './parts'

type Step = 0 | 1 | 2
type Form = {
  project: string
  topic: string
  display: string
  slug: string
  slugEdited: boolean
  avatar: AgentAvatar
  role: string
  model: string
  permission: '' | PermissionMode
  cron: boolean
  schedule: string
  cronPrompt: string
  hook: boolean
  hookKind: AgentWebhookKind
  hookPrompt: string
  feed: boolean
  feedTrigger: AgentTriggerInput
  telegram: boolean
  limits: AgentLimits
}

const fresh = (topicPath?: string): Form => {
  const m = topicPath ? /^projects\/([^/]+)\/topics\/([^/]+)$/.exec(topicPath) : null
  return {
    project: m?.[1] || '',
    topic: m?.[2] || '',
    display: '',
    slug: '',
    slugEdited: false,
    avatar: randomAvatar(),
    role: '',
    model: '',
    permission: '',
    cron: false,
    schedule: '0 8 * * *',
    cronPrompt: '',
    hook: false,
    hookKind: 'generic',
    hookPrompt: '',
    feed: false,
    feedTrigger: { source: '', levels: [], match: '', prompt: '' },
    telegram: false,
    limits: { ...DEFAULT_LIMITS },
  }
}

export function CreateAgent({ open, onOpenChange, topicPath }: { open: boolean; onOpenChange: (o: boolean) => void; topicPath?: string }) {
  const t = useT()
  const mask = useMask()
  const navigate = useNavigate()
  const { data: ws } = useWorkspace()
  const create = useCreateAgent()
  const addCron = useAddAgentCron()
  const addHook = useAddAgentWebhook()
  const [step, setStep] = React.useState<Step>(0)
  // First the one-sentence way (Claude prepares the agent in a session); "Set it up by hand" = the steps below.
  const [manual, setManual] = React.useState(false)
  const [f, setF] = React.useState<Form>(() => fresh(topicPath))
  const [errors, setErrors] = React.useState<{ name?: string; form?: string; schedule?: string }>({})
  const [made, setMade] = React.useState<{ agent: Agent; hook?: AgentWebhookResult['hook']; warn?: string } | null>(null)
  const busy = create.isPending || addCron.isPending || addHook.isPending

  React.useEffect(() => {
    if (open) {
      setF(fresh(topicPath))
      setStep(0)
      setManual(false)
      setErrors({})
      setMade(null)
    }
  }, [open, topicPath])
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }))

  const projects = ws?.projects || []
  const project = projects.find((p) => p.name === f.project)
  const topics = project?.topics || []
  const slug = f.slugEdited ? f.slug : slugify(f.display).slice(0, 48)
  const external = f.hook || f.feed
  const canNext = step === 0 ? !!project && topics.some((x) => x.name === f.topic) : step === 1 ? !!f.display.trim() && SLUG_RE.test(slug) : true

  const submit = async () => {
    setErrors({})
    let agent: Agent
    try {
      agent = await create.mutateAsync({
        topic_path: `projects/${f.project}/topics/${f.topic}`,
        name: slug,
        display_name: f.display.trim(),
        description: f.role.trim(),
        avatar: f.avatar,
        model: f.model,
        permission_mode: f.permission,
        telegram: f.telegram,
        limits: f.limits,
        triggers: f.feed ? [{ kind: 'feed', enabled: true, ...f.feedTrigger }] : [],
      })
    } catch (e) {
      const code = isApiError(e) ? e.code : ''
      const msg = e instanceof Error ? e.message : String(e)
      if (code === 'exists' || code === 'invalid_name') {
        setErrors({ name: code === 'exists' ? t('agents.create.exists') : msg })
        setStep(1)
      } else setErrors({ form: msg })
      return
    }
    // The agent exists: a failing extra trigger is reported, the agent stays.
    const warn: string[] = []
    if (f.cron) {
      try {
        await addCron.mutateAsync({ path: agent.path, schedule: f.schedule, prompt: f.cronPrompt.trim() || t('agents.create.cronDefaultPrompt') })
      } catch (e) {
        warn.push(`${t('agents.create.cronFailed')} ${e instanceof Error ? e.message : ''}`)
      }
    }
    let hook: AgentWebhookResult['hook'] | undefined
    if (f.hook) {
      try {
        hook = (await addHook.mutateAsync({ path: agent.path, kind: f.hookKind, prompt: f.hookPrompt.trim() })).hook
      } catch (e) {
        warn.push(`${t('agents.create.hookFailed')} ${e instanceof Error ? e.message : ''}`)
      }
    }
    toast.success(t('agents.create.done', { name: agent.display_name }))
    if (!hook && !warn.length) {
      onOpenChange(false)
      navigate(agentRoute(agent))
    } else setMade({ agent, hook, warn: warn.join('\n') || undefined })
  }

  const STEPS = [t('agents.create.where'), t('agents.create.who'), t('agents.create.when')]
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="md:w-[560px]" data-testid="agent-create">
        <SheetHeader>
          <SheetTitle>{made ? t('agents.create.madeTitle', { name: made.agent.display_name }) : t('agents.create.title')}</SheetTitle>
          <SheetDescription>{made ? t('agents.create.madeDesc') : manual ? t('agents.create.desc') : t('agents.quick.desc')}</SheetDescription>
          {!made && manual && (
            <ol className="mt-2 flex items-center gap-1.5 text-xs" aria-label={t('agents.create.steps')}>
              {STEPS.map((label, i) => (
                <li key={label} className="flex items-center gap-1.5">
                  {i > 0 && <span className="h-px w-4 bg-border" aria-hidden />}
                  <button
                    type="button"
                    disabled={i > step}
                    onClick={() => setStep(i as Step)}
                    aria-current={i === step ? 'step' : undefined}
                    className={cn('flex items-center gap-1.5 rounded-full px-2 py-1 disabled:cursor-default', i === step ? 'bg-primary/15 font-medium text-primary' : 'text-muted-foreground hover:text-foreground disabled:hover:text-muted-foreground')}
                  >
                    <span className={cn('flex size-4 items-center justify-center rounded-full text-[10px] tabular-nums', i < step ? 'bg-primary text-primary-foreground' : 'border')}>{i < step ? <Check className="size-3" /> : i + 1}</span>
                    {label}
                  </button>
                </li>
              ))}
            </ol>
          )}
        </SheetHeader>
        <SheetBody className="grid content-start gap-5">
          {!made && !manual ? (
            <QuickCreate topicPath={topicPath} onManual={() => setManual(true)} onDone={() => onOpenChange(false)} />
          ) : made ? (
            <div className="grid gap-4">
              {made.warn && <Callout tone="warning">{made.warn}</Callout>}
              {made.hook && <WebhookMade hook={made.hook} />}
              <div>
                <Button
                  onClick={() => {
                    onOpenChange(false)
                    navigate(agentRoute(made.agent))
                  }}
                >
                  {t('agents.create.openAgent')} <ArrowRight />
                </Button>
              </div>
            </div>
          ) : step === 0 ? (
            <>
              <FormField label={t('agents.create.project')}>
                <Select
                  value={f.project || undefined}
                  onValueChange={(v) => setF((x) => ({ ...x, project: v, topic: projects.find((p) => p.name === v)?.topics[0]?.name || '' }))}
                  placeholder={t('agents.create.pickProject')}
                  options={projects.map((p) => ({ value: p.name, label: mask(p.emoji ? `${p.emoji} ${p.name}` : p.name, 6) }))}
                />
              </FormField>
              <FormField label={t('agents.create.topic')} hint={t('agents.create.topicHint')}>
                <Select
                  value={f.topic || undefined}
                  onValueChange={(v) => set('topic', v)}
                  disabled={!project}
                  placeholder={project && !topics.length ? t('agents.create.noTopic') : t('agents.create.pickTopic')}
                  options={topics.map((x) => ({ value: x.name, label: mask(x.name, 6) }))}
                />
              </FormField>
              <Callout tone="info">{t('agents.create.whereExplain')}</Callout>
            </>
          ) : step === 1 ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                <FormField label={t('agents.create.name')} error={errors.name}>
                  <Input value={f.display} autoFocus maxLength={60} onChange={(e) => set('display', e.target.value)} placeholder={t('agents.create.namePlaceholder')} data-testid="agent-name" />
                </FormField>
                <FormField label={t('agents.create.slug')} hint={t('agents.create.slugHint')}>
                  <Input
                    value={slug}
                    maxLength={48}
                    onChange={(e) => setF((x) => ({ ...x, slug: e.target.value.toLowerCase(), slugEdited: true }))}
                    aria-invalid={!!slug && !SLUG_RE.test(slug)}
                    className="font-mono"
                  />
                </FormField>
              </div>
              <div className="grid gap-1.5">
                <span className="text-sm font-medium">{t('agents.create.face')}</span>
                <AvatarEditor value={f.avatar} onChange={(a) => set('avatar', a)} />
              </div>
              <FormField label={t('agents.create.role')} hint={t('agents.create.roleHint')}>
                <Textarea minRows={4} maxRows={14} value={f.role} onChange={(e) => set('role', e.target.value)} placeholder={t('agents.create.rolePlaceholder')} data-testid="agent-role" />
              </FormField>
              <div className="grid gap-3 sm:grid-cols-2">
                <FormField label={t('agents.field.model')}>
                  <ModelSelect value={f.model} onChange={(v) => set('model', v)} />
                </FormField>
                <FormField label={t('agents.field.permission')} hint={t('agents.field.permissionHint')}>
                  <PermissionSelect value={f.permission} onChange={(v) => set('permission', v)} />
                </FormField>
              </div>
            </>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">{t('agents.create.whenExplain')}</p>
              <TriggerToggle icon={Clock} title={t('agents.trigger.cron')} desc={t('agents.trigger.cronDesc')} on={f.cron} onChange={(v) => set('cron', v)} testId="agent-cron">
                <SchedulePicker value={f.schedule} onChange={(v) => set('schedule', v)} error={errors.schedule} />
                <FormField label={t('agents.trigger.prompt')} hint={t('agents.trigger.cronPromptHint')}>
                  <Textarea minRows={2} maxRows={8} value={f.cronPrompt} onChange={(e) => set('cronPrompt', e.target.value)} placeholder={t('agents.create.cronDefaultPrompt')} />
                </FormField>
              </TriggerToggle>
              <TriggerToggle icon={Webhook} title={t('agents.trigger.webhook')} desc={t('agents.trigger.webhookDesc')} on={f.hook} onChange={(v) => set('hook', v)} testId="agent-hook">
                <FormField label={t('agents.hook.kind')}>
                  <WebhookKindSelect value={f.hookKind} onChange={(v) => set('hookKind', v)} />
                </FormField>
                <FormField label={t('agents.trigger.prompt')} hint={t('agents.trigger.promptHint')}>
                  <Textarea minRows={2} maxRows={8} value={f.hookPrompt} onChange={(e) => set('hookPrompt', e.target.value)} placeholder={t('agents.trigger.promptPlaceholder')} />
                </FormField>
                <p className="text-xs text-muted-foreground">{t('agents.hook.afterCreate')}</p>
              </TriggerToggle>
              <TriggerToggle icon={Rss} title={t('agents.trigger.feed')} desc={t('agents.trigger.feedDesc')} on={f.feed} onChange={(v) => set('feed', v)} testId="agent-feed">
                <FeedTriggerFields value={f.feedTrigger} onChange={(v) => set('feedTrigger', v)} />
              </TriggerToggle>
              <TriggerToggle icon={Send} title={t('agents.trigger.telegram')} desc={t('agents.trigger.telegramDesc')} on={f.telegram} onChange={(v) => set('telegram', v)} testId="agent-telegram" />
              {external && (f.permission === '' || f.permission === 'bypass') && (
                <Callout
                  tone="warning"
                  icon={ShieldCheck}
                  action={
                    <Button size="sm" variant="outline" onClick={() => set('permission', 'acceptEdits')}>
                      {t('agents.create.useSafer')}
                    </Button>
                  }
                >
                  {t('agents.create.externalWarn')}
                </Callout>
              )}
              <details className="group rounded-lg border p-3">
                <summary className="cursor-pointer text-sm font-medium">{t('agents.limits.title')}</summary>
                <p className="mt-1 mb-3 text-xs text-muted-foreground">{t('agents.limits.desc')}</p>
                <LimitsFields value={f.limits} onChange={(l) => set('limits', l)} />
              </details>
              {errors.form && <Callout tone="error">{errors.form}</Callout>}
            </>
          )}
        </SheetBody>
        {!made && manual && (
          <div className="flex shrink-0 items-center justify-between gap-2 border-t px-5 py-3">
            {step > 0 ? (
              <Button variant="ghost" onClick={() => setStep((step - 1) as Step)} disabled={busy}>
                <ArrowLeft /> {t('common.back')}
              </Button>
            ) : (
              <span />
            )}
            {step < 2 ? (
              <Button onClick={() => setStep((step + 1) as Step)} disabled={!canNext} data-testid="agent-next">
                {t('agents.create.next')} <ArrowRight />
              </Button>
            ) : (
              <Button onClick={submit} loading={busy} data-testid="agent-submit">
                <Check /> {t('agents.create.submit')}
              </Button>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}

function TriggerToggle({
  icon: Icon,
  title,
  desc,
  on,
  onChange,
  testId,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  desc: string
  on: boolean
  onChange: (v: boolean) => void
  testId?: string
  children?: React.ReactNode
}) {
  const id = React.useId()
  return (
    <div className={cn('rounded-lg border transition-colors', on && 'border-primary/40 bg-primary/5')}>
      <div className="flex items-start gap-3 p-3">
        <Icon className="mt-0.5 size-4 shrink-0 text-primary" />
        <label htmlFor={id} className="grid min-w-0 flex-1 cursor-pointer gap-0.5">
          <span className="text-sm font-medium">{title}</span>
          <span className="text-xs text-muted-foreground">{desc}</span>
        </label>
        <Switch id={id} checked={on} onCheckedChange={onChange} data-testid={testId} />
      </div>
      {on && children && <div className="grid gap-3 border-t px-3 pt-3 pb-3">{children}</div>}
    </div>
  )
}

const TEMPLATES = ['feedback', 'digest', 'support', 'watch'] as const
const TEMPLATE_AVATAR: Record<(typeof TEMPLATES)[number], AgentAvatar> = {
  feedback: { color: 'orange', eyes: 'wide', mouth: 'smile', hat: 'cap', bg: 'orange' },
  digest: { color: 'violet', eyes: 'dots', mouth: 'smile', hat: 'antenna', bg: 'slate' },
  support: { color: 'teal', eyes: 'dots', mouth: 'grin', hat: 'none', bg: 'teal' },
  watch: { color: 'blue', eyes: 'wide', mouth: 'smile', hat: 'antenna', bg: 'blue' },
}

/** "What should it do, and when?" in a sentence (or from a template): a new session in the chosen topic gets the
 * request, and Claude (skill maxxing-agents) infers the rest, asks what is missing and creates the agent. */
function QuickCreate({ topicPath, onManual, onDone }: { topicPath?: string; onManual: () => void; onDone: () => void }) {
  const t = useT()
  const mask = useMask()
  const navigate = useNavigate()
  const { data: ws } = useWorkspace()
  const start = useCreateSession()
  const [text, setText] = React.useState('')
  const topics = React.useMemo(
    () => (ws?.projects || []).filter((p) => p.name !== 'system').flatMap((p) => p.topics.map((x) => ({ value: `projects/${p.name}/topics/${x.name}`, label: `${p.name} / ${x.name}` }))),
    [ws],
  )
  const [where, setWhere] = React.useState(topicPath || '')
  const go = () => {
    const v = text.trim()
    if (!v) return
    const path = where || (topics.some((x) => x.value === 'projects/general/topics/inbox') ? 'projects/general/topics/inbox' : topics[0]?.value)
    if (!path) return
    const message = where ? t('agents.quick.promptHere', { text: v }) : t('agents.quick.prompt', { text: v })
    start.mutate({ path, message }, { onSuccess: (s) => (onDone(), navigate(sessionsUrl({ id: s.id, path: s.path }))) })
  }
  return (
    <div className="grid gap-4" data-testid="agent-quick">
      <div className="grid gap-2 rounded-xl border bg-card p-3 focus-within:border-primary/50">
        <Textarea
          autoFocus
          minRows={3}
          maxRows={10}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault()
              go()
            }
          }}
          placeholder={t('agents.quick.placeholder')}
          className="resize-none border-0 bg-transparent p-1 text-[15px] shadow-none focus-visible:ring-0 dark:bg-transparent"
          data-testid="agent-quick-text"
        />
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={where || '_auto'}
            onValueChange={(v) => setWhere(v === '_auto' ? '' : v)}
            className="w-56 max-sm:w-full"
            aria-label={t('agents.quick.where')}
            options={[{ value: '_auto', label: t('agents.quick.auto') }, ...topics.map((x) => ({ value: x.value, label: mask(x.label, 8) }))]}
          />
          <Button className="ml-auto" onClick={go} disabled={!text.trim()} loading={start.isPending} data-testid="agent-quick-go">
            <Sparkles /> {t('agents.quick.go')}
          </Button>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {TEMPLATES.map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setText(t(`agents.tpl.${k}.text` as 'agents.tpl.feedback.text'))}
            className="flex items-start gap-3 rounded-xl border bg-card p-3 text-left transition-colors hover:border-primary/40 hover:bg-accent/40"
            data-testid={`agent-tpl-${k}`}
          >
            <AgentAvatarIcon avatar={TEMPLATE_AVATAR[k]} size={32} />
            <span className="grid min-w-0 gap-0.5">
              <span className="text-sm font-medium">{t(`agents.tpl.${k}.title` as 'agents.tpl.feedback.title')}</span>
              <span className="text-xs text-muted-foreground">{t(`agents.tpl.${k}.desc` as 'agents.tpl.feedback.desc')}</span>
            </span>
          </button>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">{t('agents.quick.how')}</p>
      <div>
        <Button variant="link" className="h-auto p-0" onClick={onManual} data-testid="agent-manual">
          {t('agents.quick.manual')}
        </Button>
      </div>
    </div>
  )
}
