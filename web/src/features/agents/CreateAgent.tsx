// Create an agent, in a side sheet (bottom sheet on touch screens). First where (project, then topic), then "With
// Claude": a new session of that topic opens in Sessions with the request started and Claude prepares the agent (skill
// maxxing-agents); or a ready-made agent of the gallery (GET /api/agents/templates) fills the steps below, to check and
// create. "By hand" = 3 steps:
// Where (project, then topic) -> Who (name, face, role, model, permission mode) -> When (first triggers, guards).
// The agent is created at the end; its cron and webhook triggers are added right after (webhook: its URL shown).
// A ready-made agent made for a mailbox (`mail`) asks on the last step which mailbox of the E-mail page it gets.
// "Import a Claude Code agent file": a .claude/agents/<name>.md file (picked or pasted) becomes an agent of a topic.
import * as React from 'react'
import { Link, useNavigate } from 'react-router'
import { ArrowLeft, ArrowRight, Check, Clock, Dices, FileUp, Mail, Rss, Send, ShieldCheck, SlidersHorizontal, Sparkles, Webhook } from 'lucide-react'
import { useLang, useT } from '@/i18n'
import { errorMessage, isApiError } from '@/lib/api'
import { agentRoute, useAddAgentCron, useAddAgentWebhook, useAgentTemplates, useCreateAgent, useImportAgent, useMailAccounts, useSettings, useWorkspace } from '@/lib/queries'
import type { Agent, AgentAvatar, AgentImportResult, AgentLimits, AgentTemplate, AgentTriggerInput, AgentWebhookKind, AgentWebhookResult, PermissionMode } from '@/lib/types'
import { SLUG_RE, cn, slugify } from '@/lib/utils'
import { Button, FormField, Input, Select, Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle, Switch, Textarea, toast, useMask } from '@/components/ui'
import { Callout } from '@/features/common'
import { SchedulePicker } from '@/features/crons/SchedulePicker'
import { AgentAvatarIcon, projectColor, randomAvatar } from './Avatar'
import { useProjectColorOf } from './layout'
import { AvatarEditor } from './AvatarEditor'
import { useCreateWithClaude } from './EditWithClaude'
import { DEFAULT_LIMITS, FeedTriggerFields, KeyChecks, LimitsFields, ModelSelect, PermissionSelect, WebhookKindSelect, WebhookMade } from './parts'

type Step = 0 | 1 | 2
type Form = {
  project: string
  topic: string
  display: string
  slug: string
  slugEdited: boolean
  avatar: AgentAvatar
  /** the user picked the outfit colour: changing the project no longer changes it */
  colorEdited: boolean
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
  approvals: boolean
  allowed: string[]
  keys: string[]
  /** the mailbox given to a template made for one (its `mail`) */
  mailAccount: string
}

/** `colorOf` = the project's colour (useProjectColorOf: the one picked on the Agents page). */
const fresh = (topicPath?: string, colorOf: ColorOf = projectColor): Form => {
  const m = topicPath ? /^projects\/([^/]+)\/topics\/([^/]+)$/.exec(topicPath) : null
  return {
    project: m?.[1] || '',
    topic: m?.[2] || '',
    display: '',
    slug: '',
    slugEdited: false,
    avatar: randomAvatar(m?.[1] ? colorOf(m[1]) : undefined),
    colorEdited: false,
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
    approvals: false,
    allowed: [],
    keys: [],
    mailAccount: '',
  }
}

/** The character of the new agent: small with "Change" (and Random), the editor unfolds under it. */
function CharacterField({ value, project, onChange }: { value: AgentAvatar; project: string; onChange: (a: AgentAvatar) => void }) {
  const t = useT()
  const colorOf = useProjectColorOf()
  const [open, setOpen] = React.useState(false)
  return (
    <div className="grid gap-3" data-testid="agent-character">
      <div className="flex items-center gap-3">
        <AgentAvatarIcon avatar={value} size={48} animate />
        <div className="grid min-w-0 flex-1">
          <span className="text-sm font-medium">{t('agents.create.face')}</span>
          <span className="text-xs text-muted-foreground">{t('agents.create.faceHint')}</span>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={() => onChange(randomAvatar(project ? colorOf(project) : undefined))} aria-label={t('agents.avatar.random')} title={t('agents.avatar.random')}>
          <Dices />
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={() => setOpen((o) => !o)} aria-expanded={open} data-testid="agent-character-edit">
          {open ? t('common.close') : t('agents.create.faceEdit')}
        </Button>
      </div>
      {open && <AvatarEditor value={value} onChange={onChange} project={project} preview={false} className="rounded-xl border p-4" />}
    </div>
  )
}

