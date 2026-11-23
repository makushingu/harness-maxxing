// Settings -> Feed: the notifications feed's sources (built-in, scripts, webhooks) and their Telegram rule, the
// copy to Telegram and the server problems. Webhooks themselves (URL, secret, test, delete) are on Settings ->
// Webhooks: a source that comes from one links there.
import { Link } from 'react-router'
import { Webhook } from 'lucide-react'
import { useFeedSettings, useSaveFeedSettings } from '@/lib/queries'
import type { FeedHook, FeedHookKind, FeedRule, FeedSource } from '@/lib/types'
import { useT, type TKey } from '@/i18n'
import { Badge, Select, Skeleton, Switch } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { SettingsCard } from '@/pages/settings/sections/ui'

const KIND_LABEL: Record<FeedHookKind, string> = { stripe: 'Stripe', shopify: 'Shopify', github: 'GitHub', generic: 'JSON' }

export function FeedSettingsCards() {
  const t = useT()
  const { data, isPending } = useFeedSettings()
  const save = useSaveFeedSettings()
  const ruleOptions = (data?.rules || ['auto', 'off', 'silent', 'loud']).map((r) => ({ value: r, label: t(`feed.rule.${r}` as TKey) }))
  const setRule = (source: string, rule: FeedRule) => save.mutate({ rules: { [source]: rule } })
  const hookOf = (name: string) => data?.hooks.find((h) => h.name === name)

  return (
    <div className="grid gap-6">
      <SettingsCard title={t('feed.settingsTitle')} description={t('feed.settingsDesc')}>
        <SettingRow label={t('feed.telegram')} description={t('feed.telegramDesc')} htmlFor="mx-feed-tg">
          <Switch id="mx-feed-tg" checked={data?.telegram ?? true} disabled={!data} onCheckedChange={(v) => save.mutate({ telegram: v })} />
        </SettingRow>
        <SettingRow label={t('feed.health')} description={t('feed.healthDesc')} htmlFor="mx-feed-health">
          <Switch id="mx-feed-health" checked={data?.health ?? false} disabled={!data} onCheckedChange={(v) => save.mutate({ health: v })} />
        </SettingRow>
      </SettingsCard>
      <SettingsCard title={t('feed.sources')} description={t('feed.sourcesDesc')}>
        {isPending || !data ? (
          <div className="grid gap-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : (
          <div className="divide-y" data-testid="feed-sources">
            {data.sources.map((s) => (
              <SourceRow key={s.source} s={s} hook={hookOf(s.source)} ruleOptions={ruleOptions} onRule={(r) => setRule(s.source, r)} />
            ))}
          </div>
        )}
        <p className="mt-3 text-xs text-muted-foreground">{t('feed.cliHint')}</p>
        <p className="mt-1.5 text-xs text-muted-foreground">
          {t('webhooks.feedLink')}{' '}
          <Link to="/settings/webhooks" className="font-medium text-primary underline-offset-4 hover:underline">
            {t('webhooks.feedLinkTo')}
          </Link>
        </p>
      </SettingsCard>
    </div>
  )
}

function SourceRow({ s, hook, ruleOptions, onRule }: { s: FeedSource; hook?: FeedHook; ruleOptions: { value: string; label: string }[]; onRule: (r: FeedRule) => void }) {
  const t = useT()
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5" data-testid="feed-source" data-source={s.source}>
      <div className="grid min-w-0 flex-1 basis-40 gap-0.5">
        <span className="flex min-w-0 items-center gap-2 text-sm font-medium">
          {hook && <Webhook className="size-3.5 shrink-0 text-muted-foreground" />}
          <span className="truncate">{s.label}</span>
          <Badge variant="muted" className="shrink-0">{hook ? KIND_LABEL[hook.kind] : s.builtin ? t('feed.builtin') : t('feed.script')}</Badge>
        </span>
        {hook ? (
          <Link to="/settings/webhooks" className="w-fit text-xs text-primary underline-offset-4 hover:underline pointer-coarse:py-1">
            {t('feed.byWebhook')}
          </Link>
        ) : (
          s.own_thread && <span className="text-xs text-muted-foreground">{t('feed.ownThread')}</span>
        )}
      </div>
      <Select value={s.rule} onValueChange={(v) => onRule(v as FeedRule)} options={ruleOptions} aria-label={t('feed.ruleLabel', { source: s.label })} className="w-44" />
    </div>
  )
}
