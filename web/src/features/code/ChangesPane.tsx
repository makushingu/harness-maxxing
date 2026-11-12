// The Changes view inside the file viewer (Viewer.tsx shows it for `mx-changes:` paths): the list of what a
// session changed, grouped by repository (branch, pull request, checks, commit / push / PR), and the diff of one
// file. ← / → go through the files of the list, ↑ comes back to it. Plan: plans/code-in-session.md (lot 1).
import * as React from 'react'
import { create } from 'zustand'
import { useQueryClient } from '@tanstack/react-query'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import {
  ArrowUp, Check, ChevronDown, ChevronLeft, ChevronRight, CircleAlert, CircleDot, ExternalLink, FileQuestion, GitBranch, GitCompare, GitPullRequest, Loader2, Maximize2, MessageSquareQuote, Minimize2, Plus, Sparkles, Undo2, Upload, X,
} from 'lucide-react'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger, EmptyState, Input, Select, Sensitive, Skeleton, Textarea, Tooltip, toast } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { useFileViewer } from '@/features/files/viewerStore'
import {
  changesPath, codeApi, parseChangesPath, quoteInSession, useChanges, useFileDiff, useRepoStatus, type ChangedFile, type ChangesRef, type ChangesScope, type DiffLine, type RepoChanges, type Undo,
} from './api'

const SCOPES: ChangesScope[] = ['turn', 'session', 'uncommitted', 'branch']
/** How long "Undone · Restore" stays (Romain's choice: no confirmation, a way back instead). */
const UNDO_MS = 10_000

type Props = { path: string; index: number; count: number; fullscreen: boolean; canFull: boolean; onFull: () => void; swipe: React.HTMLAttributes<HTMLDivElement> }

export function ChangesPane({ path, index, count, fullscreen, canFull, onFull, swipe }: Props) {
  const t = useT()
  const ref = parseChangesPath(path)
  if (!ref) return <EmptyState icon={FileQuestion} title={t('code.gone')} className="flex-1" />
  return <Pane at={ref} path={path} index={index} count={count} fullscreen={fullscreen} canFull={canFull} onFull={onFull} swipe={swipe} />
}

