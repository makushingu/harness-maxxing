// An agent's settings (the sheet opened from its profile), in four sections with a small nav on top:
//   Essentials (on, silent, look, model, daily budget) · Protection (Free = like a session / Protected = its sandbox,
//   with its sites and folders; approvals, keys) · E-mail (only once it has a mailbox or one is asked for,
//   AgentMail.tsx) · Advanced, folded (permission mode, outside events, subagent, tools, rules, the other limits,
//   export), then the danger zone. `section` = the one shown first (?settings=mail on the agent's page).
// Switches save at once; the fields (model, mode, tools, rules, limits) wait for the Save bar. Its name and character
// are edited elsewhere: click the character at the top of its profile (Appearance.tsx).
import * as React from 'react'
import { useNavigate } from 'react-router'
import { AlertTriangle, ChevronRight, Download, Lock, Mail, Pencil, Plus, Trash2, Unlock, X } from 'lucide-react'
import { useT } from '@/i18n'
import { errorMessage, isApiError } from '@/lib/api'
import { agentExportUrl, useDeleteAgent, usePatchAgent } from '@/lib/queries'
import type { AgentDetail, AgentLimits, AgentRule, AgentRuleTool, PermissionMode } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button, confirm, FormField, Input, Select, Sensitive, Switch, Textarea, toast } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { SettingsCard } from '@/pages/settings/sections/ui'
import { AgentMail } from './AgentMail'
import { AppearanceDialog } from './Appearance'
import { KeyChecks, LimitsFields, ModelSelect, PermissionSelect } from './parts'

const toolsText = (l: string[]) => l.join('\n')
const toolsList = (s: string) =>
  s
    .split(/[\n,]+/)
    .map((x) => x.trim())
    .filter(Boolean)

type Draft = { model: string; permission: '' | PermissionMode; allowed: string; disallowed: string; limits: AgentLimits; rules: AgentRule[] }
const draftOf = (a: AgentDetail): Draft => ({
  rules: (a.rules || []).map((r) => ({ ...r, reason: r.reason || '' })),
  model: a.model,
  permission: a.permission_mode,
  allowed: toolsText(a.allowed_tools),
  disallowed: toolsText(a.disallowed_tools),
  limits: { ...a.limits },
})

const SECTIONS = ['essential', 'protection', 'mail', 'advanced'] as const
export type SectionId = (typeof SECTIONS)[number]

