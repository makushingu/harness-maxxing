// Settings -> Notifications: the feed's sources (built-in + webhooks), their Telegram rule, and webhooks
// management (add with the right URL and signing secret per service, test, new URL, delete).
import * as React from 'react'
import { FlaskConical, KeyRound, MoreHorizontal, Plus, RefreshCw, Trash2, Webhook } from 'lucide-react'
import { useCreateHook, useDeleteHook, useFeedSettings, usePatchHook, useSaveFeedSettings, useSettings, useTestHook } from '@/lib/queries'
import type { FeedHook, FeedHookKind, FeedRule, FeedSource } from '@/lib/types'
import { useT, type TKey } from '@/i18n'
import {
  Badge,
  Button,
  confirm,
  CopyButton,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  FormField,
  Input,
  Select,
  Sensitive,
  Skeleton,
  Switch,
  toast,
} from '@/components/ui'
import { Callout, SettingRow } from '@/features/common'
import { SettingsCard } from '@/pages/settings/sections/ui'

const KIND_LABEL: Record<FeedHookKind, string> = { stripe: 'Stripe', shopify: 'Shopify', github: 'GitHub', generic: 'JSON' }

export function FeedSettingsCards() {
  const t = useT()
  const { data, isPending } = useFeedSettings()
  const save = useSaveFeedSettings()
  const { data: settings } = useSettings()
  const [adding, setAdding] = React.useState(false)
  const publicOk = /^https:\/\//.test(settings?.public_url || '')
  const ruleOptions = (data?.rules || ['auto', 'off', 'silent', 'loud']).map((r) => ({ value: r, label: t(`feed.rule.${r}` as TKey) }))
  const setRule = (source: string, rule: FeedRule) => save.mutate({ rules: { [source]: rule } })
  const hookOf = (name: string) => data?.hooks.find((h) => h.name === name)

  return (
    <div className="grid gap-6">
      <SettingsCard title={t('feed.title')} description={t('feed.settingsDesc')}>
        <SettingRow label={t('feed.telegram')} description={t('feed.telegramDesc')} htmlFor="mx-feed-tg">
          <Switch id="mx-feed-tg" checked={data?.telegram ?? true} disabled={!data} onCheckedChange={(v) => save.mutate({ telegram: v })} />
        </SettingRow>
      </SettingsCard>
      <SettingsCard
        title={t('feed.sources')}
        description={t('feed.sourcesDesc')}
        actions={
          <Button size="sm" onClick={() => setAdding(true)} data-testid="add-hook">
            <Plus /> {t('feed.addWebhook')}
          </Button>
        }
      >
        {!publicOk && <Callout tone="warning" className="mb-3">{t('feed.notPublic')}</Callout>}
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
      </SettingsCard>
      {adding && <AddHookDialog onClose={() => setAdding(false)} />}
    </div>
  )
}

function SourceRow({ s, hook, ruleOptions, onRule }: { s: FeedSource; hook?: FeedHook; ruleOptions: { value: string; label: string }[]; onRule: (r: FeedRule) => void }) {
  const t = useT()
  const test = useTestHook()
  const patch = usePatchHook()
  const del = useDeleteHook()
  const [secret, setSecret] = React.useState(false)
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5" data-testid="feed-source" data-source={s.source}>
      <div className="grid min-w-0 flex-1 gap-0.5">
        <span className="flex min-w-0 items-center gap-2 text-sm font-medium">
          {hook && <Webhook className="size-3.5 shrink-0 text-muted-foreground" />}
          <span className="truncate">{s.label}</span>
          <Badge variant="muted" className="shrink-0">{hook ? KIND_LABEL[hook.kind] : s.builtin ? t('feed.builtin') : t('feed.script')}</Badge>
        </span>
        {hook ? (
          <span className="flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
            <code className="truncate font-mono text-[11px]">
              <Sensitive length={24}>{hook.url}</Sensitive>
            </code>
            <CopyButton text={hook.url} className="size-6" />
          </span>
        ) : (
          s.own_thread && <span className="text-xs text-muted-foreground">{t('feed.ownThread')}</span>
        )}
      </div>
      <Select value={s.rule} onValueChange={(v) => onRule(v as FeedRule)} options={ruleOptions} aria-label={t('feed.ruleLabel', { source: s.label })} className="w-44" />
      {hook && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={t('common.more')}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuItem onSelect={() => test.mutate(hook.id, { onSuccess: () => toast.success(t('feed.testSent')) })}>
              <FlaskConical /> {t('feed.test')}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setSecret(true)}>
              <KeyRound /> {hook.has_secret ? t('feed.changeSecret') : t('feed.setSecret')}
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={async () => {
                if (await confirm({ title: t('feed.regenerate'), description: t('feed.regenerateDesc'), confirmText: t('feed.regenerate') }))
                  patch.mutate({ id: hook.id, regenerate: true })
              }}
            >
              <RefreshCw /> {t('feed.regenerate')}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              destructive
              onSelect={async () => {
                if (await confirm({ title: t('feed.deleteHook', { name: hook.name }), description: t('feed.deleteHookDesc'), destructive: true, confirmText: t('common.delete') }))
                  del.mutate(hook.id)
              }}
            >
              <Trash2 /> {t('common.delete')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      {secret && hook && <SecretDialog hook={hook} onClose={() => setSecret(false)} />}
    </div>
  )
}

