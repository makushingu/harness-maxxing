// What a merge waits for when its repository holds its merges (server: maxxing/gate.py): the checks of the forge,
// the repository's verification command and a review by another Claude model, on the commit to merge. Shown above
// Merge in the PR view and in the end of a separate copy; "Merge anyway" stays there, behind a confirmation.
import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Bot, Check, CircleAlert, CircleDashed, ListChecks, Loader2, ShieldCheck } from 'lucide-react'
import { useNavigate } from 'react-router'
import { Button, toast } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { codeApi, type Gate, type GateTarget } from './api'

type Tone = 'ok' | 'bad' | 'wait' | 'todo'
const ICON = { ok: Check, bad: CircleAlert, wait: Loader2, todo: CircleDashed }
const TONE = { ok: 'text-success', bad: 'text-destructive', wait: 'text-muted-foreground', todo: 'text-muted-foreground' }

function Row({ icon: Icon, label, tone, text, children }: { icon: typeof Check; label: string; tone: Tone; text: string; children?: React.ReactNode }) {
  const State = ICON[tone]
  return (
    <li className="flex flex-wrap items-center gap-x-2 gap-y-1" data-tone={tone}>
      <Icon className="size-3.5 shrink-0 text-muted-foreground" />
      <span className="font-medium">{label}</span>
      <span className={cn('inline-flex min-w-0 items-center gap-1', TONE[tone])}>
        <State className={cn('size-3 shrink-0', tone === 'wait' && 'animate-spin')} />
        <span className="min-w-0">{text}</span>
      </span>
      {children && <span className="ml-auto flex items-center gap-1">{children}</span>}
    </li>
  )
}

export function GatePanel({ target, gate, onLeave }: { target: GateTarget; gate: Extract<Gate, { active: true }>; onLeave?: () => void }) {
  const t = useT()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [busy, setBusy] = React.useState<null | 'review' | 'verify'>(null)
  const act = async (what: 'review' | 'verify') => {
    setBusy(what)
    try {
      const out = what === 'review' ? await codeApi.gateReview(target) : await codeApi.gateVerify(target)
      qc.setQueryData(['code', 'gate', target], out)
      if (what === 'review') void qc.invalidateQueries({ queryKey: ['sessions'] })
    } catch (e) {
      toast.error(t('code.failed'), errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  const { checks, verify, review } = gate
  const vTone: Tone = verify.state === 'passed' || verify.state === 'none' ? 'ok' : verify.state === 'failed' ? 'bad' : verify.state === 'running' ? 'wait' : 'todo'
  const rTone: Tone = review.state === 'accepted' ? 'ok' : review.state === 'running' ? 'wait' : review.state === 'missing' ? 'todo' : 'bad'
  return (
    <div className="space-y-1.5 rounded-md border px-2.5 py-2 text-[13px]" data-testid="gate" data-open={gate.open}>
      <p className="text-[11px] text-muted-foreground">{gate.open ? t('code.gate.open') : t('code.gate.closed')}</p>
      <ul className="list-none space-y-1.5 p-0">
        {checks && (
          <Row icon={ListChecks} label={t('code.gate.checks')} tone={checks.state === 'ok' || checks.state === 'none' ? 'ok' : checks.state === 'failed' ? 'bad' : 'wait'} text={t(`code.gate.checks.${checks.state}`, { ok: checks.ok, total: checks.total, failed: checks.failed })} />
        )}
        <Row icon={ShieldCheck} label={t('code.gate.verify')} tone={vTone} text={t(`code.gate.verify.${verify.state}`)}>
          {(verify.state === 'missing' || verify.state === 'failed') && (
            <Button size="sm" variant="outline" className="h-7" onClick={() => void act('verify')} disabled={!!busy} data-testid="gate-verify">
              {busy === 'verify' && <Loader2 className="animate-spin" />}
              {t('code.verify.run')}
            </Button>
          )}
        </Row>
        <Row icon={Bot} label={t('code.gate.review')} tone={rTone} text={t(`code.gate.review.${review.state}`, { model: review.model ?? '', round: review.rounds, max: review.max })}>
          {review.session && (
            <Button
              size="sm"
              variant="ghost"
              className="h-7"
              onClick={() => {
                onLeave?.()
                navigate(`/sessions/${review.session}`)
              }}
            >
              {t('code.gate.review.read')}
            </Button>
          )}
          {review.state !== 'running' && review.state !== 'accepted' && (
            <Button size="sm" variant="outline" className="h-7" onClick={() => void act('review')} disabled={!!busy} data-testid="gate-review">
              {busy === 'review' && <Loader2 className="animate-spin" />}
              {t(review.state === 'missing' ? 'code.gate.review.ask' : 'code.gate.review.again')}
            </Button>
          )}
        </Row>
      </ul>
      {review.summary && review.state !== 'running' && <p className="border-t pt-1.5 text-xs whitespace-pre-wrap text-muted-foreground" data-testid="gate-summary">{review.summary}</p>}
    </div>
  )
}