/** A section of the sheet: a title, one line of plain words, its settings. */
function Section({ id, title, description, children }: { id: SectionId; title: string; description?: string; children: React.ReactNode }) {
  return (
    <section id={`ag-sec-${id}`} data-section={id} className="grid scroll-mt-14 grid-cols-[minmax(0,1fr)] gap-4 border-t pt-6 first:border-t-0 first:pt-0" aria-labelledby={`ag-sec-${id}-t`}>
      <div className="grid gap-1">
        <h3 id={`ag-sec-${id}-t`} className="text-[15px] font-semibold tracking-tight">
          {title}
        </h3>
        {description && <p className="text-[13px] text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  )
}

/** The chips on top of the sheet: jump to a section; the one in view is marked. */
function SectionNav({ titles, ids }: { titles: Record<SectionId, string>; ids: SectionId[] }) {
  const t = useT()
  const ref = React.useRef<HTMLElement>(null)
  const [current, setCurrent] = React.useState<SectionId>('essential')
  React.useEffect(() => {
    const box = ref.current?.parentElement
    if (!box) return
    const onScroll = () => {
      const top = box.getBoundingClientRect().top + 64
      let cur: SectionId = 'essential'
      for (const el of box.querySelectorAll<HTMLElement>('[data-section]')) if (el.getBoundingClientRect().top <= top) cur = el.dataset.section as SectionId
      // at the very bottom the last section is the one being read
      if (box.scrollTop + box.clientHeight >= box.scrollHeight - 4) cur = ids[ids.length - 1]
      setCurrent(cur)
    }
    box.addEventListener('scroll', onScroll, { passive: true })
    return () => box.removeEventListener('scroll', onScroll)
  }, [ids])
  const go = (id: SectionId) => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    document.getElementById(`ag-sec-${id}`)?.scrollIntoView({ block: 'start', behavior: reduce ? 'auto' : 'smooth' })
    setCurrent(id)
  }
  return (
    <nav ref={ref} aria-label={t('agents.settings.nav')} className="sticky top-0 z-10 -mx-5 flex gap-1 overflow-x-auto border-b bg-popover px-5 py-2" data-testid="agent-settings-nav">
      {ids.map((id) => (
        <button
          key={id}
          type="button"
          onClick={() => go(id)}
          aria-current={current === id ? 'true' : undefined}
          className={cn(
            'h-7 shrink-0 rounded-full px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none max-md:h-10 pointer-coarse:h-10',
            current === id && 'bg-secondary text-foreground',
          )}
        >
          {titles[id]}
        </button>
      ))}
    </nav>
  )
}

/** Technical help folded under "Details". */
function Details({ children, open }: { children: React.ReactNode; open?: boolean }) {
  const t = useT()
  return (
    <details className="group/det" open={open}>
      <summary className="flex w-fit cursor-pointer list-none items-center gap-1 rounded text-xs font-medium text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-3.5 transition-transform group-open/det:rotate-90" /> {t('agents.settings.details')}
      </summary>
      <div className="mt-3 grid gap-3">{children}</div>
    </details>
  )
}

/** It reads text from outside (a mailbox, a feed trigger, a webhook): what it reads may carry orders. */
export const readsOutside = (a: AgentDetail) => !!a.mail?.length || a.triggers.some((x) => x.kind === 'feed') || !!a.webhooks?.length

export function AgentSettings({ agent: a, section }: { agent: AgentDetail; section?: SectionId }) {
  const t = useT()
  const navigate = useNavigate()
  const patch = usePatchAgent()
  // the Save button: a refused rule shows under the rules
  const saver = usePatchAgent({ errorToast: false })
  const del = useDeleteAgent()
  const [d, setD] = React.useState<Draft>(() => draftOf(a))
  const [dirty, setDirty] = React.useState(false)
  const [look, setLook] = React.useState(false)
  // E-mail: only once it has a mailbox, or once asked for one (or opened on it)
  const [mailOpen, setMailOpen] = React.useState(section === 'mail')
  const showMail = mailOpen || !!a.mail?.length
  // Advanced: folded, open when something in it is not the default (or opened on it)
  const custom = !!(a.permission_mode || a.trust_outside || a.allowed_tools.length || a.disallowed_tools.length || a.rules?.length || a.subagent)
  const [advOpen, setAdvOpen] = React.useState(section === 'advanced' || custom)
  React.useEffect(() => {
    if (!dirty) setD(draftOf(a))
  }, [a, dirty])
  // opened on a section: scrolled to it once the sheet is in
  React.useEffect(() => {
    if (!section) return
    if (section === 'mail') setMailOpen(true)
    if (section === 'advanced') setAdvOpen(true)
    const id = setTimeout(() => document.getElementById(`ag-sec-${section}`)?.scrollIntoView({ block: 'start' }), 250)
    return () => clearTimeout(id)
  }, [section])
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => {
    setD((x) => ({ ...x, [k]: v }))
    setDirty(true)
  }
  const save = () =>
    saver.mutate(
      {
        path: a.path,
        model: d.model,
        permission_mode: d.permission,
        allowed_tools: toolsList(d.allowed),
        disallowed_tools: toolsList(d.disallowed),
        limits: d.limits,
        // a rule needs a text; empty rows are dropped
        rules: d.rules.filter((r) => r.match.trim()).map((r) => ({ tool: r.tool, match: r.match.trim(), reason: r.reason.trim() })),
      },
      {
        onSuccess: () => (setDirty(false), toast.success(t('agents.settings.saved'))),
        // a refused rule is shown under the rules; anything else as a toast
        onError: (e) => !(isApiError(e) && e.code === 'bad_rule') && toast.error(errorMessage(e)),
      },
    )
  const ruleError = saver.error && isApiError(saver.error) && saver.error.code === 'bad_rule' ? errorMessage(saver.error) : null
  const titles: Record<SectionId, string> = {
    essential: t('agents.settings.sec.essential'),
    protection: t('agents.settings.sec.protection'),
    mail: t('agents.mail.title'),
    advanced: t('agents.settings.sec.advanced'),
  }
  const ids = React.useMemo(() => SECTIONS.filter((x) => x !== 'mail' || showMail), [showMail])
  const hasTools = a.allowed_tools.length > 0 || a.disallowed_tools.length > 0

  return (
    <>
      <SectionNav titles={titles} ids={ids} />
      <div className="grid max-w-3xl gap-6 pt-4" data-testid="agent-settings">
        <Section id="essential" title={titles.essential}>
          <div className="divide-y">
            <SettingRow label={t('agents.settings.enabled')} description={t('agents.settings.enabledDesc')} htmlFor="ag-enabled">
              <Switch id="ag-enabled" checked={a.enabled} onCheckedChange={(v) => patch.mutate({ path: a.path, enabled: v })} />
            </SettingRow>
            <SettingRow label={t('agents.settings.silent')} description={t('agents.settings.silentDesc')} htmlFor="ag-silent">
              <Switch id="ag-silent" checked={a.silent} onCheckedChange={(v) => patch.mutate({ path: a.path, silent: v })} data-testid="agent-silent-switch" />
            </SettingRow>
            <SettingRow label={t('agents.look.title')} description={t('agents.settings.look')}>
              <Button variant="outline" size="sm" onClick={() => setLook(true)} data-testid="agent-settings-look">
                <Pencil /> {t('agents.create.faceEdit')}
              </Button>
            </SettingRow>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField label={t('agents.field.model')} hint={t('agents.settings.sec.modelDesc')}>
              <ModelSelect id="ag-model" value={d.model} onChange={(v) => set('model', v)} />
            </FormField>
            <LimitsFields value={d.limits} onChange={(l) => set('limits', l)} part="budget" />
          </div>
        </Section>
        <AppearanceDialog agent={a} open={look} onOpenChange={setLook} />

        <Section id="protection" title={titles.protection} description={t('agents.settings.sec.protectionDesc')}>
          <SandboxFields agent={a} />
          <div className="divide-y border-t">
            <SettingRow label={t('agents.settings.approvals')} description={t('agents.settings.approvalsDesc')} htmlFor="ag-approvals">
              <Switch id="ag-approvals" checked={a.approvals} onCheckedChange={(v) => patch.mutate({ path: a.path, approvals: v })} data-testid="agent-approvals" />
            </SettingRow>
            <AgentKeys agent={a} />
          </div>
        </Section>

        {showMail ? (
          <Section id="mail" title={titles.mail} description={t('agents.mail.desc')}>
            <AgentMail agent={a} />
          </Section>
        ) : (
          <div className="border-t pt-6">
            <Button variant="outline" size="sm" onClick={() => setMailOpen(true)} data-testid="agent-mail-add">
              <Mail /> {t('agents.settings.mailAdd')}
            </Button>
          </div>
        )}

        <section id="ag-sec-advanced" data-section="advanced" className="grid scroll-mt-14 grid-cols-[minmax(0,1fr)] gap-4 border-t pt-6" data-testid="agent-advanced-settings">
          <button
            type="button"
            onClick={() => setAdvOpen((x) => !x)}
            aria-expanded={advOpen}
            className="flex w-fit items-center gap-1.5 rounded text-[15px] font-semibold tracking-tight focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            data-testid="agent-advanced-toggle"
          >
            <ChevronRight className={cn('size-4 transition-transform', advOpen && 'rotate-90')} /> {titles.advanced}
          </button>
          {!advOpen && <p className="-mt-2 text-[13px] text-muted-foreground">{t('agents.settings.sec.advancedDesc')}</p>}
          {advOpen && (
            <div className="grid gap-6">
              <h4 className="-mb-3 text-xs font-medium tracking-wide text-muted-foreground uppercase">{t('agents.settings.grp.permissions')}</h4>
              <FormField label={t('agents.field.permission')} hint={a.sandbox ? t('agents.sandbox.permissionHint') : t('agents.field.permissionHint')}>
                <PermissionSelect value={d.permission} onChange={(v) => set('permission', v)} />
              </FormField>
              <div className="divide-y">
                <SettingRow label={t('agents.settings.trustOutside')} description={t('agents.settings.trustOutsideDesc')} htmlFor="ag-trust">
                  <Switch id="ag-trust" checked={a.trust_outside} onCheckedChange={(v) => patch.mutate({ path: a.path, trust_outside: v })} data-testid="agent-trust-outside" />
                </SettingRow>
                {a.trust_outside && !a.approvals && <p className="py-3 text-xs text-warning">{t('agents.settings.trustOutsideWarn')}</p>}
                <SettingRow label={t('agents.settings.subagent')} description={t('agents.settings.subagentDesc')} htmlFor="ag-subagent">
                  <Switch id="ag-subagent" checked={a.subagent} onCheckedChange={(v) => patch.mutate({ path: a.path, subagent: v })} data-testid="agent-subagent" />
                </SettingRow>
              </div>
              <h4 className="-mb-3 text-xs font-medium tracking-wide text-muted-foreground uppercase">{t('agents.settings.grp.tools')}</h4>
              <div className="grid gap-1">
                <span className="text-sm font-medium">{t('agents.settings.tools')}</span>
                <span className="text-[13px] text-muted-foreground">{t('agents.settings.toolsDesc')}</span>
                <Details open={hasTools}>
                  <FormField label={t('agents.settings.allowed')} hint={t('agents.settings.allowedHint')}>
                    <Textarea minRows={3} maxRows={10} value={d.allowed} onChange={(e) => set('allowed', e.target.value)} className="font-mono text-[13px]" placeholder="Read&#10;Grep&#10;Bash(git status:*)" />
                  </FormField>
                  <FormField label={t('agents.settings.disallowed')} hint={t('agents.settings.disallowedHint')}>
                    <Textarea minRows={3} maxRows={10} value={d.disallowed} onChange={(e) => set('disallowed', e.target.value)} className="font-mono text-[13px]" placeholder="WebFetch&#10;Bash(rm:*)" />
                  </FormField>
                </Details>
              </div>
              <div className="grid gap-3">
                <div className="grid gap-0.5">
                  <span className="text-sm font-medium">{t('agents.rules.title')}</span>
                  <span className="text-[13px] text-muted-foreground">{t('agents.rules.desc')}</span>
                </div>
                <RulesEditor value={d.rules} onChange={(r) => set('rules', r)} error={ruleError} />
              </div>
              <h4 className="-mb-3 text-xs font-medium tracking-wide text-muted-foreground uppercase">{t('agents.settings.grp.limits')}</h4>
              <div className="grid gap-3">
                <div className="grid gap-0.5">
                  <span className="text-sm font-medium">{t('agents.settings.sec.limits')}</span>
                  <span className="text-[13px] text-muted-foreground">{t('agents.limits.desc')}</span>
                </div>
                <LimitsFields value={d.limits} onChange={(l) => set('limits', l)} part="rest" />
              </div>
              <div className="divide-y">
                <SettingRow label={t('agents.export.button')} description={t('agents.export.tip')}>
                  <Button asChild variant="outline" size="sm">
                    <a href={agentExportUrl(a.path)} download={`${a.name}.md`} data-testid="agent-export">
                      <Download /> {t('agents.export.download')}
                    </a>
                  </Button>
                </SettingRow>
                <p className="pt-4 text-xs text-muted-foreground">{t('agents.settings.importHint')}</p>
              </div>
            </div>
          )}
        </section>

        <div className="sticky bottom-[calc(var(--safe-bottom)+0.5rem)] z-10 flex justify-end gap-2 empty:hidden">
          {dirty && (
            <div className="flex gap-2 rounded-xl border bg-popover p-2 shadow-pop animate-in">
              <Button variant="ghost" onClick={() => (setD(draftOf(a)), setDirty(false))}>
                {t('common.cancel')}
              </Button>
              <Button loading={saver.isPending} onClick={save} data-testid="agent-settings-save">
                {t('common.save')}
              </Button>
            </div>
          )}
        </div>

        <SettingsCard title={t('agents.settings.danger')} danger>
          <SettingRow label={t('agents.settings.delete')} description={t('agents.settings.deleteDesc')}>
            <Button
              variant="destructive"
              loading={del.isPending}
              onClick={async () => {
                const ok = await confirm({
                  title: t('agents.settings.deleteTitle', { name: a.display_name }),
                  description: t('agents.settings.deleteDesc'),
                  destructive: true,
                  confirmText: t('common.delete'),
                  typeToConfirm: a.name,
                })
                if (ok) del.mutate(a.path, { onSuccess: () => (toast.success(t('agents.settings.deleted')), navigate('/agents')) })
              }}
              data-testid="agent-delete"
            >
              <Trash2 /> {t('common.delete')}
            </Button>
          </SettingRow>
        </SettingsCard>
      </div>
    </>
  )
}

/** The Keys vault entries the agent's runs get as environment variables: none until checked here. */
function AgentKeys({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  const patch = usePatchAgent()
  return (
    <div className="grid gap-2 py-3" data-testid="agent-keys">
      <div className="grid gap-0.5">
        <span className="text-sm font-medium">{t('agents.settings.keys')}</span>
        <span className="text-xs text-muted-foreground">{t('agents.settings.keysDesc')}</span>
      </div>
      <KeyChecks value={a.keys} onChange={(keys) => patch.mutate({ path: a.path, keys })} />
    </div>
  )
}

/** Free (no sandbox, like a session) or Protected (its sandbox); protected: the hosts its commands may reach and the
 *  folders of the topic it may write in. Free while it reads outside text: Protected is advised. */
function SandboxFields({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  const patch = usePatchAgent({ errorToast: false })
  // the field the last refusal belongs to (bad_domain / bad_path), shown under it
  const [err, setErr] = React.useState<{ field: 'domains' | 'writable'; text: string } | null>(null)
  const save = (field: 'domains' | 'writable', list: string[], saved?: () => void) =>
    patch.mutate(
      { path: a.path, [field]: list },
      {
        onSuccess: () => (setErr(null), saved?.()),
        onError: (e) => (isApiError(e) && (e.code === 'bad_domain' || e.code === 'bad_path') ? setErr({ field, text: errorMessage(e) }) : toast.error(errorMessage(e))),
      },
    )
  const setBox = (v: boolean) => v !== a.sandbox && patch.mutate({ path: a.path, sandbox: v }, { onError: (e) => toast.error(errorMessage(e)) })
  const Choice = ({ on, icon: Icon, title, desc, id }: { on: boolean; icon: typeof Lock; title: string; desc: string; id: string }) => (
    <button
      type="button"
      role="radio"
      aria-checked={a.sandbox === on}
      onClick={() => setBox(on)}
      className={cn(
        'flex items-start gap-3 rounded-xl border bg-card p-3 text-left transition-colors hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
        a.sandbox === on && 'border-primary bg-primary/5 hover:bg-primary/5',
      )}
      data-testid={id}
    >
      <Icon className={cn('mt-0.5 size-5 shrink-0', a.sandbox === on ? 'text-primary' : 'text-muted-foreground')} />
      <span className="grid min-w-0 gap-0.5">
        <span className="text-sm font-medium">{title}</span>
        <span className="text-xs text-muted-foreground">{desc}</span>
      </span>
    </button>
  )
  return (
    <div className="grid gap-4" data-testid="agent-sandbox">
      <div role="radiogroup" aria-label={t('agents.settings.sec.protection')} className="grid gap-2 sm:grid-cols-2">
        <Choice on={false} icon={Unlock} title={t('agents.protect.free')} desc={t('agents.protect.freeDesc')} id="agent-protect-free" />
        <Choice on icon={Lock} title={t('agents.protect.box')} desc={t('agents.protect.boxDesc')} id="agent-sandbox-toggle" />
      </div>
      {!a.sandbox && readsOutside(a) && (
        <p className="flex items-start gap-1.5 text-xs text-warning" data-testid="agent-protect-advice">
          <AlertTriangle className="mt-px size-3.5 shrink-0" /> {t('agents.protect.advice')}
        </p>
      )}
      {a.sandbox && (
        <>
          <Details>
            <div className="grid gap-2 text-xs text-muted-foreground" data-testid="agent-sandbox-help">
              <p>{t('agents.sandbox.desc')}</p>
              <p>{t('agents.sandbox.whenOff')}</p>
            </div>
          </Details>
          <div className="grid gap-2">
            <div className="grid gap-0.5">
              <span className="text-sm font-medium">{t('agents.sandbox.domains')}</span>
              <span className="text-xs text-muted-foreground">{t('agents.sandbox.domainsDesc')}</span>
            </div>
            <ListEditor
              value={a.domains || []}
              onChange={(l, saved) => save('domains', l, saved)}
              placeholder="api.github.com, *.example.com"
              empty={t('agents.sandbox.domainsNone')}
              error={err?.field === 'domains' ? err.text : null}
              testid="agent-domains"
            />
          </div>
          <div className="grid gap-2">
            <div className="grid gap-0.5">
              <span className="text-sm font-medium">{t('agents.sandbox.writable')}</span>
              <span className="text-xs text-muted-foreground">{t('agents.sandbox.writableDesc')}</span>
            </div>
            <ListEditor
              value={a.writable || []}
              onChange={(l, saved) => save('writable', l, saved)}
              placeholder={t('agents.sandbox.writablePlaceholder')}
              empty={t('agents.sandbox.writableNone')}
              error={err?.field === 'writable' ? err.text : null}
              testid="agent-writable"
            />
          </div>
        </>
      )}
    </div>
  )
}

/** A short list of strings as chips (x to remove) and a field to add one (Enter or the + button; commas split). The
 *  field keeps what was typed until the server took it (`saved`). */
export function ListEditor({ value, onChange, placeholder, empty, error, testid }: { value: string[]; onChange: (l: string[], saved?: () => void) => void; placeholder: string; empty: string; error: string | null; testid: string }) {
  const t = useT()
  const [v, setV] = React.useState('')
  const add = () => {
    const items = v.split(/[\s,]+/).map((x) => x.trim()).filter((x) => x && !value.includes(x))
    if (!items.length) return setV('')
    onChange([...value, ...items], () => setV(''))
  }
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-2" data-testid={testid}>
      {value.length ? (
        <ul className="flex flex-wrap gap-1.5">
          {value.map((x) => (
            <li key={x} className="flex max-w-full min-w-0 items-center gap-1 rounded-md bg-secondary py-0.5 pr-0.5 pl-2 font-mono text-[12px]">
              <span className="truncate">
                <Sensitive length={8}>{x}</Sensitive>
              </span>
              <button
                type="button"
                onClick={() => onChange(value.filter((y) => y !== x))}
                className="relative grid size-5 place-items-center rounded text-muted-foreground hover:bg-accent hover:text-foreground before:absolute before:-inset-2.5 before:content-['']"
                aria-label={t('agents.list.remove', { name: x })}
              >
                <X className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground italic">{empty}</p>
      )}
      <div className="flex gap-2">
        <Input
          value={v}
          onChange={(e) => setV(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
          placeholder={placeholder}
          aria-invalid={!!error || undefined}
          className="h-8 font-mono text-[13px]"
        />
        <Button type="button" size="sm" variant="outline" onClick={add} disabled={!v.trim()} aria-label={t('common.add')}>
          <Plus />
        </Button>
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}

const RULE_TOOLS: AgentRuleTool[] = ['Bash', 'Write', 'Edit', 'WebFetch', '*']
const MAX_RULES = 20

/** "Refuse <tool> when it contains <text> - reason shown to Claude" (saved with the other settings). */
function RulesEditor({ value, onChange, error }: { value: AgentRule[]; onChange: (r: AgentRule[]) => void; error: string | null }) {
  const t = useT()
  const set = (i: number, r: Partial<AgentRule>) => onChange(value.map((x, j) => (j === i ? { ...x, ...r } : x)))
  return (
    <div className="grid gap-3" data-testid="agent-rules">
      {!value.length && <p className="text-xs text-muted-foreground italic">{t('agents.rules.none')}</p>}
      {value.map((r, i) => (
        <div key={i} className="grid gap-2 rounded-lg border p-2.5" data-testid="agent-rule">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span>{t('agents.rules.refuse')}</span>
            <Select
              value={r.tool}
              onValueChange={(v) => set(i, { tool: v as AgentRuleTool })}
              className="h-8 w-32"
              aria-label={t('agents.rules.tool')}
              options={RULE_TOOLS.map((x) => ({ value: x, label: x === '*' ? t('agents.rules.anyTool') : x }))}
            />
            <span>{t('agents.rules.contains')}</span>
            <Input value={r.match} onChange={(e) => set(i, { match: e.target.value })} placeholder={t('agents.rules.matchPlaceholder')} className="h-8 min-w-40 flex-1 font-mono text-[13px]" aria-label={t('agents.rules.match')} />
            <Button type="button" variant="ghost" size="icon-sm" onClick={() => onChange(value.filter((_, j) => j !== i))} aria-label={t('agents.rules.remove')}>
              <Trash2 />
            </Button>
          </div>
          <Input value={r.reason} onChange={(e) => set(i, { reason: e.target.value })} placeholder={t('agents.rules.reasonPlaceholder')} className="h-8 text-[13px]" aria-label={t('agents.rules.reason')} />
        </div>
      ))}
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div>
        <Button type="button" size="sm" variant="outline" disabled={value.length >= MAX_RULES} onClick={() => onChange([...value, { tool: 'Bash', match: '', reason: '' }])} data-testid="agent-rule-add">
          <Plus /> {t('agents.rules.add')}
        </Button>
      </div>
    </div>
  )
}
