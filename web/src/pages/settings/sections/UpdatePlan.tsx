// Smart update, in the Version card: what the next update does to THIS server (preflight, simulated on a
// throw-away copy), the right button ("Update" or "Update with Harness"), and after an update the verification
// of extensions and customizations ("Fix with Harness" when something stopped working).
import * as React from 'react'
import { useNavigate } from 'react-router'
import { ArrowUpCircle, Bot, CheckCircle2, CircleAlert, CircleCheck, CircleDashed, PackageCheck, ShieldCheck, Wrench } from 'lucide-react'
import { usePreflight, useUpdateAssist, useUpdateFix, useVerifyUpdate } from '@/lib/queries'
import type { Preflight, PreflightCustom, Session, VersionInfo } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Button, Spinner, toast } from '@/components/ui'
import { Callout } from '@/features/common'

const sessionHref = (s: Session) => `/sessions?path=${encodeURIComponent(s.path)}&session=${s.id}`

function Row({ tone, children, detail }: { tone: 'ok' | 'warn' | 'error' | 'info'; children: React.ReactNode; detail?: string }) {
  const Icon = tone === 'ok' ? CircleCheck : tone === 'info' ? CircleDashed : CircleAlert
  return (
    <li className="flex items-start gap-2 text-[13px]">
      <Icon className={cn('mt-0.5 size-3.5 shrink-0', tone === 'ok' ? 'text-success' : tone === 'warn' ? 'text-warning' : tone === 'error' ? 'text-destructive' : 'text-muted-foreground')} />
      <span className="min-w-0">
        {children}
        {detail && <span className="block truncate font-mono text-[11px] text-muted-foreground">{detail}</span>}
      </span>
    </li>
  )
}

function customLine(c: PreflightCustom, t: ReturnType<typeof useT>) {
  const tone = c.status === 'conflict' ? 'error' : c.status === 'review' || c.status === 'unknown' ? 'warn' : c.status === 'included' ? 'info' : 'ok'
  return (
    <Row key={c.id} tone={tone} detail={(c.conflicts.length ? c.conflicts : c.status === 'review' ? c.overlap : []).join(', ') || undefined}>
      <span className="font-medium">{c.title}</span> — {t(`update.custom.${c.status}`)}
    </Row>
  )
}

/** Before updating: the preflight and the right button. `onUpdate` runs the plain update (confirm included). */
export function UpdatePlan({ v, onUpdate, updating }: { v: VersionInfo; onUpdate: () => void; updating: boolean }) {
  const t = useT()
  const navigate = useNavigate()
  const pf = usePreflight(true, v.latest_commit)
  const assist = useUpdateAssist()
  const p: Preflight | undefined = pf.data
  const startAssist = () =>
    assist.mutate(undefined, {
      onSuccess: (r) => navigate(sessionHref(r.session)),
      onError: () => toast.error(t('update.assistFailed')),
    })

  if (pf.isPending)
    return (
      <p className="flex items-center gap-2 text-[13px] text-muted-foreground" data-testid="preflight-loading">
        <Spinner className="size-3.5" /> {t('update.checking')}
      </p>
    )
  // preflight unavailable (no git clone, offline...): the plain button, as before
  if (!p || pf.isError || !p.ok)
    return (
      <div>
        <Button loading={updating} onClick={onUpdate}>
          <ArrowUpCircle /> {t('system.update')}
        </Button>
      </div>
    )
  const mine = p.customs.length + (p.unsaved.length ? 1 : 0)
  const adapt = p.verdict === 'adapt'
  return (
    <div className="grid gap-3" data-testid="preflight" data-verdict={p.verdict}>
      <div className={cn('grid grid-cols-[minmax(0,1fr)] gap-2.5 rounded-lg border p-3.5', adapt ? 'border-warning/40 bg-warning/5' : 'bg-muted/30')}>
        <div className="flex items-center gap-2 text-sm font-medium">
          {adapt ? <Wrench className="size-4 text-warning" /> : <ShieldCheck className="size-4 text-success" />}
          {adapt ? t('update.adaptTitle') : mine ? t('update.simpleTitleCustoms', { count: mine }) : t('update.simpleTitle')}
        </div>
        {(p.customs.length > 0 || p.unsaved.length > 0 || p.web_changes.length > 0 || p.extensions.length > 0 || p.notes.length > 0) && (
          <ul className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
            {p.customs.map((c) => customLine(c, t))}
            {p.unsaved.length > 0 && (
              <Row tone={p.unsaved_overlap?.length ? 'warn' : 'ok'} detail={p.unsaved.slice(0, 4).join(', ')}>
                {t('update.unsaved', { count: p.unsaved.length })}
              </Row>
            )}
            {p.web_changes.length > 0 && (
              <Row tone="warn" detail={p.web_changes.slice(0, 3).join(', ')}>
                {t('update.webChanges', { count: p.web_changes.length })}
              </Row>
            )}
            {p.extensions.map((e) => (
              <Row key={e.id} tone="error" detail={e.reason}>
                {t('update.extension', { name: e.name })}
              </Row>
            ))}
            {p.notes.length > 0 && <Row tone="info">{t('update.notes', { count: p.notes.length })}</Row>}
          </ul>
        )}
        <p className="text-xs text-muted-foreground">{adapt ? t('update.adaptDesc') : t('update.simpleDesc')}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {adapt ? (
          <Button loading={assist.isPending} onClick={startAssist} data-testid="update-assist">
            <Bot /> {t('update.withHarness')}
          </Button>
        ) : (
          <Button loading={updating} onClick={onUpdate}>
            <ArrowUpCircle /> {t('system.update')}
          </Button>
        )}
      </div>
    </div>
  )
}