function Pane({ at, path, index, count, fullscreen, canFull, onFull, swipe }: Props & { at: ChangesRef }) {
  const t = useT()
  const { go, setList, show } = useFileViewer()
  const q = useChanges(at.sid, at.scope, at.n)
  const repos = React.useMemo(() => q.data?.repos ?? [], [q.data])
  const listPath = changesPath({ sid: at.sid, scope: at.scope, n: at.n })

  // The viewer browses the list then every file of it (← / →).
  React.useEffect(() => {
    if (!q.data) return
    const all = [listPath, ...repos.flatMap((r) => r.files.map((f) => changesPath({ sid: at.sid, scope: at.scope, n: at.n, root: r.root, path: f.path })))]
    const { list } = useFileViewer.getState()
    if (list.join('\n') === all.join('\n')) return
    setList(all, Math.max(0, all.indexOf(path)))
  }, [q.data, repos, listPath, path, at.sid, at.scope, at.n, setList])

  const repo = at.root ? repos.find((r) => r.root === at.root) : undefined
  const file = repo?.files.find((f) => f.path === at.path)
  const multi = count > 1
  const toFile = (r: RepoChanges, f: ChangedFile) => show(changesPath({ ...at, root: r.root, path: f.path }), useFileViewer.getState().list)
  const totals = repos.reduce((s, r) => ({ files: s.files + r.files.length + (r.more || 0), add: s.add + r.add, del: s.del + r.del }), { files: 0, add: 0, del: 0 })

  return (
    <>
      <div className="flex h-12 shrink-0 items-center gap-1 border-b px-2 md:px-3">
        {at.root ? (
          <Tooltip content={t('code.backToList')}>
            <Button variant="ghost" size="icon-sm" onClick={() => show(listPath, useFileViewer.getState().list)} aria-label={t('code.backToList')} data-testid="changes-up">
              <ArrowUp />
            </Button>
          </Tooltip>
        ) : (
          <GitCompare className="ml-1 size-4 shrink-0 text-muted-foreground" />
        )}
        <div className="mr-1 ml-1 grid min-w-0 flex-1 leading-tight">
          <span className="truncate text-sm font-medium" data-testid="viewer-name">
            {at.path ? <Sensitive>{at.path.split('/').pop()}</Sensitive> : t('code.title')}
          </span>
          <span className="truncate text-[11px] text-muted-foreground tabular-nums">
            {at.path ? (
              <Sensitive>{`${repo?.name ?? ''} · ${at.path}`}</Sensitive>
            ) : (
              q.data && t('code.totals', { count: totals.files, add: totals.add, del: totals.del })
            )}
          </span>
        </div>
        {!at.root && (
          <Select
            value={at.scope}
            onValueChange={(v) => show(changesPath({ sid: at.sid, scope: v as ChangesScope, n: at.n }))}
            options={SCOPES.filter((s) => s !== 'turn' || at.n != null).map((s) => ({ value: s, label: t(`code.scope.${s}`) }))}
            aria-label={t('code.scopeLabel')}
            className="h-8 w-auto max-md:h-10"
          />
        )}
        {at.root && multi && (
          <>
            <Button variant="ghost" size="icon-sm" onClick={() => go(-1)} aria-label={t('files.prev')}>
              <ChevronLeft />
            </Button>
            <span className="text-[11px] text-muted-foreground tabular-nums max-md:hidden">{`${index} / ${count - 1}`}</span>
            <Button variant="ghost" size="icon-sm" onClick={() => go(1)} aria-label={t('files.next')}>
              <ChevronRight />
            </Button>
          </>
        )}
        {canFull && (
          <Tooltip content={fullscreen ? t('viewer.panel') : t('viewer.fullscreen')}>
            <Button variant="ghost" size="icon-sm" onClick={onFull} aria-label={fullscreen ? t('viewer.panel') : t('viewer.fullscreen')}>
              {fullscreen ? <Minimize2 /> : <Maximize2 />}
            </Button>
          </Tooltip>
        )}
        <DialogPrimitive.Close asChild>
          <Button variant="ghost" size="icon-sm" aria-label={t('common.close')}>
            <X />
          </Button>
        </DialogPrimitive.Close>
      </div>
      <div className="relative flex min-h-0 flex-1 flex-col" {...(at.root ? swipe : {})}>
        {q.isPending ? (
          <div className="space-y-2 p-4">
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
          </div>
        ) : q.isError ? (
          <EmptyState icon={CircleAlert} title={errorMessage(q.error)} className="flex-1" />
        ) : at.root ? (
          repo && file ? (
            <FileBody sid={at.sid} repo={repo} file={file} />
          ) : (
            <EmptyState icon={FileQuestion} title={t('code.fileGone')} className="flex-1" />
          )
        ) : repos.length === 0 ? (
          <EmptyState icon={GitCompare} title={t(`code.none.${at.scope}`)} className="flex-1" />
        ) : (
          <div className="min-h-0 flex-1 space-y-4 overflow-auto p-3 md:p-4" data-testid="changes-list">
            {repos.map((r) => (
              <RepoBlock key={r.root} sid={at.sid} scope={at.scope} repo={r} onOpen={(f) => toFile(r, f)} />
            ))}
          </div>
        )}
      </div>
      <UndoBarView />
    </>
  )
}

function useRefresh() {
  const qc = useQueryClient()
  return React.useCallback(() => void qc.invalidateQueries({ queryKey: ['code'] }), [qc])
}

// "Undone · Restore" bar at the bottom of the view for 10 s (no confirmation, Romain 12/11). A toast's button cannot
// be clicked while the viewer (a modal dialog) is open, and the bar survives ← / → (the pane remounts per path).
type UndoBar = { id: number; label: string; back: Undo[] }
const useUndoBar = create<{ bar: UndoBar | null; set: (b: UndoBar | null) => void }>((set) => ({ bar: null, set: (bar) => set({ bar }) }))

/** Puts files back, then offers the bar. */
function useRestore() {
  const t = useT()
  const refresh = useRefresh()
  return React.useCallback(
    async (repo: RepoChanges, paths: string[], label: string) => {
      try {
        const out = await codeApi.restore(repo.root, repo.pre, paths)
        refresh()
        useUndoBar.getState().set({ id: Date.now(), label, back: [{ root: repo.root, undo: out.undo }] })
      } catch (e) {
        toast.error(t('code.failed'), errorMessage(e))
      }
    },
    [t, refresh],
  )
}