/** The character in the outfit colour of `project` (its agents are told apart by it). */
function dressFor(a: AgentAvatar, project: string, colorOf: ColorOf): AgentAvatar {
  return project ? { ...a, color: colorOf(project) } : a
}
type ColorOf = (project: string) => string

/** The form filled from a ready-made agent: its name, face, role, safety settings and first trigger. */
const fromTemplate = (tp: AgentTemplate, topicPath: string | undefined, colorOf: ColorOf): Form => ({
  ...fresh(topicPath, colorOf),
  display: tp.name,
  avatar: dressFor({ ...tp.avatar }, fresh(topicPath).project, colorOf),
  role: tp.role,
  permission: tp.permission_mode,
  approvals: tp.approvals,
  allowed: [...tp.allowed_tools],
  keys: [...tp.keys_present],
  limits: { ...DEFAULT_LIMITS, ...tp.limits },
  cron: !!tp.cron,
  schedule: tp.cron?.schedule || '0 8 * * *',
  cronPrompt: tp.cron?.prompt || '',
  hook: !!tp.webhook,
  hookKind: tp.webhook?.kind || 'generic',
  hookPrompt: tp.webhook?.prompt || '',
})

/** How the sheet opens: on "Where?" + the choice With Claude / By hand (default), straight on the steps, on the import,
 *  or on a template (chosen from the empty Agents page, which shows the same choice), `topic` = the topic picked there. */
export type CreateStart = { manual?: boolean; importing?: boolean; template?: AgentTemplate | null; topic?: string }

