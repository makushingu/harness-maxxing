// The verification command of a repository in the Changes view (server: maxxing/verify.py): set it, run it, read
// why it failed, hand the failure to Claude. `useVerifyFlow().ensure` is what Push and Pull request wait for.
import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Check, CircleAlert, Loader2, Pencil, ShieldCheck, Square, Wrench } from 'lucide-react'
import { Button, Checkbox, Input, Tooltip, toast } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { codeApi, codeKeys, useVerify, type Verify } from './api'

const POLL_MS = 1500

export function useVerifyFlow(root: string) {
  const qc = useQueryClient()
  const q = useVerify(root)
  const put = React.useCallback((v: Verify) => void qc.setQueryData(codeKeys.verify(root), v), [qc, root])
  /** Runs the command when its last result is not about what is there now, and waits: true = passed (or no command). */
  const ensure = React.useCallback(async () => {
    let v = await codeApi.verify(root)
    if (!v.command || (v.run?.state === 'passed' && v.run.fresh)) return true
    if (v.run?.state !== 'running') v = await codeApi.verifyRun(root)
    for (;;) {
      put(v)
      if (v.run?.state !== 'running') break
      await new Promise((r) => window.setTimeout(r, POLL_MS))
      v = await codeApi.verify(root)
    }
    return v.run?.state === 'passed'
  }, [root, put])
  return { data: q.data, put, ensure }
}

export function VerifyRow({ root, sid, flow, locked }: { root: string; sid: string; flow: ReturnType<typeof useVerifyFlow>; locked: boolean }) {
  const t = useT()
  const v = flow.data
  const [editing, setEditing] = React.useState(false)
  const [cmd, setCmd] = React.useState('')
  const [open, setOpen] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  if (!v) return null
  const run = v.run
  const going = run?.state === 'running'
  const bad = run?.state === 'failed' || run?.state === 'stopped'

  const act = async (f: () => Promise<Verify | void>) => {
    setBusy(true)
    try {
      const out = await f()
      if (out) flow.put(out)
    } catch (e) {
      toast.error(t('code.failed'), errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const edit = () => {
    setCmd(v.command || v.suggest[0] || '')
    setEditing(true)
  }

  if (editing) {
    return (
      <form
        className="space-y-1.5"
        data-testid="verify-form"
        onSubmit={(e) => {
          e.preventDefault()
          void act(() => codeApi.verifySet(root, { command: cmd.trim() })).then(() => setEditing(false))
        }}
      >
        <div className="flex items-center gap-2">
          <Input autoFocus value={cmd} onChange={(e) => setCmd(e.target.value)} placeholder={t('code.verify.ph')} aria-label={t('code.verify.command')} className="h-8 font-mono text-[13px]" />
          <Button size="sm" type="submit" disabled={busy}>
            {t('common.save')}
          </Button>
          <Button size="sm" type="button" variant="ghost" onClick={() => setEditing(false)}>
            {t('common.cancel')}
          </Button>
        </div>
        {v.suggest.length > 1 && (
          <div className="flex flex-wrap gap-1">
            {v.suggest.map((s) => (
              <button key={s} type="button" onClick={() => setCmd(s)} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground hover:text-foreground">
                {s}
              </button>
            ))}
          </div>
        )}
        <p className="text-[11px] text-muted-foreground">{t('code.verify.hint')}</p>
      </form>
    )
  }
  // off until the owner turns it on for this repository: its merges then wait for the verification and a review
  const gate = (
    <Tooltip content={t('code.gate.holdTip')}>
      <label className="flex w-fit cursor-pointer items-center gap-2 text-[11px] text-muted-foreground">
        <Checkbox checked={v.gate} disabled={busy} onCheckedChange={(on) => void act(() => codeApi.verifySet(root, { gate: on === true }))} data-testid="gate-hold" />
        {t('code.gate.hold')}
      </label>
    </Tooltip>
  )
  if (!v.command) {
    return (
      <div className="space-y-1.5">
        <button type="button" onClick={edit} className="text-[11px] text-muted-foreground hover:text-foreground hover:underline" data-testid="verify-set">
          {t('code.verify.set')}
        </button>
        {gate}
      </div>
    )
  }
  return (
    <div className="space-y-1.5" data-testid="verify">
      <div className="flex flex-wrap items-center gap-2">
        {going ? (
          <Button size="sm" variant="outline" onClick={() => void act(() => codeApi.verifyStop(root))} disabled={busy} data-testid="verify-stop">
            <Square />
            {t('code.verify.stop')}
          </Button>
        ) : (
          <Button size="sm" variant="outline" onClick={() => void act(() => codeApi.verifyRun(root))} disabled={busy || locked} data-testid="verify-run">
            <ShieldCheck />
            {t('code.verify.run')}
          </Button>
        )}
        {run && (
          <span
            className={cn('inline-flex items-center gap-1 text-[11px]', going ? 'text-muted-foreground' : bad ? 'text-destructive' : run.fresh ? 'text-success' : 'text-muted-foreground')}
            data-testid="verify-state"
            data-state={run.state}
          >
            {going ? <Loader2 className="size-3 animate-spin" /> : bad ? <CircleAlert className="size-3" /> : <Check className="size-3" />}
            {t(`code.verify.state.${run.state}`)}
            {!going && !run.fresh && <span className="text-muted-foreground">· {t('code.verify.old')}</span>}
          </span>
        )}
        <code className="min-w-0 truncate font-mono text-[11px] text-muted-foreground">{v.command}</code>
        <Tooltip content={t('code.verify.change')}>
          <Button variant="ghost" size="icon-sm" className="size-7" aria-label={t('code.verify.change')} onClick={edit} disabled={going}>
            <Pencil className="size-3.5" />
          </Button>
        </Tooltip>
        {run && !going && (
          <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setOpen((o) => !o)} data-testid="verify-output-btn">
            {t('code.verify.output')}
          </Button>
        )}
        {bad && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            data-testid="verify-fix"
            onClick={() => void act(() => codeApi.verifyFix(root, sid).then(() => void toast.success(t('code.verify.sent'))))}
          >
            <Wrench />
            {t('code.verify.fix')}
          </Button>
        )}
      </div>
      {open && run && !going && (
        <pre className="max-h-64 overflow-auto rounded-md bg-muted p-2 font-mono text-[11px] whitespace-pre-wrap" data-testid="verify-output">
          {run.tail || t('code.verify.noOutput')}
        </pre>
      )}
      {gate}
    </div>
  )
}