function UndoBarView() {
  const t = useT()
  const refresh = useRefresh()
  const { bar, set } = useUndoBar()
  React.useEffect(() => {
    if (!bar) return
    const id = window.setTimeout(() => useUndoBar.getState().bar?.id === bar.id && set(null), UNDO_MS)
    return () => window.clearTimeout(id)
  }, [bar, set])
  if (!bar) return null
  return (
    <div role="status" className="flex items-center gap-2 border-t bg-muted/60 px-3 py-1.5 text-[13px]" data-testid="undo-bar">
      <Undo2 className="size-3.5 shrink-0 text-muted-foreground" />
      <span className="min-w-0 truncate">
        {t('code.undone')} · <Sensitive>{bar.label}</Sensitive>
      </span>
      <Button
        size="sm"
        variant="outline"
        className="ml-auto h-7"
        onClick={() => {
          set(null)
          void codeApi.undo(bar.back).then(refresh, (e) => toast.error(t('code.failed'), errorMessage(e)))
        }}
      >
        {t('code.restoreBack')}
      </Button>
    </div>
  )
}

const STATUS_TONE: Record<string, string> = { A: 'text-success', D: 'text-destructive', R: 'text-primary', C: 'text-primary' }

function RepoBlock({ sid, scope, repo, onOpen }: { sid: string; scope: ChangesScope; repo: RepoChanges; onOpen: (f: ChangedFile) => void }) {
  const t = useT()
  const restore = useRestore()
  const st = useRepoStatus(repo.root, !repo.error)
  const paths = (fs: ChangedFile[]) => fs.flatMap((f) => (f.old ? [f.path, f.old] : [f.path]))
  return (
    <section className="overflow-hidden rounded-lg border" data-testid="changes-repo">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b bg-muted/30 px-3 py-2">
        <span className="text-sm font-medium">
          <Sensitive>{repo.name}</Sensitive>
        </span>
        <BranchChip repo={repo} st={st.data} />
        {st.data?.pr ? <PrBadge pr={st.data.pr} checks={st.data.checks} /> : null}
        <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
          <span className="text-success">+{repo.add}</span> <span className="text-destructive">−{repo.del}</span>
        </span>
        {repo.files.length > 0 && !repo.error && (
          <Tooltip content={t('code.undoAllTip')}>
            <Button variant="ghost" size="icon-sm" className="size-7" aria-label={t('code.undoAll')} onClick={() => void restore(repo, paths(repo.files), repo.name)} disabled={!!repo.more}>
              <Undo2 className="size-3.5" />
            </Button>
          </Tooltip>
        )}
      </div>
      {repo.error && <p className="px-3 py-2 text-xs text-destructive">{repo.error}</p>}
      {repo.approx && <p className="px-3 pt-2 text-[11px] text-muted-foreground">{t('code.approx')}</p>}
      <ul className="py-1">
        {repo.files.map((f) => (
          <li key={f.path} className="group/file flex items-center gap-2 px-1.5">
            <button
              type="button"
              onClick={() => onOpen(f)}
              className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-1 text-left text-[13px] outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring max-md:py-2"
              data-testid="changes-file"
            >
              <span className={cn('w-3 shrink-0 font-mono text-[11px] font-semibold', STATUS_TONE[f.status] ?? 'text-warning')}>{f.status}</span>
              <span className="min-w-0 truncate">
                <Sensitive>
                  {f.path.includes('/') && <span className="text-muted-foreground">{f.path.slice(0, f.path.lastIndexOf('/') + 1)}</span>}
                  {f.path.split('/').pop()}
                </Sensitive>
              </span>
              <span className="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums">
                {f.binary ? t('code.binary') : (
                  <>
                    <span className="text-success">+{f.add}</span> <span className="text-destructive">−{f.del}</span>
                  </>
                )}
              </span>
            </button>
            <Tooltip content={t('code.undoFile')}>
              <Button
                variant="ghost"
                size="icon-sm"
                className="size-7 opacity-0 group-hover/file:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100"
                aria-label={t('code.undoFile')}
                onClick={() => void restore(repo, paths([f]), f.path)}
              >
                <Undo2 className="size-3.5" />
              </Button>
            </Tooltip>
          </li>
        ))}
        {!!repo.more && <li className="px-3 py-1 text-[11px] text-muted-foreground">{t('code.more', { count: repo.more })}</li>}
      </ul>
      {!repo.error && st.data && <GitActions sid={sid} scope={scope} repo={repo} st={st.data} />}
    </section>
  )
}

