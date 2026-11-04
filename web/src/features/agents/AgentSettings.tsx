// An agent's settings: on/off, safety (approvals, outside events, keys), sandbox (domains, writable folders),
// rules, model, permission mode, tools, subagent, guards, face, delete.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Plus, Trash2, X } from 'lucide-react'
import { useT } from '@/i18n'
import { errorMessage, isApiError } from '@/lib/api'
import { useDeleteAgent, usePatchAgent } from '@/lib/queries'
import type { AgentAvatar, AgentDetail, AgentLimits, AgentRule, AgentRuleTool, PermissionMode } from '@/lib/types'
import { Button, confirm, FormField, Input, Select, Sensitive, Switch, Textarea, toast } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { SettingsCard } from '@/pages/settings/sections/ui'
import { AvatarEditor } from './AvatarEditor'
import { KeyChecks, LimitsFields, ModelSelect, PermissionSelect } from './parts'

const toolsText = (l: string[]) => l.join('\n')
const toolsList = (s: string) =>
  s
    .split(/[\n,]+/)
    .map((x) => x.trim())
    .filter(Boolean)

type Draft = { display: string; model: string; permission: '' | PermissionMode; allowed: string; disallowed: string; limits: AgentLimits; avatar: AgentAvatar; rules: AgentRule[] }
const draftOf = (a: AgentDetail): Draft => ({
  rules: (a.rules || []).map((r) => ({ ...r, reason: r.reason || '' })),
  display: a.display_name,
  model: a.model,
  permission: a.permission_mode,
  allowed: toolsText(a.allowed_tools),
  disallowed: toolsText(a.disallowed_tools),
  limits: { ...a.limits },
  avatar: { ...a.avatar },
})

