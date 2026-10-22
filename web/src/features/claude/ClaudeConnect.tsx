import * as React from 'react'
import { KeyRound, PlugZap, RefreshCw, Terminal, Trash2 } from 'lucide-react'
import { useClaudeAuth, useClaudeAuthRemove, useClaudeStatus, useClaudeTest } from '@/lib/queries'
import { errorMessage } from '@/lib/api'
import { fmtRelative } from '@/lib/format'
import type { ClaudeAuthMethod, ClaudeTestResult } from '@/lib/types'
import { useLang, useT, type TKey } from '@/i18n'
import { Badge, Button, CodeBlock, FormField, SecretInput, Sensitive, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger, confirm } from '@/components/ui'
import { Callout, Steps } from '../common'

const METHOD: Record<NonNullable<ClaudeAuthMethod>, TKey> = {
  oauth_token: 'claude.method.oauth_token',
  credentials: 'claude.method.credentials',
  api_key: 'claude.method.api_key',
}

/** Live status line + test button. */
export function ClaudeStatusCard({ onReplace }: { onReplace?: () => void }) {
  const t = useT()
  const lang = useLang()
  const { data: s, isLoading } = useClaudeStatus()
  const test = useClaudeTest()
  const remove = useClaudeAuthRemove()
  const [result, setResult] = React.useState<ClaudeTestResult | null>(null)
  if (isLoading || !s) return <Skeleton className="h-[74px] rounded-lg" />
  if (!s.installed)
    return (
      <Callout tone="error" title={t('claude.notInstalled')}>
        {t('claude.notInstalledDesc')} <CodeBlock inline code="maxxing doctor" className="mt-2" />
      </Callout>
    )
  return (
    <div className="grid gap-3">
      <Callout
        tone={s.auth.ok ? 'success' : 'warning'}
        title={s.auth.ok ? t('claude.connected') : s.auth.method ? t('claude.signInExpired') : t('claude.notConnected')}
        action={
          s.auth.ok ? (
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                loading={test.isPending}
                onClick={() =>
                  test.mutate(undefined, {
                    onSuccess: setResult,
                    onError: (e) => setResult({ ok: false, model: '', ms: 0, error: errorMessage(e) }),
                  })
                }
              >
                <PlugZap /> {t('claude.test')}
              </Button>
            </div>
          ) : undefined
        }
      >
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          {s.auth.method && <Badge variant="outline">{t(METHOD[s.auth.method])}</Badge>}
          {s.version && <span>Claude Code {s.version}</span>}
          {s.auth.detail && (
            <span>
              · <Sensitive>{s.auth.detail}</Sensitive>
            </span>
          )}
          {s.auth.ok && s.auth.checked_at && (
            <span className="text-muted-foreground">· {t('claude.verified', { when: fmtRelative(s.auth.checked_at, lang) })}</span>
          )}
        </span>
      </Callout>
      {result && (
        <Callout tone={result.ok ? 'success' : 'error'} title={result.ok ? t('claude.testOk') : t('claude.testFailed')}>
          {result.ok ? t('claude.testOkDesc', { model: result.model, ms: Math.round(result.ms) }) : result.error}
        </Callout>
      )}
      {s.auth.ok && onReplace && (
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={onReplace}>
            <RefreshCw /> {t('claude.replace')}
          </Button>
          {s.auth.method !== 'credentials' && (
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive"
              loading={remove.isPending}
              onClick={async () => {
                if (await confirm({ title: t('claude.removeTitle'), description: t('claude.removeDesc'), destructive: true, confirmText: t('common.remove') })) remove.mutate()
              }}
            >
              <Trash2 /> {t('claude.remove')}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}

/** Paste a `claude setup-token` OAuth token or an Anthropic API key, then the server tests it. */
export function ClaudeAuthForm({ onDone }: { onDone?: () => void }) {
  const t = useT()
  const [kind, setKind] = React.useState<'oauth_token' | 'api_key'>('oauth_token')
  const [value, setValue] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)
  const auth = useClaudeAuth()
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const v = value.trim()
    if (!v) return setError(t('claude.pasteFirst'))
    setError(null)
    auth.mutate(
      { kind, value: v },
      {
        onSuccess: (r) => {
          if (r.ok) {
            setValue('')
            onDone?.()
          } else setError(r.error || t('claude.authFailed'))
        },
        onError: (e) => setError(errorMessage(e)),
      },
    )
  }
  return (
    <Tabs value={kind} onValueChange={(v) => {
        setKind(v as typeof kind)
        setError(null)
      }}>
      <TabsList className="w-full sm:w-auto">
        <TabsTrigger value="oauth_token" className="flex-1">
          <Terminal /> {t('claude.tabSubscription')}
        </TabsTrigger>
        <TabsTrigger value="api_key" className="flex-1">
          <KeyRound /> {t('claude.tabApiKey')}
        </TabsTrigger>
      </TabsList>
      <form onSubmit={submit} className="mt-4 grid gap-5" noValidate>
        <TabsContent value="oauth_token" className="mt-0 grid gap-4">
          <p className="text-sm text-muted-foreground">{t('claude.subscriptionIntro')}</p>
          <Steps
            items={[
              <div className="grid gap-2">
                <span>{t('claude.step1')}</span>
                <CodeBlock inline code={`ssh root@${window.location.hostname}`} />
              </div>,
              <div className="grid gap-2">
                <span>{t('claude.step2')}</span>
                <CodeBlock inline code="claude setup-token" />
              </div>,
              <span>{t('claude.step3')}</span>,
            ]}
          />
        </TabsContent>
        <TabsContent value="api_key" className="mt-0 grid gap-4">
          <p className="text-sm text-muted-foreground">{t('claude.apiKeyIntro')}</p>
          <Steps
            items={[
              <span>
                {t('claude.apiStep1')}{' '}
                <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener noreferrer">
                  console.anthropic.com
                </a>
              </span>,
              <span>{t('claude.apiStep2')}</span>,
            ]}
          />
        </TabsContent>
        <FormField label={kind === 'oauth_token' ? t('claude.tokenLabel') : t('claude.keyLabel')} error={error || undefined} hint={t('claude.storedHint')}>
          <SecretInput value={value} onChange={(e) => setValue(e.target.value)} placeholder={kind === 'oauth_token' ? 'sk-ant-oat01-…' : 'sk-ant-api03-…'} />
        </FormField>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" loading={auth.isPending}>
            <PlugZap /> {t('claude.connectTest')}
          </Button>
          {auth.isPending && <span className="text-[13px] text-muted-foreground">{t('claude.testing')}</span>}
        </div>
      </form>
    </Tabs>
  )
}

/** Status + (form when not connected or when replacing). */
export function ClaudeConnect() {
  const t = useT()
  const { data: s } = useClaudeStatus()
  const [replacing, setReplacing] = React.useState(false)
  const showForm = !!s && s.installed && (!s.auth.ok || replacing)
  return (
    <div className="grid gap-5">
      <ClaudeStatusCard onReplace={replacing ? undefined : () => setReplacing(true)} />
      {showForm && (
        <div className="rounded-lg border p-4 md:p-5">
          <ClaudeAuthForm onDone={() => setReplacing(false)} />
          {replacing && (
            <Button variant="ghost" size="sm" className="mt-3" onClick={() => setReplacing(false)}>
              {t('common.cancel')}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