function BranchChip({ repo, st }: { repo: RepoChanges; st?: { branch: string | null; ahead: number; behind: number; upstream: string | null } }) {
  const t = useT()
  const b = st ?? repo
  return (
    <span className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
      <GitBranch className="size-3" />
      <Sensitive>{b.branch ?? t('code.detached')}</Sensitive>
      {!!b.ahead && <span title={t('code.ahead', { count: b.ahead })}>↑{b.ahead}</span>}
      {!!b.behind && <span title={t('code.behind', { count: b.behind })}>↓{b.behind}</span>}
    </span>
  )
}

function PrBadge({ pr, checks }: { pr: { number: number; url: string; draft: boolean }; checks: { total: number; ok: number; failed: number; pending: number } | null }) {
  const t = useT()
  const tone = !checks || !checks.total ? 'text-muted-foreground' : checks.failed ? 'text-destructive' : checks.pending ? 'text-warning' : 'text-success'
  const tip = checks?.total ? t('code.checks', { ok: checks.ok, total: checks.total, failed: checks.failed, pending: checks.pending }) : t('code.noChecks')
  return (
    <Tooltip content={tip}>
      <a href={pr.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-[11px] hover:underline" data-testid="changes-pr">
        <GitPullRequest className="size-3" />#{pr.number}
        {pr.draft && <span className="text-muted-foreground">{t('code.draft')}</span>}
        {checks?.total ? checks.failed ? <CircleAlert className={cn('size-3', tone)} /> : checks.pending ? <CircleDot className={cn('size-3', tone)} /> : <Check className={cn('size-3', tone)} /> : null}
        <ExternalLink className="size-3 text-muted-foreground" />
      </a>
    </Tooltip>
  )
}

type Act = 'commit' | 'push' | 'pr'

/** Commit (message proposed on demand: ✨, or a click on Commit with an empty message), push, pull request, new branch. */
function GitActions({ repo, st }: { sid: string; scope: ChangesScope; repo: RepoChanges; st: NonNullable<ReturnType<typeof useRepoStatus>['data']> }) {
  const t = useT()
  const refresh = useRefresh()
  const [msg, setMsg] = React.useState('')
  const [busy, setBusy] = React.useState<null | 'message' | Act | 'branch'>(null)
  const [branching, setBranching] = React.useState(false)
  const [branch, setBranch] = React.useState('')
  const box = React.useRef<HTMLTextAreaElement>(null)

  const propose = async () => {
    setBusy('message')
    try {
      setMsg((await codeApi.message(repo.root)).message)
      box.current?.focus()
    } catch (e) {
      toast.error(t('code.noMessage'), errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  const run = async (what: Act, f: () => Promise<unknown>, done: string) => {
    setBusy(what)
    try {
      await f()
      refresh()
      toast.success(done) // a new pull request shows as the repository's badge (its link)
      return true
    } catch (e) {
      toast.error(t('code.failed'), errorMessage(e))
      return false
    } finally {
      setBusy(null)
    }
  }
  const commit = async (then: Act) => {
    if (!msg.trim()) return void propose()
    const ok = await run('commit', () => codeApi.commit(repo.root, msg.trim(), then !== 'commit'), then === 'commit' ? t('code.committed') : t('code.committedPushed'))
    if (!ok) return
    setMsg('')
    if (then === 'pr') await run('pr', () => codeApi.pr(repo.root), t('code.prOpened'))
  }
  const newBranch = async () => {
    const name = branch.trim()
    if (!name) return
    setBusy('branch')
    try {
      await codeApi.branch(repo.root, name)
      refresh()
      setBranching(false)
      setBranch('')
    } catch (e) {
      toast.error(t('code.failed'), errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  const canPush = !!st.branch && (st.ahead > 0 || !st.upstream) && st.dirty === 0
  const canPr = !!st.github && !!st.branch && !st.pr && st.dirty === 0 && !!st.upstream && !['main', 'master'].includes(st.branch)
  const spin = (k: typeof busy) => (busy === k ? <Loader2 className="animate-spin" /> : null)

  return (
    <div className="space-y-2 border-t px-3 py-2.5">
      {st.dirty > 0 && (
        <div className="relative">
          <Textarea
            ref={box}
            value={msg}
            onChange={(e) => setMsg(e.target.value)}
            minRows={1}
            maxRows={8}
            placeholder={t('code.messagePh', { count: st.dirty })}
            className="pr-10 text-[13px]"
            data-testid="commit-message"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault()
                void commit('commit')
              }
            }}
          />
          <Tooltip content={t('code.propose')}>
            <Button variant="ghost" size="icon-sm" className="absolute top-1 right-1 size-7" aria-label={t('code.propose')} onClick={() => void propose()} disabled={!!busy}>
              {busy === 'message' ? <Loader2 className="animate-spin" /> : <Sparkles className="size-3.5" />}
            </Button>
          </Tooltip>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {st.dirty > 0 && (
          <div className="flex">
            <Button size="sm" className="rounded-r-none" onClick={() => void commit('commit')} disabled={!!busy} data-testid="commit">
              {spin('commit')}
              {msg.trim() ? t('code.commit') : t('code.commitPropose')}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm" className="rounded-l-none border-l border-primary-foreground/20 px-2" aria-label={t('code.moreActions')} disabled={!!busy}>
                  <ChevronDown />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuItem onSelect={() => void commit('commit')}>{t('code.commit')}</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => void commit('push')} disabled={!st.branch}>{t('code.commitPush')}</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => void commit('pr')} disabled={!st.github || !st.branch}>{t('code.commitPr')}</DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => setBranching(true)}>{t('code.newBranch')}</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
        {canPush && (
          <Button size="sm" variant="outline" onClick={() => void run('push', () => codeApi.push(repo.root), t('code.pushed'))} disabled={!!busy} data-testid="push">
            {spin('push') ?? <Upload />}
            {st.ahead > 0 ? t('code.pushN', { count: st.ahead }) : t('code.push')}
          </Button>
        )}
        {canPr && (
          <Button size="sm" variant="outline" onClick={() => void run('pr', () => codeApi.pr(repo.root), t('code.prOpened'))} disabled={!!busy} data-testid="open-pr">
            {spin('pr') ?? <GitPullRequest />}
            {t('code.openPrBtn')}
          </Button>
        )}
        {st.dirty === 0 && !canPush && !canPr && <span className="text-[11px] text-muted-foreground">{st.pr ? t('code.upToDatePr') : t('code.clean')}</span>}
        {st.dirty === 0 && (
          <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setBranching((b) => !b)}>
            <Plus />
            {t('code.newBranch')}
          </Button>
        )}
      </div>
      {branching && (
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            void newBranch()
          }}
        >
          <Input autoFocus value={branch} onChange={(e) => setBranch(e.target.value)} placeholder={t('code.branchPh')} className="h-8 font-mono text-[13px]" />
          <Button size="sm" type="submit" disabled={!branch.trim() || !!busy}>
            {spin('branch')}
            {t('code.create')}
          </Button>
        </form>
      )}
      {st.github_error && <p className="text-[11px] text-muted-foreground">{st.github_error}</p>}
    </div>
  )
}

// ---- one file ---------------------------------------------------------------------------------------------------

function FileBody({ sid, repo, file }: { sid: string; repo: RepoChanges; file: ChangedFile }) {
  const t = useT()
  const [full, setFull] = React.useState(false)
  const d = useFileDiff(repo.root, repo.pre, repo.post, file.path, file.old, full)
  const restore = useRestore()
  const { close } = useFileViewer()
  // Selected lines (index in the flat list of rows): click a line number, shift-click to extend.
  const [sel, setSel] = React.useState<{ a: number; b: number } | null>(null)
  const rows = React.useMemo(() => {
    const out: ({ kind: 'head'; text: string } | { kind: 'line'; l: DiffLine })[] = []
    for (const h of d.data?.hunks ?? []) {
      out.push({ kind: 'head', text: h.head })
      for (const l of h.lines) out.push({ kind: 'line', l })
    }
    return out
  }, [d.data])
  const pick = (i: number, ext: boolean) => setSel((s) => (ext && s ? { a: Math.min(s.a, i), b: Math.max(s.b, i) } : s && s.a === i && s.b === i ? null : { a: i, b: i }))
  const ask = () => {
    if (!sel) return
    const lines = rows.slice(sel.a, sel.b + 1).flatMap((r) => (r.kind === 'line' ? [r.l] : []))
    const nums = lines.map((l) => l.n ?? l.o).filter((x): x is number => x != null)
    const range = nums.length ? (nums[0] === nums[nums.length - 1] ? `${nums[0]}` : `${nums[0]}-${nums[nums.length - 1]}`) : ''
    const where = `${repo.root}/${file.path}${range ? `:${range}` : ''}`
    quoteInSession(sid, `${where}\n\`\`\`diff\n${lines.map((l) => `${l.t}${l.s}`).join('\n')}\n\`\`\``)
    close()
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-1.5 text-[11px] text-muted-foreground">
        <span className={cn('font-mono font-semibold', STATUS_TONE[file.status] ?? 'text-warning')}>{file.status}</span>
        {file.old && (
          <span className="truncate">
            <Sensitive>{t('code.renamedFrom', { path: file.old })}</Sensitive>
          </span>
        )}
        <span className="tabular-nums">
          <span className="text-success">+{file.add}</span> <span className="text-destructive">−{file.del}</span>
        </span>
        <div className="ml-auto flex items-center gap-1">
          {sel && (
            <Button size="sm" variant="outline" className="h-7" onClick={ask} data-testid="ask-claude">
              <MessageSquareQuote />
              {t('code.ask')}
            </Button>
          )}
          <Button size="sm" variant="ghost" className="h-7" onClick={() => void restore(repo, file.old ? [file.path, file.old] : [file.path], file.path)} data-testid="undo-file">
            <Undo2 />
            {t('code.undoFile')}
          </Button>
        </div>
      </div>
      {d.isPending ? (
        <div className="space-y-1.5 p-4">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-4" style={{ width: `${40 + ((i * 37) % 55)}%` }} />
          ))}
        </div>
      ) : d.isError ? (
        <EmptyState icon={CircleAlert} title={errorMessage(d.error)} className="flex-1" />
      ) : d.data.binary ? (
        <EmptyState icon={FileQuestion} title={t('code.binaryFile')} className="flex-1" />
      ) : rows.length === 0 ? (
        <EmptyState icon={GitCompare} title={t('code.noDiff')} className="flex-1" />
      ) : (
        <div className="min-h-0 flex-1 overflow-auto font-mono text-[12px] leading-[1.6]" data-testid="file-diff">
          <div className="min-w-max">
            {rows.map((r, i) =>
              r.kind === 'head' ? (
                <div key={i} className="sticky left-0 bg-primary/6 px-3 py-0.5 text-[11px] text-muted-foreground">
                  {r.text}
                </div>
              ) : (
                <div
                  key={i}
                  className={cn(
                    'flex',
                    r.l.t === '+' && 'bg-success/12',
                    r.l.t === '-' && 'bg-destructive/12',
                    sel && i >= sel.a && i <= sel.b && 'ring-1 ring-primary/60 ring-inset bg-primary/10',
                  )}
                >
                  <button
                    type="button"
                    tabIndex={-1}
                    onClick={(e) => pick(i, e.shiftKey)}
                    className="flex shrink-0 cursor-pointer text-right text-muted-foreground/70 select-none hover:text-foreground"
                    aria-label={t('code.selectLine')}
                  >
                    <span className="w-10 pr-1.5">{r.l.o ?? ''}</span>
                    <span className="w-10 pr-1.5">{r.l.n ?? ''}</span>
                  </button>
                  <span className={cn('w-4 shrink-0 text-center select-none', r.l.t === '+' ? 'text-success' : r.l.t === '-' ? 'text-destructive' : 'text-muted-foreground')}>{r.l.t === ' ' ? '' : r.l.t}</span>
                  <span className="pr-4 whitespace-pre">{r.l.s || ' '}</span>
                </div>
              ),
            )}
          </div>
          {d.data.cut && (
            <button type="button" onClick={() => setFull(true)} className="sticky left-0 px-3 py-2 font-sans text-xs text-primary hover:underline">
              {t('code.showAll', { count: d.data.lines })}
            </button>
          )}
        </div>
      )}
      {!sel && rows.length > 0 && <p className="border-t px-3 py-1 text-[11px] text-muted-foreground max-md:hidden">{t('code.selectHint')}</p>}
    </div>
  )
}
