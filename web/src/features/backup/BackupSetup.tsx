import * as React from 'react'
import { CloudUpload, ExternalLink, GitBranch, Lock } from 'lucide-react'
import { useBackup, useBackupConfig, useBackupRun } from '@/lib/queries'
import { errorMessage } from '@/lib/api'
import type { BackupRunResult } from '@/lib/types'
import { useT } from '@/i18n'
import { Badge, Button, Checkbox, FormField, Input, Label, SecretInput, Sensitive, Skeleton } from '@/components/ui'
import { Callout, Steps } from '../common'

const REPO_RE = /^[A-Za-z0-9-]{1,39}\/[A-Za-z0-9._-]{1,100}$/

export function BackupWhy() {
  const t = useT()
  return (
    <Callout tone="info" title={t('backup.whyTitle')}>
      {t('backup.why')}
    </Callout>
  )
}

/** Repo + token form, then "run first backup". */
export function BackupSetup({ onFirstRun }: { onFirstRun?: (r: BackupRunResult) => void }) {
  const t = useT()
  const { data: b, isLoading } = useBackup()
  const [repo, setRepo] = React.useState('')
  const [token, setToken] = React.useState('')
  const [create, setCreate] = React.useState(true)
  const [errors, setErrors] = React.useState<{ repo?: string; token?: string; form?: string }>({})
  const [editing, setEditing] = React.useState(false)
  const config = useBackupConfig()
  const run = useBackupRun()
  const [result, setResult] = React.useState<BackupRunResult | null>(null)

  if (isLoading || !b) return <Skeleton className="h-64" />
  const configured = b.configured && !editing

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const errs: typeof errors = {}
    if (!REPO_RE.test(repo.trim())) errs.repo = t('backup.repoInvalid')
    if (!token.trim()) errs.token = t('backup.tokenRequired')
    setErrors(errs)
    if (Object.keys(errs).length) return
    config.mutate(
      { repo: repo.trim(), token: token.trim(), create },
      {
        onSuccess: (r) => {
          if (!r.ok) return setErrors({ form: r.error || t('backup.configFailed') })
          if (r.private === false) return setErrors({ form: t('backup.notPrivate') })
          setToken('')
          setEditing(false)
        },
        onError: (e) => setErrors({ form: errorMessage(e) }),
      },
    )
  }

  if (configured)
    return (
      <div className="grid gap-4">
        <Callout
          tone="success"
          title={t('backup.connected')}
          action={
            <Button variant="ghost" size="sm" onClick={() => {
                setRepo(b.repo || '')
                setEditing(true)
              }}>
              {t('common.change')}
            </Button>
          }
        >
          <span className="flex flex-wrap items-center gap-2">
            <GitBranch className="size-3.5" />
            <span className="font-mono">
              <Sensitive length={10}>{b.repo}</Sensitive>
            </span>
            {b.private && (
              <Badge variant="success">
                <Lock /> {t('backup.private')}
              </Badge>
            )}
          </span>
        </Callout>
        {result && (
          <Callout tone={result.ok ? 'success' : 'error'} title={result.ok ? t('backup.runOk') : t('backup.runFailed')}>
            {result.ok ? t('backup.runOkDesc', { files: result.files, commit: (result.commit || '').slice(0, 7) }) : result.error}
          </Callout>
        )}
        <div>
          <Button
            loading={run.isPending}
            variant={result?.ok ? 'outline' : 'default'}
            onClick={() =>
              run.mutate(undefined, {
                onSuccess: (r) => {
                  setResult(r)
                  if (r.ok) onFirstRun?.(r)
                },
                onError: (e) => setResult({ ok: false, commit: null, files: 0, error: errorMessage(e) }),
              })
            }
          >
            <CloudUpload /> {b.last ? t('backup.runNow') : t('backup.runFirst')}
          </Button>
        </div>
      </div>
    )

  return (
    <div className="grid gap-5">
      <Steps
        items={[
          <span>
            {t('backup.gh1')}{' '}
            <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener noreferrer">
              github.com/settings/personal-access-tokens <ExternalLink className="inline size-3" />
            </a>
          </span>,
          <span>{t('backup.gh2')}</span>,
          <span>
            {t('backup.gh3')} <strong>Contents: Read and write</strong>, <strong>Administration: Read and write</strong> {t('backup.gh3b')}
          </span>,
          <span>{t('backup.gh4')}</span>,
        ]}
      />
      <form onSubmit={submit} className="grid gap-4" noValidate>
        <FormField label={t('backup.repo')} error={errors.repo} hint={t('backup.repoHint')}>
          <Input value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="your-name/claude-memory" autoComplete="off" spellCheck={false} className="font-mono" />
        </FormField>
        <FormField label={t('backup.token')} error={errors.token}>
          <SecretInput value={token} onChange={(e) => setToken(e.target.value)} placeholder="github_pat_…" />
        </FormField>
        <Label className="items-start gap-3 leading-snug font-normal">
          <Checkbox checked={create} onCheckedChange={(v) => setCreate(v === true)} className="mt-0.5" />
          <span className="grid gap-0.5">
            <span className="font-medium">{t('backup.create')}</span>
            <span className="text-[13px] text-muted-foreground">{t('backup.createHint')}</span>
          </span>
        </Label>
        {errors.form && <Callout tone="error">{errors.form}</Callout>}
        <div className="flex gap-2">
          <Button type="submit" loading={config.isPending}>
            <Lock /> {t('backup.connect')}
          </Button>
          {editing && (
            <Button variant="ghost" onClick={() => setEditing(false)}>
              {t('common.cancel')}
            </Button>
          )}
        </div>
      </form>
    </div>
  )
}
