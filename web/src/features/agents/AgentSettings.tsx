// An agent's settings: on/off, safety (approvals, outside events, keys), model, permission mode, tools, guards,
// face, delete.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Trash2 } from 'lucide-react'
import { useT } from '@/i18n'
import { useDeleteAgent, usePatchAgent } from '@/lib/queries'
import type { AgentAvatar, AgentDetail, AgentLimits, PermissionMode } from '@/lib/types'
import { Button, confirm, FormField, Input, Switch, Textarea, toast } from '@/components/ui'
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

type Draft = { display: string; model: string; permission: '' | PermissionMode; allowed: string; disallowed: string; limits: AgentLimits; avatar: AgentAvatar }
const draftOf = (a: AgentDetail): Draft => ({
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
    patch.mutate(
      {
        path: a.path,
        display_name: d.display.trim() || a.name,
        model: d.model,
        permission_mode: d.permission,
        allowed_tools: toolsList(d.allowed),
        disallowed_tools: toolsList(d.disallowed),
        limits: d.limits,
        avatar: d.avatar,
      },
      { onSuccess: () => (setDirty(false), toast.success(t('agents.settings.saved'))) },
    )

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

      <SettingsCard title={t('agents.settings.identity')}>
        <div className="grid gap-4">
          <FormField label={t('agents.create.name')} hint={t('agents.settings.folder', { name: a.name })}>
            <Input value={d.display} maxLength={60} onChange={(e) => set('display', e.target.value)} />
          </FormField>
          <AvatarEditor value={d.avatar} onChange={(v) => set('avatar', v)} />
        </div>
      </SettingsCard>

      <SettingsCard title={t('agents.settings.claude')}>
        <div className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField label={t('agents.field.model')}>
              <ModelSelect value={d.model} onChange={(v) => set('model', v)} />
            </FormField>
            <FormField label={t('agents.field.permission')} hint={t('agents.field.permissionHint')}>
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
            <Button loading={patch.isPending} onClick={save} data-testid="agent-settings-save">
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