export function AgentSettings({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  const navigate = useNavigate()
  const patch = usePatchAgent()
  // the Save button: a refused rule shows under the rules
  const saver = usePatchAgent({ errorToast: false })
  const del = useDeleteAgent()
  const [d, setD] = React.useState<Draft>(() => draftOf(a))
  const [dirty, setDirty] = React.useState(false)
  React.useEffect(() => {
    if (!dirty) setD(draftOf(a))
  }, [a, dirty])
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => {
    setD((x) => ({ ...x, [k]: v }))
    setDirty(true)
  }
  const save = () =>
    saver.mutate(
      {
        path: a.path,
        display_name: d.display.trim() || a.name,
        model: d.model,
        permission_mode: d.permission,
        allowed_tools: toolsList(d.allowed),
        disallowed_tools: toolsList(d.disallowed),
        limits: d.limits,
        avatar: d.avatar,
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

  return (
    <div className="grid max-w-3xl gap-6">
      <SettingsCard title={t('agents.settings.general')}>
        <div className="divide-y">
          <SettingRow label={t('agents.settings.enabled')} description={t('agents.settings.enabledDesc')} htmlFor="ag-enabled">
            <Switch id="ag-enabled" checked={a.enabled} onCheckedChange={(v) => patch.mutate({ path: a.path, enabled: v })} />
          </SettingRow>
        </div>
      </SettingsCard>

      <SettingsCard title={t('agents.settings.safety')} description={t('agents.settings.safetyDesc')}>
        <div className="divide-y">
          <SettingRow label={t('agents.settings.approvals')} description={t('agents.settings.approvalsDesc')} htmlFor="ag-approvals">
            <Switch id="ag-approvals" checked={a.approvals} onCheckedChange={(v) => patch.mutate({ path: a.path, approvals: v })} data-testid="agent-approvals" />
          </SettingRow>
          <SettingRow label={t('agents.settings.trustOutside')} description={t('agents.settings.trustOutsideDesc')} htmlFor="ag-trust">
            <Switch id="ag-trust" checked={a.trust_outside} onCheckedChange={(v) => patch.mutate({ path: a.path, trust_outside: v })} data-testid="agent-trust-outside" />
          </SettingRow>
          {a.trust_outside && !a.approvals && <p className="py-3 text-xs text-warning">{t('agents.settings.trustOutsideWarn')}</p>}
          <AgentKeys agent={a} />
        </div>
      </SettingsCard>

      <SandboxCard agent={a} />

      <SettingsCard title={t('agents.rules.title')} description={t('agents.rules.desc')}>
        <RulesEditor value={d.rules} onChange={(r) => set('rules', r)} error={ruleError} />
      </SettingsCard>

      <SettingsCard title={t('agents.settings.identity')}>
        <div className="grid gap-4">
          <FormField label={t('agents.create.name')} hint={t('agents.settings.folder', { name: a.name })}>
            <Input value={d.display} maxLength={60} onChange={(e) => set('display', e.target.value)} />
          </FormField>
          <AvatarEditor value={d.avatar} onChange={(v) => set('avatar', v)} project={a.project} />
        </div>
      </SettingsCard>

      <SettingsCard title={t('agents.settings.claude')}>
        <div className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField label={t('agents.field.model')}>
              <ModelSelect value={d.model} onChange={(v) => set('model', v)} />
            </FormField>
            <FormField label={t('agents.field.permission')} hint={a.sandbox ? t('agents.sandbox.permissionHint') : t('agents.field.permissionHint')}>
              <PermissionSelect value={d.permission} onChange={(v) => set('permission', v)} />
            </FormField>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField label={t('agents.settings.allowed')} hint={t('agents.settings.allowedHint')}>
              <Textarea minRows={3} maxRows={10} value={d.allowed} onChange={(e) => set('allowed', e.target.value)} className="font-mono text-[13px]" placeholder="Read&#10;Grep&#10;Bash(git status:*)" />
            </FormField>
            <FormField label={t('agents.settings.disallowed')} hint={t('agents.settings.disallowedHint')}>
              <Textarea minRows={3} maxRows={10} value={d.disallowed} onChange={(e) => set('disallowed', e.target.value)} className="font-mono text-[13px]" placeholder="WebFetch&#10;Bash(rm:*)" />
            </FormField>
          </div>
          <SettingRow label={t('agents.settings.subagent')} description={t('agents.settings.subagentDesc')} htmlFor="ag-subagent" className="border-t pt-4 first:pt-4">
            <Switch id="ag-subagent" checked={a.subagent} onCheckedChange={(v) => patch.mutate({ path: a.path, subagent: v })} data-testid="agent-subagent" />
          </SettingRow>
        </div>
      </SettingsCard>

      <SettingsCard title={t('agents.limits.title')} description={t('agents.limits.desc')}>
        <LimitsFields value={d.limits} onChange={(l) => set('limits', l)} />
      </SettingsCard>

      <div className="sticky bottom-[calc(var(--safe-bottom)+0.5rem)] z-10 flex justify-end gap-2">
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

/** The sandbox: on/off, the hosts its commands may reach, the folders of the topic it may write in. */
function SandboxCard({ agent: a }: { agent: AgentDetail }) {
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
  return (
    <SettingsCard title={t('agents.sandbox.title')} description={t('agents.sandbox.desc')}>
      <div className="divide-y" data-testid="agent-sandbox">
        <SettingRow label={t('agents.sandbox.toggle')} description={t('agents.sandbox.toggleDesc')} htmlFor="ag-sandbox">
          <Switch
            id="ag-sandbox"
            checked={a.sandbox}
            onCheckedChange={(v) => patch.mutate({ path: a.path, sandbox: v }, { onError: (e) => toast.error(errorMessage(e)) })}
            data-testid="agent-sandbox-toggle"
          />
        </SettingRow>
        {!a.sandbox && <p className="py-3 text-xs text-warning">{t('agents.sandbox.offWarn')}</p>}
        <div className="grid gap-2 py-4">
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
        <div className="grid gap-2 py-4 last:pb-0">
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
      </div>
    </SettingsCard>
  )
}

/** A short list of strings as chips (x to remove) and a field to add one (Enter or the + button; commas split). The
 *  field keeps what was typed until the server took it (`saved`). */
function ListEditor({ value, onChange, placeholder, empty, error, testid }: { value: string[]; onChange: (l: string[], saved?: () => void) => void; placeholder: string; empty: string; error: string | null; testid: string }) {
  const t = useT()
  const [v, setV] = React.useState('')
  const add = () => {
    const items = v.split(/[\s,]+/).map((x) => x.trim()).filter((x) => x && !value.includes(x))
    if (!items.length) return setV('')
    onChange([...value, ...items], () => setV(''))
  }
  return (
    <div className="grid gap-2" data-testid={testid}>
      {value.length ? (
        <ul className="flex flex-wrap gap-1.5">
          {value.map((x) => (
            <li key={x} className="flex min-w-0 items-center gap-1 rounded-md bg-secondary py-0.5 pr-0.5 pl-2 font-mono text-[12px]">
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