function SecretDialog({ hook, onClose }: { hook: FeedHook; onClose: () => void }) {
  const t = useT()
  const patch = usePatchHook()
  const [v, setV] = React.useState('')
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('feed.secretTitle', { name: hook.name })}</DialogTitle>
          <DialogDescription>{t(`feed.secretHelp.${hook.kind}` as TKey)}</DialogDescription>
        </DialogHeader>
        <Input value={v} onChange={(e) => setV(e.target.value)} placeholder={t('feed.secretPlaceholder')} autoComplete="off" />
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button loading={patch.isPending} onClick={() => patch.mutate({ id: hook.id, secret: v }, { onSuccess: onClose })}>
            {t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function AddHookDialog({ onClose }: { onClose: () => void }) {
  const t = useT()
  const create = useCreateHook()
  const [kind, setKind] = React.useState<FeedHookKind>('stripe')
  const [name, setName] = React.useState('stripe')
  const [secret, setSecret] = React.useState('')
  const [made, setMade] = React.useState<FeedHook | null>(null)
  const [err, setErr] = React.useState<string | null>(null)
  const kinds: FeedHookKind[] = ['stripe', 'shopify', 'github', 'generic']
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="hook-dialog">
        <DialogHeader>
          <DialogTitle>{made ? t('feed.hookReady') : t('feed.addWebhook')}</DialogTitle>
          <DialogDescription>{made ? t(`feed.where.${made.kind}` as TKey) : t('feed.addWebhookDesc')}</DialogDescription>
        </DialogHeader>
        {made ? (
          <div className="grid gap-3">
            <div className="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2">
              <code className="min-w-0 flex-1 font-mono text-xs break-all" data-testid="hook-url">
                {made.url}
              </code>
              <CopyButton text={made.url} />
            </div>
            {!made.has_secret && made.kind !== 'generic' && <Callout tone="warning">{t('feed.noSecretWarn')}</Callout>}
          </div>
        ) : (
          <form
            className="grid gap-4"
            id="hook-form"
            onSubmit={(e) => {
              e.preventDefault()
              setErr(null)
              create.mutate({ name, kind, secret: secret.trim() || undefined }, { onSuccess: setMade, onError: (x) => setErr(x.message) })
            }}
          >
            <FormField label={t('feed.kind')}>
              <Select
                value={kind}
                onValueChange={(v) => {
                  setKind(v as FeedHookKind)
                  if (kinds.includes(name as FeedHookKind)) setName(v === 'generic' ? 'webhook' : v)
                }}
                options={kinds.map((k) => ({ value: k, label: t(`feed.kind.${k}` as TKey) }))}
                aria-label={t('feed.kind')}
              />
            </FormField>
            <FormField label={t('feed.sourceName')} hint={t('feed.sourceNameHint')} error={err || undefined}>
              <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} autoComplete="off" data-testid="hook-name" />
            </FormField>
            <FormField label={t('feed.secret')} hint={t(`feed.secretHelp.${kind}` as TKey)}>
              <Input value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={t('feed.secretPlaceholder')} autoComplete="off" />
            </FormField>
          </form>
        )}
        <DialogFooter>
          {made ? (
            <Button onClick={onClose}>{t('common.done')}</Button>
          ) : (
            <>
              <Button variant="ghost" onClick={onClose}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" form="hook-form" loading={create.isPending} disabled={!name.trim()}>
                {t('feed.create')}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