/** After an update: the verification, and the session applying the upgrade notes. */
export function UpdateReportView({ v }: { v: VersionInfo }) {
  const t = useT()
  const navigate = useNavigate()
  const fix = useUpdateFix()
  const verify = useVerifyUpdate()
  const r = v.report
  const notes = v.after?.notes_session && v.after.to === v.version ? v.after : null
  const recheck = (
    <Button
      variant="ghost"
      size="sm"
      loading={verify.isPending}
      onClick={() => verify.mutate(undefined, { onSuccess: (x) => (x.report.ok ? toast.success(t('update.allGood')) : undefined) })}
    >
      {t('update.verify')}
    </Button>
  )
  return (
    <>
      {r && !r.ok && (
        <Callout
          tone="warning"
          title={t('update.problems', { count: r.problems, version: r.version })}
          action={
            <Button size="sm" loading={fix.isPending} onClick={() => fix.mutate(undefined, { onSuccess: (x) => navigate(sessionHref(x.session)) })}>
              <Bot /> {t('update.fix')}
            </Button>
          }
        >
          {t('update.problemsDesc')}
        </Callout>
      )}
      {r?.ok && r.version === v.version && (
        <p className="flex flex-wrap items-center gap-x-1.5 text-[13px] text-muted-foreground" data-testid="update-verified">
          <PackageCheck className="size-3.5 text-success" /> {t('update.verified')}
          {recheck}
        </p>
      )}
      {!r && !!v.custom?.count && (
        <p className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
          <ShieldCheck className="size-3.5" />
          <Button
            variant="link"
            size="sm"
            className="h-auto shrink p-0 text-left text-[13px] whitespace-normal"
            disabled={verify.isPending}
            onClick={() => verify.mutate(undefined, { onSuccess: (x) => (x.report.ok ? toast.success(t('update.allGood')) : undefined) })}
          >
            {t('update.verifyLong')}
          </Button>
          {verify.isPending && <Spinner className="size-3.5" />}
        </p>
      )}
      {notes && (
        <p className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
          <CheckCircle2 className="size-3.5 text-primary" /> {t('update.notesSession')}
          <Button variant="link" size="sm" className="h-auto p-0" onClick={() => navigate(`/sessions?path=${encodeURIComponent(notes.notes_path || '')}&session=${notes.notes_session}`)}>
            {t('update.openSession')}
          </Button>
        </p>
      )}
    </>
  )
}
