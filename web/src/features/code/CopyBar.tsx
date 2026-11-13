// The bar above the composer of a session on a separate copy (Code mode): its branch against its base, what is not
// committed, and one main button - "Open a PR" on GitHub, "Merge into <base>" otherwise -, the others behind
// "Finish…" (commit first with a message proposed by Claude, open a PR, merge here, discard). A copy on a pull
// request shows that PR and opens it in the PR view. Plan: plans/code-worktree-pr.md (lot 4).
import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Check, CircleAlert, FolderGit2, GitBranch, GitMerge, GitPullRequest, Loader2, MoreHorizontal, Sparkles, Trash2, Wrench } from 'lucide-react'
import {
  Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger, Sensitive, Textarea, Tooltip, toast,
} from '@/components/ui'
import { errorMessage, isApiError } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import type { Session } from '@/lib/types'
import { openFileViewer } from '@/features/files/viewerStore'
import { codeApi, useRepoStatus } from './api'
import { copyApi, copyKeys, useCopyStatus, type CopyStatus } from './copyApi'
import { prPath } from './prApi'

type End = 'pr' | 'merge' | 'discard'

export function CopyBar({ session, running, onAsk }: { session: Session; running: boolean; onAsk: (text: string) => void }) {
  const t = useT()
  const qc = useQueryClient()
  const wt = session.worktree
  const live = !!wt && !wt.removed
  const st = useCopyStatus(session.id, live)
  const repo = useRepoStatus(wt?.path ?? '', live && !!st.data?.exists && !!st.data?.github)
  const [end, setEnd] = React.useState<End | null>(null)
  const [busy, setBusy] = React.useState(false)
  // a turn may have committed or changed files: read again when it ends
  React.useEffect(() => {
    if (!running) void qc.invalidateQueries({ queryKey: copyKeys.status(session.id) })
  }, [running, qc, session.id])
  if (!wt) return null
  if (wt.removed) {
    return wt.kept_branch ? (
      <div className="flex items-center gap-2 border-t bg-muted/40 px-3 py-1 text-[11px] text-muted-foreground" data-testid="copy-bar">
        <FolderGit2 className="size-3.5 shrink-0" />
        <span className="min-w-0 truncate"><Sensitive>{t('copy.goneKept', { branch: wt.kept_branch })}</Sensitive></span>
      </div>
    ) : null
  }
  const s = st.data
  const pr = repo.data?.pr
  const github = !!s?.github && !s.fork
  const dirty = s?.dirty ?? 0
  const prOf = wt.pr?.number && s?.github ? { full: wt.pr.full || s.github, n: wt.pr.number } : pr && s?.github ? { full: s.github, n: pr.number } : null
  const main: End | null = !s?.exists || wt.pr ? null : github ? (pr ? null : 'pr') : 'merge'

  const openPr = async () => {
    setBusy(true)
    try {
      if (dirty) return setEnd('pr')
      const out = await codeApi.pr(wt.path)
      void qc.invalidateQueries({ queryKey: ['code'] })
      toast.success(t('code.prOpened'))
      if (s?.github) openFileViewer(prPath({ full: s.github, n: out.number }))
    } catch (e) {
      toast.error(t('code.failed'), errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex min-w-0 items-center gap-2 border-t bg-muted/40 px-3 py-1 text-[12px]" data-testid="copy-bar">
      <Tooltip content={<span className="block max-w-80 font-mono text-[11px] break-all">{wt.path}</span>}>
        <span className="inline-flex min-w-0 items-center gap-1 font-mono text-[11px]">
          <GitBranch className="size-3.5 shrink-0 text-primary" />
          <span className="truncate"><Sensitive>{s?.branch || wt.branch}</Sensitive></span>
        </span>
      </Tooltip>
      {s?.exists && (
        <span className="min-w-0 truncate text-[11px] text-muted-foreground tabular-nums">
          <Sensitive>{`← ${s.base}`}</Sensitive>
          {` · ${s.ahead ? t('copy.ahead', { count: s.ahead }) : t('copy.noCommit')}`}
          {!!s.behind && ` · ${t('copy.behind', { count: s.behind, base: s.base })}`}
          {!!dirty && ` · ${t('copy.dirty', { count: dirty })}`}
        </span>
      )}
      {wt.preparing && (
        <span className="inline-flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground">
          <Loader2 className="size-3 animate-spin" />
          {t('copy.preparing')}
        </span>
      )}
      {s?.prepare?.state === 'failed' && (
        <button type="button" className="inline-flex shrink-0 items-center gap-1 text-[11px] text-destructive hover:underline" onClick={() => void copyApi.prepareLog(session.id).then((r) => onAsk(t('copy.prepareFailedAsk', { cmd: s.prepare!.cmd, log: r.log.slice(-3000) })))}>
          <CircleAlert className="size-3" />
          {t('copy.prepareFailed')}
        </button>
      )}
      {s && !s.exists && <span className="text-[11px] text-destructive">{t('copy.missing')}</span>}
      <div className="ml-auto flex shrink-0 items-center gap-1">
        {prOf && (
          <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => openFileViewer(prPath(prOf))} data-testid="copy-pr">
            <GitPullRequest />#{prOf.n}
          </Button>
        )}
        {main === 'pr' && (
          <Button size="sm" variant="outline" className="h-7" onClick={() => void openPr()} disabled={busy || running || !s?.ahead && !dirty} data-testid="copy-open-pr">
            {busy ? <Loader2 className="animate-spin" /> : <GitPullRequest />}
            {t('code.openPrBtn')}
          </Button>
        )}
        {main === 'merge' && (
          <Button size="sm" variant="outline" className="h-7" onClick={() => setEnd('merge')} disabled={running || (!s?.ahead && !dirty)} data-testid="copy-merge">
            <GitMerge />
            {t('copy.mergeInto', { base: s?.base ?? wt.base })}
          </Button>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="ghost" className="size-7" aria-label={t('copy.finish')} disabled={running}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {s?.github && !s.fork && !wt.pr && !pr && <DropdownMenuItem onSelect={() => setEnd('pr')}><GitPullRequest /> {t('code.openPrBtn')}</DropdownMenuItem>}
            {!wt.pr && <DropdownMenuItem onSelect={() => setEnd('merge')}><GitMerge /> {t('copy.mergeInto', { base: s?.base ?? wt.base })}</DropdownMenuItem>}
            <DropdownMenuItem onSelect={() => onAsk(t('copy.askUpdate', { base: s?.base ?? wt.base }))}><Wrench /> {t('copy.update', { base: s?.base ?? wt.base })}</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => setEnd('discard')} className="text-destructive"><Trash2 /> {pr?.number || wt.pr ? t('copy.tidy') : t('copy.discard')}</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {end && s && <EndDialog session={session} st={s} what={end} onClose={() => setEnd(null)} onAsk={onAsk} />}
    </div>
  )
}

/** The end of a copy: open a PR, merge into the base here, or discard - committing first when something is left. */
function EndDialog({ session, st, what, onClose, onAsk }: { session: Session; st: CopyStatus; what: End; onClose: () => void; onAsk: (text: string) => void }) {
  const t = useT()
  const qc = useQueryClient()
  const [choice, setChoice] = React.useState<End>(what)
  const dirty = st.dirty ?? 0
  const [commitFirst, setCommitFirst] = React.useState(dirty > 0)
  const [msg, setMsg] = React.useState('')
  const [busy, setBusy] = React.useState<null | 'message' | 'go'>(null)
  const canPr = !!st.github && !st.fork && !st.pr
  const choices: End[] = [...(canPr ? (['pr'] as End[]) : []), ...(!st.pr ? (['merge'] as End[]) : []), 'discard']
  const propose = async (auto = false) => {
    setBusy('message')
    try {
      const m = (await codeApi.message(st.path)).message
      // proposed on opening: what the user typed meanwhile wins
      setMsg((cur) => (auto && cur.trim() ? cur : m))
    } catch (e) {
      toast.error(t('code.noMessage'), errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  React.useEffect(() => {
    if (dirty > 0 && choice !== 'discard' && !msg) void propose(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, when the window opens
  }, [])
  const go = async () => {
    setBusy('go')
    try {
      if (choice === 'discard') {
        await copyApi.remove(session.id, true)
        toast.success(t('copy.discarded'))
      } else if (choice === 'merge') {
        const r = await copyApi.merge(session.id, commitFirst && dirty ? msg.trim() : undefined)
        toast.success(t('copy.merged', { base: r.base }))
      } else {
        if (commitFirst && dirty) await codeApi.commit(st.path, msg.trim(), false)
        const out = await codeApi.pr(st.path)
        toast.success(t('code.prOpened'))
        if (st.github) openFileViewer(prPath({ full: st.github, n: out.number }))
      }
      void qc.invalidateQueries({ queryKey: ['code'] })
      void qc.invalidateQueries({ queryKey: ['sessions'] })
      onClose()
    } catch (e) {
      const conflict = isApiError(e, 'conflict')
      if (conflict) {
        onClose()
        onAsk(t('copy.askConflict', { base: st.base }))
        toast.error(t('copy.conflict', { base: st.base }))
      } else toast.error(t('code.failed'), errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  const lost = choice === 'discard' && (dirty > 0 || (st.ahead ?? 0) > 0)
  const needMsg = choice !== 'discard' && dirty > 0 && commitFirst && !msg.trim()
  const blocked = choice !== 'discard' && dirty > 0 && !commitFirst
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="md:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('copy.endTitle')}</DialogTitle>
          <DialogDescription>
            <Sensitive>{t('copy.endDesc', { branch: st.branch, base: st.base })}</Sensitive>
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-2">
          {choices.map((c) => (
            <label key={c} className={cn('flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2.5', choice === c && (c === 'discard' ? 'border-destructive/50 bg-destructive/5' : 'border-primary/50 bg-primary/[0.06]'))}>
              <input type="radio" name="copy-end" className="mt-1 accent-primary" checked={choice === c} onChange={() => setChoice(c)} />
              <span className="grid gap-0.5 leading-tight">
                <span className="flex items-center gap-1.5 text-sm font-medium">
                  {c === 'pr' ? <GitPullRequest className="size-3.5" /> : c === 'merge' ? <GitMerge className="size-3.5" /> : <Trash2 className="size-3.5" />}
                  {c === 'merge' ? t('copy.mergeInto', { base: st.base }) : c === 'pr' ? t('code.openPrBtn') : st.pr ? t('copy.tidy') : t('copy.discard')}
                  {c === (st.github && !st.fork ? 'pr' : 'merge') && <span className="rounded bg-primary/15 px-1 text-[10px] text-primary">{t('copy.advised')}</span>}
                </span>
                <span className="text-xs text-muted-foreground">{t(`copy.end.${c}`, { base: st.base })}</span>
              </span>
            </label>
          ))}
        </div>
        {choice !== 'discard' && dirty > 0 && (
          <div className="grid gap-2">
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={commitFirst} onCheckedChange={(v) => setCommitFirst(v === true)} />
              {t('copy.commitFirst', { count: dirty })}
            </label>
            {commitFirst && (
              <div className="relative">
                <Textarea value={msg} onChange={(e) => setMsg(e.target.value)} minRows={2} maxRows={8} placeholder={t('code.messagePh', { count: dirty })} className="pr-10 text-[13px]" />
                <Tooltip content={t('code.propose')}>
                  <Button variant="ghost" size="icon-sm" className="absolute top-1 right-1 size-7" aria-label={t('code.propose')} onClick={() => void propose()} disabled={!!busy}>
                    {busy === 'message' ? <Loader2 className="animate-spin" /> : <Sparkles className="size-3.5" />}
                  </Button>
                </Tooltip>
              </div>
            )}
          </div>
        )}
        {lost && <p className="text-xs text-destructive">{t('copy.lost', { files: dirty, commits: st.ahead ?? 0 })}</p>}
        {blocked && <p className="text-xs text-muted-foreground">{t('copy.commitNeeded')}</p>}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant={choice === 'discard' ? 'destructive' : 'default'} onClick={() => void go()} disabled={!!busy || needMsg || blocked} data-testid="copy-end-go">
            {busy === 'go' ? <Loader2 className="animate-spin" /> : <Check />}
            {choice === 'discard' ? (st.pr ? t('copy.tidy') : t('copy.discard')) : choice === 'merge' ? t('copy.merge') : t('code.openPrBtn')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** The branch of a session on a copy, beside its topic in the header. */
export function CopyMark({ session }: { session: Session }) {
  const t = useT()
  const wt = session.worktree
  if (!wt || wt.removed) return null
  return (
    <Tooltip content={t('copy.markTip', { base: wt.base })}>
      <span className="inline-flex min-w-0 shrink items-center gap-0.5 font-mono text-[11px] text-primary" data-testid="copy-mark">
        <GitBranch className="size-3 shrink-0" />
        <span className="truncate"><Sensitive>{wt.branch}</Sensitive></span>
      </span>
    </Tooltip>
  )
}