export function CreateAgent({ open, onOpenChange, topicPath, start }: { open: boolean; onOpenChange: (o: boolean) => void; topicPath?: string; start?: CreateStart | null }) {
  const t = useT()
  const mask = useMask()
  const navigate = useNavigate()
  const { data: ws } = useWorkspace()
  const colorOf = useProjectColorOf()
  const create = useCreateAgent()
  const addCron = useAddAgentCron()
  const addHook = useAddAgentWebhook()
  const [step, setStep] = React.useState<Step>(0)
  // First where + the choice (QuickCreate: With Claude = a session in Sessions prepares the agent); "By hand" = the steps.
  const [manual, setManual] = React.useState(false)
  const [importing, setImporting] = React.useState(false)
  const [tpl, setTpl] = React.useState<AgentTemplate | null>(null)
  // The topic picked in QuickCreate (or on the empty page) wins over the list's filter.
  const [where, setWhere] = React.useState(topicPath)
  const [f, setF] = React.useState<Form>(() => fresh(topicPath, colorOf))
  const [errors, setErrors] = React.useState<{ name?: string; form?: string; schedule?: string }>({})
  const [made, setMade] = React.useState<{ agent: Agent; hook?: AgentWebhookResult['hook']; warn?: string } | null>(null)
  const busy = create.isPending || addCron.isPending || addHook.isPending
  const { data: settings } = useSettings()
  const mailOn = !!settings?.mail_page
  const needsMail = !!tpl?.mail
  const { data: mailboxes } = useMailAccounts(open && needsMail && mailOn)

  // the only mailbox is picked already
  React.useEffect(() => {
    if (needsMail && mailboxes?.length === 1 && !f.mailAccount) setF((x) => ({ ...x, mailAccount: mailboxes[0].id }))
  }, [needsMail, mailboxes, f.mailAccount])
  React.useEffect(() => {
    if (open) {
      const tp = start?.template || null
      const w = start?.topic || topicPath
      const next = tp ? fromTemplate(tp, w, colorOf) : fresh(w, colorOf)
      setWhere(w)
      setF(next)
      setStep(tp && next.project && next.topic ? 1 : 0)
      setManual(!!tp || !!start?.manual)
      setImporting(!tp && !!start?.importing)
      setTpl(tp)
      setErrors({})
      setMade(null)
    }
  }, [open, topicPath, start])
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
        ...(tpl && { template: tpl.id }),
        display_name: f.display.trim(),
        description: f.role.trim(),
        avatar: f.avatar,
        model: f.model,
        permission_mode: f.permission,
        telegram: f.telegram,
        limits: f.limits,
        approvals: f.approvals,
        allowed_tools: f.allowed,
        keys: f.keys,
        triggers: f.feed ? [{ kind: 'feed', enabled: true, ...f.feedTrigger }] : [],
        ...(tpl?.mail && f.mailAccount && { mail: [{ account: f.mailAccount, ...tpl.mail }] }),
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
          <SheetTitle>{made ? t('agents.create.madeTitle', { name: made.agent.display_name }) : importing ? t('agents.import.title') : t('agents.create.title')}</SheetTitle>
          <SheetDescription>{made ? t('agents.create.madeDesc') : importing ? t('agents.import.desc') : manual ? t('agents.create.desc') : t('agents.quick.desc')}</SheetDescription>
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
                    className={cn("relative flex items-center gap-1.5 rounded-full px-2 py-1 disabled:cursor-default pointer-coarse:before:absolute pointer-coarse:before:inset-x-0 pointer-coarse:before:-inset-y-2 pointer-coarse:before:content-['']", i === step ? 'bg-primary/15 font-medium text-primary' : 'text-muted-foreground hover:text-foreground disabled:hover:text-muted-foreground')}
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
          {!made && importing ? (
            <ImportAgentFile
              topicPath={where}
              onBack={() => setImporting(false)}
              onOpen={(a) => {
                onOpenChange(false)
                navigate(agentRoute(a))
              }}
            />
          ) : !made && !manual ? (
            <QuickCreate
              key={where || ''}
              topicPath={where}
              onManual={(w) => {
                const next = fresh(w, colorOf)
                setWhere(w)
                setF(next)
                setManual(true)
                setStep(next.project && next.topic ? 1 : 0)
              }}
              onImport={(w) => {
                setWhere(w)
                setImporting(true)
              }}
              onTemplate={(tp, w) => {
                const next = fromTemplate(tp, w, colorOf)
                setWhere(w)
                setF(next)
                setTpl(tp)
                setManual(true)
                setStep(next.project && next.topic ? 1 : 0)
              }}
              onDone={() => onOpenChange(false)}
            />
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
                  onValueChange={(v) => setF((x) => ({ ...x, project: v, topic: projects.find((p) => p.name === v)?.topics[0]?.name || '', avatar: x.colorEdited ? x.avatar : dressFor(x.avatar, v, colorOf) }))}
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
              {tpl && <Callout tone="info">{t('agents.gallery.from', { name: tpl.name, needs: tpl.needs })}</Callout>}
              <div className="grid items-start gap-3 sm:grid-cols-2">
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
              <CharacterField value={f.avatar} project={f.project} onChange={(a) => setF((x) => ({ ...x, avatar: a, colorEdited: x.colorEdited || a.color !== x.avatar.color }))} />
              <FormField label={t('agents.create.role')} hint={t('agents.create.roleHint')}>
                <Textarea minRows={4} maxRows={14} value={f.role} onChange={(e) => set('role', e.target.value)} placeholder={t('agents.create.rolePlaceholder')} data-testid="agent-role" />
              </FormField>
              <div className="grid items-start gap-3 sm:grid-cols-2">
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
              {needsMail && (
                <div className="grid gap-3 rounded-lg border border-primary/40 bg-primary/5 p-3" data-testid="agent-create-mail">
                  <div className="flex items-start gap-3">
                    <Mail className="mt-0.5 size-4 shrink-0 text-primary" />
                    <div className="grid min-w-0 flex-1 gap-0.5">
                      <span className="text-sm font-medium">{t('agents.mail.createTitle')}</span>
                      <span className="text-xs text-muted-foreground">{t('agents.mail.createDesc')}</span>
                    </div>
                  </div>
                  {!mailOn || (mailboxes && !mailboxes.length) ? (
                    <p className="text-xs">
                      {!mailOn ? t('agents.mail.off') : t('agents.mail.noBox')}{' '}
                      <Link to={mailOn ? '/mail' : '/settings/features'} className="text-primary underline" onClick={() => onOpenChange(false)}>
                        {mailOn ? t('agents.mail.openMail') : t('agents.mail.openFeatures')}
                      </Link>
                    </p>
                  ) : (
                    <Select
                      value={f.mailAccount || undefined}
                      onValueChange={(v) => set('mailAccount', v)}
                      placeholder={t('agents.mail.pick')}
                      aria-label={t('agents.mail.pick')}
                      options={(mailboxes || []).map((x) => ({ value: x.id, label: mask(x.label ? `${x.label} (${x.address})` : x.address, 10) }))}
                    />
                  )}
                </div>
              )}
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
              <div className="grid gap-3 rounded-lg border p-3" data-testid="agent-create-safety">
                <div className="flex items-start gap-3">
                  <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" />
                  <label htmlFor="ag-create-approvals" className="grid min-w-0 flex-1 cursor-pointer gap-0.5">
                    <span className="text-sm font-medium">{t('agents.settings.approvals')}</span>
                    <span className="text-xs text-muted-foreground">{external ? t('agents.create.externalAsks') : t('agents.settings.approvalsDesc')}</span>
                  </label>
                  <Switch id="ag-create-approvals" checked={f.approvals} onCheckedChange={(v) => set('approvals', v)} />
                </div>
                <div className="grid gap-1.5 border-t pt-3">
                  <span className="text-sm font-medium">{t('agents.settings.keys')}</span>
                  <span className="text-xs text-muted-foreground">{t('agents.settings.keysDesc')}</span>
                  <KeyChecks value={f.keys} onChange={(v) => set('keys', v)} />
                </div>
                {f.allowed.length > 0 && (
                  <p className="border-t pt-3 text-xs text-muted-foreground">
                    {t('agents.create.allowedOnly')} <span className="font-mono">{f.allowed.join(', ')}</span>
                  </p>
                )}
              </div>
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
              <Button onClick={submit} loading={busy} disabled={needsMail && !f.mailAccount} data-testid="agent-submit">
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

/** First where the agent lives (project, then topic: prefilled from the list's filter), then how to set it up: "With
 * Claude" opens a new session of that topic in Sessions with the request started (the owner says what it should do
 * and when; Claude, skill maxxing-agents, infers the rest and creates it), "By hand" opens the form on that topic.
 * Below, the gallery of ready-made agents (fills the form) and the import, on the same topic. */
export function QuickCreate({ topicPath, onManual, onImport, onTemplate, onDone }: { topicPath?: string; onManual: (topic: string) => void; onImport: (topic: string) => void; onTemplate: (t: AgentTemplate, topic: string) => void; onDone: () => void }) {
  const t = useT()
  const lang = useLang()
  const { data: templates } = useAgentTemplates(lang)
  const mask = useMask()
  const { data: ws } = useWorkspace()
  const createWithClaude = useCreateWithClaude()
  const projects = React.useMemo(() => (ws?.projects || []).filter((p) => p.name !== 'system'), [ws])
  const m = topicPath ? /^projects\/([^/]+)\/topics\/([^/]+)$/.exec(topicPath) : null
  const [project, setProject] = React.useState(m?.[1] || '')
  const [topic, setTopic] = React.useState(m?.[2] || '')
  const topics = projects.find((p) => p.name === project)?.topics || []
  const where = project && topics.some((x) => x.name === topic) ? `projects/${project}/topics/${topic}` : ''
  const Choice = ({ icon: Icon, title, desc, onClick, id }: { icon: typeof Sparkles; title: string; desc: string; onClick: () => void; id: string }) => (
    <button
      type="button"
      disabled={!where}
      onClick={onClick}
      className="flex items-start gap-3 rounded-xl border bg-card p-3 text-left transition-colors enabled:hover:border-primary/40 enabled:hover:bg-accent/40 disabled:cursor-not-allowed disabled:opacity-50"
      data-testid={id}
    >
      <Icon className="mt-0.5 size-5 shrink-0 text-primary" />
      <span className="grid min-w-0 gap-0.5">
        <span className="text-sm font-medium">{title}</span>
        <span className="text-xs text-muted-foreground">{desc}</span>
      </span>
    </button>
  )
  return (
    <div className="grid gap-5" data-testid="agent-quick">
      <div className="grid items-start gap-3 sm:grid-cols-2">
        <FormField label={t('agents.create.project')}>
          <Select
            value={project || undefined}
            onValueChange={(v) => {
              setProject(v)
              setTopic(projects.find((p) => p.name === v)?.topics[0]?.name || '')
            }}
            placeholder={t('agents.create.pickProject')}
            options={projects.map((p) => ({ value: p.name, label: mask(p.emoji ? `${p.emoji} ${p.name}` : p.name, 6) }))}
          />
        </FormField>
        <FormField label={t('agents.create.topic')}>
          <Select
            value={topic || undefined}
            onValueChange={setTopic}
            disabled={!project}
            placeholder={t('agents.create.pickTopic')}
            options={topics.map((x) => ({ value: x.name, label: mask(x.name, 6) }))}
          />
        </FormField>
      </div>
      <p className="-mt-3 text-xs text-muted-foreground">{t('agents.create.topicHint')}</p>
      <div className="grid gap-2 sm:grid-cols-2">
        <Choice
          id="agent-quick-go"
          icon={Sparkles}
          title={t('agents.quick.go')}
          desc={t('agents.quick.how')}
          onClick={() => {
            onDone()
            createWithClaude(where)
          }}
        />
        <Choice id="agent-manual" icon={SlidersHorizontal} title={t('agents.quick.manual')} desc={t('agents.quick.manualDesc')} onClick={() => onManual(where)} />
      </div>
      {!!templates?.length && (
        <div className="grid gap-2" data-testid="agent-gallery">
          <h3 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('agents.gallery.title')}</h3>
          <div className="grid gap-2 sm:grid-cols-2">
            {templates.map((tp) => (
              <button
                key={tp.id}
                type="button"
                disabled={!where}
                onClick={() => onTemplate(tp, where)}
                className="flex items-start gap-3 rounded-xl border bg-card p-3 text-left transition-colors enabled:hover:border-primary/40 enabled:hover:bg-accent/40 disabled:cursor-not-allowed disabled:opacity-50"
                data-testid={`agent-tpl-${tp.id}`}
              >
                <AgentAvatarIcon avatar={tp.avatar} size={32} />
                <span className="grid min-w-0 gap-0.5">
                  <span className="text-sm font-medium">{tp.name}</span>
                  <span className="text-xs text-muted-foreground">{tp.summary}</span>
                  <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                    {tp.mail?.trigger ? <Mail className="size-3" /> : tp.cron ? <Clock className="size-3" /> : <Webhook className="size-3" />}
                    {tp.mail?.trigger ? t('agents.mail.galleryTag') : tp.cron ? t('agents.gallery.cron') : t('agents.gallery.webhook')}
                    {tp.approvals && <><span aria-hidden>·</span><ShieldCheck className="size-3" /> {t('agents.gallery.asks')}</>}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
      <div>
        <Button variant="link" className="h-auto p-0" disabled={!where} onClick={() => onImport(where)} data-testid="agent-import">
          <FileUp /> {t('agents.import.link')}
        </Button>
      </div>
    </div>
  )
}

/** The topics an agent can live in (the system project aside), as select options. */
function useTopicOptions() {
  const { data: ws } = useWorkspace()
  return React.useMemo(
    () => (ws?.projects || []).filter((p) => p.name !== 'system').flatMap((p) => p.topics.map((x) => ({ value: `projects/${p.name}/topics/${x.name}`, label: `${p.name} / ${x.name}` }))),
    [ws],
  )
}

/** A Claude Code agent file (.claude/agents/<name>.md: front matter + prompt), picked or pasted, becomes an agent of a
 *  topic (POST /api/agents/import). Its fields with no equivalent (mcpServers, memory...) are listed after. */
function ImportAgentFile({ topicPath, onBack, onOpen }: { topicPath?: string; onBack: () => void; onOpen: (a: Agent) => void }) {
  const t = useT()
  const mask = useMask()
  const topics = useTopicOptions()
  const imp = useImportAgent()
  const [where, setWhere] = React.useState(topicPath || '')
  const [text, setText] = React.useState('')
  const [file, setFile] = React.useState('')
  const [name, setName] = React.useState('')
  const [done, setDone] = React.useState<AgentImportResult | null>(null)
  const pick = async (f: File | undefined) => {
    if (!f) return
    setFile(f.name)
    setText(await f.text())
    // the file name is the agent's name in Claude Code: offered as the folder
    if (!name) setName(slugify(f.name.replace(/\.md$/i, '')).slice(0, 48))
  }
  const err = imp.error ? (isApiError(imp.error) && imp.error.code === 'bad_file' ? t('agents.import.badFile', { why: errorMessage(imp.error) }) : errorMessage(imp.error)) : null
  const go = () =>
    imp.mutate(
      { topic_path: where, markdown: text, name: name.trim() || undefined },
      {
        onSuccess: (a) => {
          toast.success(t('agents.create.done', { name: a.display_name }))
          if (a.ignored?.length) setDone(a)
          else onOpen(a)
        },
      },
    )
  if (done)
    return (
      <div className="grid gap-4" data-testid="agent-import-done">
        <Callout tone="info">{t('agents.import.ignored', { fields: done.ignored.join(', ') })}</Callout>
        <div>
          <Button onClick={() => onOpen(done)}>
            {t('agents.create.openAgent')} <ArrowRight />
          </Button>
        </div>
      </div>
    )
  return (
    <div className="grid gap-4" data-testid="agent-import-form">
      <FormField label={t('agents.import.file')} hint={t('agents.import.fileHint')}>
        <div className="flex flex-wrap items-center gap-2">
          <Button asChild variant="outline" size="sm">
            <label className="cursor-pointer">
              <FileUp /> {t('agents.import.pick')}
              <input type="file" accept=".md,text/markdown,text/plain" className="sr-only" onChange={(e) => pick(e.target.files?.[0])} data-testid="agent-import-input" />
            </label>
          </Button>
          {file && <span className="truncate text-xs text-muted-foreground">{mask(file, 8)}</span>}
        </div>
      </FormField>
      <FormField label={t('agents.import.paste')}>
        <Textarea
          minRows={6}
          maxRows={16}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={'---\nname: reviewer\ndescription: Reviews the code after each change\ntools: Read, Grep, Glob\n---\nYou are a careful code reviewer...'}
          className="font-mono text-[13px]"
          data-testid="agent-import-text"
        />
      </FormField>
      <div className="grid items-start gap-3 sm:grid-cols-2">
        <FormField label={t('agents.import.topic')}>
          <Select value={where || undefined} onValueChange={setWhere} placeholder={t('agents.create.pickTopic')} options={topics.map((x) => ({ value: x.value, label: mask(x.label, 8) }))} />
        </FormField>
        <FormField label={t('agents.import.name')} hint={t('agents.import.nameHint')}>
          <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={48} className="font-mono" />
        </FormField>
      </div>
      {err && <Callout tone="error">{err}</Callout>}
      <div className="flex gap-2">
        <Button variant="ghost" onClick={onBack}>
          <ArrowLeft /> {t('common.back')}
        </Button>
        <Button className="ml-auto" onClick={go} disabled={!where || !text.trim()} loading={imp.isPending} data-testid="agent-import-go">
          <FileUp /> {t('agents.import.go')}
        </Button>
      </div>
    </div>
  )
}
