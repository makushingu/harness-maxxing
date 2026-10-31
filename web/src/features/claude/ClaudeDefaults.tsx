import { ShieldAlert, ShieldCheck, ShieldHalf } from 'lucide-react'
import { useClaudeSettings, useClaudeStatus } from '@/lib/queries'
import type { PermissionMode } from '@/lib/types'
import { useLang, useT } from '@/i18n'
import { fmtDate } from '@/lib/format'
import { Badge, FormField, Select, Skeleton, Switch } from '@/components/ui'
import { OptionCard, SettingRow } from '../common'

const CLI_DEFAULT = '__cli_default__'
/** Automatic compaction thresholds offered (tokens of context at the end of a turn); 0 = off. */
const COMPACT_AT = [0, 200_000, 300_000, 400_000, 600_000, 800_000]
/** Idle compaction thresholds offered (context of a session you come back to after its cache expired); 0 = off. */
const IDLE_AT = [0, 40_000, 60_000, 100_000, 200_000]
/** Smart resume thresholds offered (context from which a return after a pause is sorted: new subject or follow-up); 0 = off. */
const SMART_AT = [0, 40_000, 60_000, 100_000, 200_000]

/** Default model + permission mode (saved immediately). */
export function ClaudeDefaults() {
  const t = useT()
  const lang = useLang()
  const { data: s } = useClaudeStatus()
  const save = useClaudeSettings()
  if (!s)
    return (
      <div className="grid gap-4">
        <Skeleton className="h-16" />
        <Skeleton className="h-48" />
      </div>
    )
  const models = s.models.filter((m) => m.id)
  if (s.default_model && !models.some((m) => m.id === s.default_model)) models.unshift({ id: s.default_model, label: s.default_model })
  const modes: { id: PermissionMode; icon: typeof ShieldAlert; title: string; desc: string; badge?: string }[] = [
    { id: 'bypass', icon: ShieldAlert, title: t('claude.mode.bypass'), desc: t('claude.mode.bypassDesc'), badge: t('claude.mode.recommendedVps') },
    { id: 'acceptEdits', icon: ShieldHalf, title: t('claude.mode.acceptEdits'), desc: t('claude.mode.acceptEditsDesc') },
    { id: 'default', icon: ShieldCheck, title: t('claude.mode.default'), desc: t('claude.mode.defaultDesc') },
  ]
  return (
    <div className="grid gap-6">
      <FormField label={t('cdef.defaultModel')} hint={t('cdef.defaultModelHint')}>
        <Select
          value={s.default_model || CLI_DEFAULT}
          onValueChange={(v) => save.mutate({ default_model: v === CLI_DEFAULT ? '' : v })}
          options={[{ value: CLI_DEFAULT, label: t('cdef.cliDefault') }, ...models.map((m) => ({ value: m.id, label: m.label || m.id }))]}
          disabled={save.isPending}
          className="sm:max-w-sm"
        />
      </FormField>
      <FormField label={t('cdef.autoCompact')} hint={t('cdef.autoCompactHint')}>
        <Select
          value={String(s.auto_compact_tokens ?? 0)}
          onValueChange={(v) => save.mutate({ auto_compact_tokens: Number(v) })}
          options={[
            ...COMPACT_AT.map((n) => ({
              value: String(n),
              label: n === 0 ? t('cdef.autoCompactOff') : `${n / 1000}k${n === 400_000 ? ` · ${t('cdef.autoCompactRecommended')}` : ''}`,
            })),
            ...(COMPACT_AT.includes(s.auto_compact_tokens) ? [] : [{ value: String(s.auto_compact_tokens), label: `${Math.round(s.auto_compact_tokens / 1000)}k` }]),
          ]}
          className="sm:max-w-sm"
          data-testid="auto-compact"
        />
      </FormField>
      <div data-tour="idle-compact">
        <FormField label={t('cdef.idleCompact')} hint={t('cdef.idleCompactHint')}>
          <Select
            value={String(s.idle_compact_tokens ?? 0)}
            onValueChange={(v) => save.mutate({ idle_compact_tokens: Number(v) })}
            options={[
              ...IDLE_AT.map((n) => ({
                value: String(n),
                label: n === 0 ? t('cdef.autoCompactOff') : `${n / 1000}k${n === 60_000 ? ` · ${t('cdef.autoCompactRecommended')}` : ''}`,
              })),
              ...(IDLE_AT.includes(s.idle_compact_tokens) ? [] : [{ value: String(s.idle_compact_tokens), label: `${Math.round(s.idle_compact_tokens / 1000)}k` }]),
            ]}
            className="sm:max-w-sm"
            data-testid="idle-compact"
          />
        </FormField>
      </div>
      <FormField label={t('cdef.smartResume')} hint={t('cdef.smartResumeHint')}>
        <Select
          value={String(s.smart_resume_tokens ?? 0)}
          onValueChange={(v) => save.mutate({ smart_resume_tokens: Number(v) })}
          options={[
            ...SMART_AT.map((n) => ({
              value: String(n),
              label: n === 0 ? t('cdef.autoCompactOff') : `${n / 1000}k${n === 60_000 ? ` · ${t('cdef.autoCompactRecommended')}` : ''}`,
            })),
            ...(SMART_AT.includes(s.smart_resume_tokens) ? [] : [{ value: String(s.smart_resume_tokens), label: `${Math.round(s.smart_resume_tokens / 1000)}k` }]),
          ]}
          className="sm:max-w-sm"
          data-testid="smart-resume"
        />
      </FormField>
      <SettingRow label={t('cdef.protectSecrets')} description={t('cdef.protectSecretsHint')} htmlFor="mx-protect-secrets">
        <Switch id="mx-protect-secrets" checked={s.protect_secrets ?? true} onCheckedChange={(v) => save.mutate({ protect_secrets: v })} />
      </SettingRow>
      <SettingRow label={t('cdef.shortTitles')} description={t('cdef.shortTitlesHint')} htmlFor="mx-short-titles">
        <Switch id="mx-short-titles" checked={s.short_titles ?? true} onCheckedChange={(v) => save.mutate({ short_titles: v })} />
      </SettingRow>
      {(s.short_titles ?? true) && (
        <SettingRow label={t('cdef.shortTitlesModel')} description={t('cdef.shortTitlesModelHint')} htmlFor="mx-short-titles-model">
          <Switch id="mx-short-titles-model" checked={!!s.short_titles_model} onCheckedChange={(v) => save.mutate({ short_titles_model: v })} />
        </SettingRow>
      )}
      <div data-tour="claude-auto-update" className="rounded-md">
        <SettingRow
          label={t('cdef.autoUpdate')}
          description={
            <>
              {t('cdef.autoUpdateHint')}
              {s.auto_update?.last && (
                <span className={`mt-1 block ${s.auto_update.last.ok ? '' : 'text-destructive'}`} data-testid="claude-last-update">
                  {t(s.auto_update.last.ok ? 'cdef.autoUpdateLast' : 'cdef.autoUpdateFailed', {
                    from: s.auto_update.last.from,
                    to: s.auto_update.last.to,
                    date: fmtDate(s.auto_update.last.at, lang),
                  })}
                  {!s.auto_update.last.ok && s.auto_update.last.error ? ` - ${s.auto_update.last.error}` : ''}
                </span>
              )}
            </>
          }
          htmlFor="mx-claude-auto-update"
          className="py-4 first:pt-4 last:pb-4"
        >
          <Switch id="mx-claude-auto-update" checked={s.auto_update?.enabled ?? false} onCheckedChange={(v) => save.mutate({ claude_auto_update: v })} />
        </SettingRow>
      </div>
      <fieldset className="grid gap-2">
        <legend className="mb-2 text-sm font-medium">{t('claude.permissionMode')}</legend>
        <div className="grid gap-2" role="radiogroup">
          {modes.map((m) => (
            <OptionCard
              key={m.id}
              name="permission-mode"
              value={m.id}
              selected={s.permission_mode === m.id}
              onSelect={() => save.mutate({ permission_mode: m.id })}
              icon={m.icon}
              title={m.title}
              description={m.desc}
              badge={m.badge ? <Badge variant="warning">{m.badge}</Badge> : undefined}
            />
          ))}
        </div>
        <p className="mt-1 text-[13px] text-muted-foreground">{t('claude.mode.note')}</p>
      </fieldset>
    </div>
  )
}
