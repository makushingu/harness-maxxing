// The PR view inside the file viewer (Viewer.tsx shows it for `mx-pr:` paths): a GitHub pull request read and acted on
// in Harness, laid out like the Changes view (same header, same file rows, same diff). Tabs Conversation / Files /
// Checks; at the bottom Comment · Approve · Request changes · Merge; "Work on this PR" and "Ask Claude to review"
// start a session on a separate copy of its branch (Code mode). Plan: plans/code-worktree-pr.md (lot 5).
import * as React from 'react'
import { create } from 'zustand'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import {
  ArrowUp, Bot, Check, ChevronDown, ChevronLeft, ChevronRight, CircleAlert, CircleDot, ExternalLink, FileQuestion, GitBranch, GitMerge, GitPullRequest, Hammer, Loader2, Maximize2, MessageSquare, Minimize2, MoreHorizontal, ShieldAlert, Trash2, X, XCircle,
} from 'lucide-react'
import {
  Badge, Button, CodeBlock, confirm, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, EmptyState, Segmented, Sensitive, Skeleton, Textarea, Tooltip, toast,
} from '@/components/ui'
import type { Components } from 'react-markdown'
import { Markdown } from '@/components/ui/markdown'
import { errorMessage } from '@/lib/api'
import { cn } from '@/lib/utils'
import { fmtRelative } from '@/lib/format'
import { useLang, useT } from '@/i18n'
import { placeSession, useSettings } from '@/lib/queries'
import { useFileViewer } from '@/features/files/viewerStore'
import { prefillDraft } from '@/pages/sessions/store'
import { DiffRows, diffRows, selected, useLineSelection } from './DiffRows'
import { checksState, parsePrPath, prApi, prKeys, prPath, usePull, type DraftComment, type PrFile, type PrRef, type Pull, type ReviewEvent } from './prApi'

type Props = { path: string; index: number; count: number; fullscreen: boolean; canFull: boolean; onFull: () => void; swipe: React.HTMLAttributes<HTMLDivElement> }

const STATUS_TONE: Record<string, string> = { A: 'text-success', D: 'text-destructive', R: 'text-primary', C: 'text-primary' }

// Line comments written in the Files tab wait here (per pull request) until the review is sent.
const useDrafts = create<{ by: Record<string, DraftComment[]>; add: (k: string, c: DraftComment) => void; drop: (k: string, i: number) => void; clear: (k: string) => void }>((set) => ({
  by: {},
  add: (k, c) => set((s) => ({ by: { ...s.by, [k]: [...(s.by[k] ?? []), c] } })),
  drop: (k, i) => set((s) => ({ by: { ...s.by, [k]: (s.by[k] ?? []).filter((_, j) => j !== i) } })),
  clear: (k) => set((s) => ({ by: { ...s.by, [k]: [] } })),
}))
const NO_DRAFTS: DraftComment[] = []

// Text written on GitHub (by anyone): pictures wait for a click, and code blocks stay code - no ```pr-review, ```git or
// ```infra block turns into a live card here.
const PLAIN: Components = {
  pre({ children }) {
    const child = React.Children.only(children) as React.ReactElement<{ children?: React.ReactNode }>
    const text = (function flat(n: React.ReactNode): string {
      return typeof n === 'string' ? n : Array.isArray(n) ? n.map(flat).join('') : React.isValidElement<{ children?: React.ReactNode }>(n) ? flat(n.props.children) : ''
    })(child?.props?.children).replace(/\n$/, '')
    return <CodeBlock code={text} className="my-2" />
  },
}

export function PrPane(props: Props) {
  const t = useT()
  const ref = parsePrPath(props.path)
  if (!ref) return <EmptyState icon={FileQuestion} title={t('pr.gone')} className="flex-1" />
  return <Pane at={ref} {...props} />
}

function Pane({ at, path, index, count, fullscreen, canFull, onFull, swipe }: Props & { at: PrRef }) {
  const t = useT()
  const { go, setList, show } = useFileViewer()
  const q = usePull(at.full, at.n)
  const pr = q.data

  // ← / → go through the PR then each of its files (like the Changes view)
  React.useEffect(() => {
    if (!pr) return
    // the first entry is the tab shown (or Files, from a file): going back with ← lands where the user was
    const head = at.path != null ? prPath({ full: at.full, n: at.n, tab: 'files' }) : path
    const all = [head, ...pr.files.map((f) => prPath({ full: at.full, n: at.n, path: f.path }))]
    if (useFileViewer.getState().list.join('\n') === all.join('\n')) return
    setList(all, Math.max(0, all.indexOf(path)))
  }, [pr, path, at.full, at.n, at.path, setList])

  const file = at.path != null ? pr?.files.find((f) => f.path === at.path) : undefined
  const back = () => show(prPath({ full: at.full, n: at.n, tab: 'files' }), useFileViewer.getState().list)

  return (
    <>
      <div className="flex h-12 shrink-0 items-center gap-1 border-b px-2 md:px-3">
        {at.path != null ? (
          <Tooltip content={t('pr.backToFiles')}>
            <Button variant="ghost" size="icon-sm" onClick={back} aria-label={t('pr.backToFiles')}>
              <ArrowUp />
            </Button>
          </Tooltip>
        ) : (
          <GitPullRequest className="ml-1 size-4 shrink-0 text-muted-foreground" />
        )}
        <div className="mr-1 ml-1 grid min-w-0 flex-1 leading-tight">
          <span className="truncate text-sm font-medium" data-testid="viewer-name">
            {at.path != null ? <Sensitive>{at.path.split('/').pop()}</Sensitive> : pr ? <Sensitive>{`#${pr.number} ${pr.title}`}</Sensitive> : `#${at.n}`}
          </span>
          <span className="truncate text-[11px] text-muted-foreground tabular-nums">
            {at.path != null ? <Sensitive>{`#${at.n} · ${at.path}`}</Sensitive> : pr && <Sensitive>{t('pr.sub', { author: pr.author.login, head: pr.head, base: pr.base, files: pr.files_total, add: pr.add, del: pr.del })}</Sensitive>}
          </span>
        </div>
        {at.path != null && count > 1 && (
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
        {pr && (
          <Tooltip content={t('pr.onGithub')}>
            <Button variant="ghost" size="icon-sm" asChild>
              <a href={pr.url} target="_blank" rel="noopener noreferrer" aria-label={t('pr.onGithub')}>
                <ExternalLink />
              </a>
            </Button>
          </Tooltip>
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
      <div className="relative flex min-h-0 flex-1 flex-col" {...(at.path != null ? swipe : {})}>
        {q.isPending ? (
          <div className="space-y-2 p-4">
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
          </div>
        ) : q.isError ? (
          <EmptyState icon={CircleAlert} title={errorMessage(q.error)} className="flex-1" />
        ) : at.path != null ? (
          file ? <PrFileBody pr={pr!} file={file} /> : <EmptyState icon={FileQuestion} title={t('code.fileGone')} className="flex-1" />
        ) : (
          <Overview pr={pr!} tab={at.tab} onTab={(tab) => show(prPath({ full: at.full, n: at.n, tab }), useFileViewer.getState().list)} onFile={(f) => show(prPath({ full: at.full, n: at.n, path: f.path }), useFileViewer.getState().list)} />
        )}
      </div>
      {pr && pr.state === 'open' && <ActionBar pr={pr} />}
    </>
  )
}

function StateBadge({ pr }: { pr: Pull }) {
  const t = useT()
  if (pr.state === 'merged') return <Badge variant="default"><GitMerge />{t('pr.state.merged')}</Badge>
  if (pr.state === 'closed') return <Badge variant="destructive"><XCircle />{t('pr.state.closed')}</Badge>
  return <Badge variant="success"><GitPullRequest />{pr.draft ? t('pr.state.draft') : t('pr.state.open')}</Badge>
}

function ChecksIcon({ pr, className }: { pr: Pull; className?: string }) {
  const s = checksState(pr.checks)
  if (s === 'failed') return <CircleAlert className={cn('text-destructive', className)} />
  if (s === 'pending') return <CircleDot className={cn('text-warning', className)} />
  if (s === 'ok') return <Check className={cn('text-success', className)} />
  return null
}

function Overview({ pr, tab, onTab, onFile }: { pr: Pull; tab: PrRef['tab']; onTab: (t: PrRef['tab']) => void; onFile: (f: PrFile) => void }) {
  const t = useT()
  const drafts = useDrafts((s) => s.by[`${pr.full}#${pr.number}`] ?? NO_DRAFTS)
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
        <StateBadge pr={pr} />
        {pr.outside && (
          <Tooltip content={t('pr.outsideTip')}>
            <Badge variant="warning"><ShieldAlert />{t('pr.outside')}</Badge>
          </Tooltip>
        )}
        {pr.fork && <Badge variant="muted">{t('pr.fork')}</Badge>}
        <Segmented
          size="sm"
          className="ml-auto"
          aria-label={t('pr.tabs')}
          value={tab}
          onChange={onTab}
          options={[
            { value: 'conversation', label: t('pr.tab.conversation'), icon: <MessageSquare className="size-3.5" /> },
            { value: 'files', label: `${t('pr.tab.files')} ${pr.files_total}${drafts.length ? ` · ${drafts.length}✎` : ''}` },
            { value: 'checks', label: t('pr.tab.checks'), icon: <ChecksIcon pr={pr} className="size-3.5" /> },
          ]}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3 md:p-4">
        {tab === 'conversation' ? <Conversation pr={pr} /> : tab === 'files' ? <FileList pr={pr} onFile={onFile} /> : <Checks pr={pr} />}
      </div>
    </div>
  )
}

function Conversation({ pr }: { pr: Pull }) {
  const t = useT()
  const lang = useLang()
  return (
    <div className="grid gap-3" data-testid="pr-conversation">
      {pr.outside && <p className="rounded-lg border border-warning/30 bg-warning/8 px-3 py-2 text-[13px]">{t('pr.outsideBanner')}</p>}
      <article className="rounded-lg border">
        <header className="flex items-center gap-2 border-b bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground">
          <Sensitive><span className="font-medium text-foreground">{pr.author.login}</span></Sensitive>
          <span>{fmtRelative(pr.created, lang)}</span>
          <span className="ml-auto inline-flex items-center gap-1 font-mono text-[11px]"><GitBranch className="size-3" /><Sensitive>{`${pr.head} → ${pr.base}`}</Sensitive></span>
        </header>
        <div className="px-3 py-2 text-[13px]">
          {pr.body.trim() ? <Markdown localImage={() => null} components={PLAIN}>{pr.body}</Markdown> : <span className="text-muted-foreground">{t('pr.noBody')}</span>}
        </div>
      </article>
      {pr.conversation.map((e) => (
        <article key={`${e.kind}-${e.id}`} className="rounded-lg border">
          <header className="flex items-center gap-2 border-b bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground">
            <Sensitive><span className="font-medium text-foreground">{e.author.login}</span></Sensitive>
            {e.kind === 'review' && e.state && <ReviewState state={e.state} />}
            <span className="ml-auto">{fmtRelative(e.at, lang)}</span>
          </header>
          {e.body.trim() && (
            <div className="px-3 py-2 text-[13px]">
              <Markdown localImage={() => null} components={PLAIN}>{e.body}</Markdown>
            </div>
          )}
        </article>
      ))}
      {pr.line_comments.length > 0 && <p className="text-xs text-muted-foreground">{t('pr.lineComments', { count: pr.line_comments.length })}</p>}
    </div>
  )
}

function ReviewState({ state }: { state: string }) {
  const t = useT()
  if (state === 'APPROVED') return <Badge variant="success"><Check />{t('pr.review.approved')}</Badge>
  if (state === 'CHANGES_REQUESTED') return <Badge variant="destructive">{t('pr.review.changes')}</Badge>
  return <Badge variant="muted">{t('pr.review.commented')}</Badge>
}

function FileList({ pr, onFile }: { pr: Pull; onFile: (f: PrFile) => void }) {
  const t = useT()
  const notes = (p: string) => pr.line_comments.filter((c) => c.path === p).length
  return (
    <section className="overflow-hidden rounded-lg border" data-testid="pr-files">
      <ul className="py-1">
        {pr.files.map((f) => (
          <li key={f.path} className="px-1.5">
            <button type="button" onClick={() => onFile(f)} className="flex w-full min-w-0 items-center gap-2 rounded-md px-1.5 py-1 text-left text-[13px] outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring max-md:py-2">
              <span className={cn('w-3 shrink-0 font-mono text-[11px] font-semibold', STATUS_TONE[f.status] ?? 'text-warning')}>{f.status}</span>
              <span className="min-w-0 truncate">
                <Sensitive>
                  {f.path.includes('/') && <span className="text-muted-foreground">{f.path.slice(0, f.path.lastIndexOf('/') + 1)}</span>}
                  {f.path.split('/').pop()}
                </Sensitive>
              </span>
              {notes(f.path) > 0 && (
                <span className="inline-flex shrink-0 items-center gap-0.5 text-[11px] text-muted-foreground">
                  <MessageSquare className="size-3" />
                  {notes(f.path)}
                </span>
              )}
              <span className="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums">
                <span className="text-success">+{f.add}</span> <span className="text-destructive">−{f.del}</span>
              </span>
            </button>
          </li>
        ))}
        {pr.files_total > pr.files.length && <li className="px-3 py-1 text-[11px] text-muted-foreground">{t('code.more', { count: pr.files_total - pr.files.length })}</li>}
      </ul>
    </section>
  )
}

function Checks({ pr }: { pr: Pull }) {
  const t = useT()
  if (!pr.checks.length) return <p className="text-[13px] text-muted-foreground">{t('code.noChecks')}</p>
  return (
    <ul className="grid gap-1" data-testid="pr-checks">
      {pr.checks.map((c, i) => {
        const failed = ['failure', 'timed_out', 'cancelled', 'action_required'].includes(c.conclusion || '')
        const done = c.status === 'completed' || c.conclusion != null
        return (
          <li key={i} className="flex items-center gap-2 rounded-md px-2 py-1 text-[13px]">
            {failed ? <CircleAlert className="size-4 text-destructive" /> : !done ? <Loader2 className="size-4 animate-spin text-warning" /> : <Check className="size-4 text-success" />}
            <Sensitive>{c.name}</Sensitive>
            {c.url && (
              <a href={c.url} target="_blank" rel="noopener noreferrer" className="ml-auto text-muted-foreground hover:text-foreground" aria-label={t('pr.onGithub')}>
                <ExternalLink className="size-3.5" />
              </a>
            )}
          </li>
        )
      })}
    </ul>
  )
}

// ---- one file: its diff, the comments on its lines, and a comment on the selected lines --------------------------

function PrFileBody({ pr, file }: { pr: Pull; file: PrFile }) {
  const t = useT()
  const key = `${pr.full}#${pr.number}`
  const drafts = useDrafts((s) => s.by[key] ?? NO_DRAFTS)
  const { sel, setSel, pick } = useLineSelection()
  const rows = React.useMemo(() => diffRows(file.hunks), [file.hunks])
  const [text, setText] = React.useState('')
  const comments = pr.line_comments.filter((c) => c.path === file.path)
  const add = () => {
    if (!sel || !text.trim()) return
    const { last } = selected(rows, sel)
    const line = last?.n ?? last?.o
    if (line == null) return
    useDrafts.getState().add(key, { path: file.path, line, side: last?.n != null ? 'RIGHT' : 'LEFT', body: text.trim() })
    setText('')
    setSel(null)
  }
  const below = (l: { o: number | null; n: number | null }) => {
    const here = comments.filter((c) => !c.outdated && (c.side === 'LEFT' ? c.line === l.o && l.n == null : c.line === l.n))
    const mine = drafts.map((d, i) => ({ d, i })).filter(({ d }) => d.path === file.path && (d.side === 'LEFT' ? d.line === l.o && l.n == null : d.line === l.n))
    if (!here.length && !mine.length) return null
    return (
      <div className="sticky left-0 grid w-[min(100%,46rem)] gap-1.5 border-y bg-card px-3 py-2 font-sans">
        {here.map((c) => (
          <div key={c.id} className="text-[13px]">
            <span className="mr-1.5 text-xs font-medium"><Sensitive>{c.author.login}</Sensitive></span>
            <Markdown localImage={() => null} components={PLAIN}>{c.body}</Markdown>
          </div>
        ))}
        {mine.map(({ d, i }) => (
          <div key={`d${i}`} className="flex items-start gap-2 rounded-md border border-dashed border-primary/40 bg-primary/5 px-2 py-1 text-[13px]">
            <Badge variant="muted">{t('pr.pending')}</Badge>
            <span className="min-w-0 flex-1 whitespace-pre-wrap">{d.body}</span>
            <Button variant="ghost" size="icon-sm" className="size-6" aria-label={t('pr.dropDraft')} onClick={() => useDrafts.getState().drop(key, i)}>
              <X className="size-3" />
            </Button>
          </div>
        ))}
      </div>
    )
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-1.5 text-[11px] text-muted-foreground">
        <span className={cn('font-mono font-semibold', STATUS_TONE[file.status] ?? 'text-warning')}>{file.status}</span>
        {file.old && <span className="truncate"><Sensitive>{t('code.renamedFrom', { path: file.old })}</Sensitive></span>}
        <span className="tabular-nums">
          <span className="text-success">+{file.add}</span> <span className="text-destructive">−{file.del}</span>
        </span>
      </div>
      {file.binary || !rows.length ? (
        <EmptyState icon={FileQuestion} title={file.binary ? t('code.binaryFile') : t('pr.noPatch')} className="flex-1" />
      ) : (
        <DiffRows rows={rows} sel={sel} onPick={pick} below={below} />
      )}
      {pr.state === 'open' &&
        (sel ? (
          <div className="flex items-end gap-2 border-t px-3 py-2">
            <Textarea autoFocus value={text} onChange={(e) => setText(e.target.value)} minRows={1} maxRows={6} placeholder={t('pr.lineCommentPh')} className="text-[13px]"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault()
                  add()
                }
              }}
            />
            <Button size="sm" onClick={add} disabled={!text.trim()}>{t('pr.addLineComment')}</Button>
          </div>
        ) : (
          rows.length > 0 && <p className="border-t px-3 py-1 text-[11px] text-muted-foreground max-md:hidden">{t('pr.selectHint')}</p>
        ))}
    </div>
  )
}

// ---- the bar at the bottom: comment, review, merge; work on it or have Claude review it ---------------------------

function ActionBar({ pr }: { pr: Pull }) {
  const t = useT()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { close } = useFileViewer()
  const { data: settings } = useSettings()
  const key = `${pr.full}#${pr.number}`
  const drafts = useDrafts((s) => s.by[key] ?? NO_DRAFTS)
  const [text, setText] = React.useState('')
  const [busy, setBusy] = React.useState<string | null>(null)
  const [method, setMethod] = React.useState(pr.methods[0] ?? 'squash')
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: prKeys.one(pr.full, pr.number) })
    void qc.invalidateQueries({ queryKey: ['git', 'pulls'] })
    void qc.invalidateQueries({ queryKey: ['code'] })
  }
  const run = async (what: string, f: () => Promise<unknown>, done: string) => {
    setBusy(what)
    try {
      await f()
      toast.success(done)
      refresh()
      return true
    } catch (e) {
      toast.error(t('code.failed'), errorMessage(e))
      return false
    } finally {
      setBusy(null)
    }
  }
  const review = async (event: ReviewEvent) => {
    if (event === 'COMMENT' && !drafts.length) {
      if (await run('comment', () => prApi.comment(pr.full, pr.number, text.trim()), t('pr.commented'))) setText('')
      return
    }
    const ok = await run(event, () => prApi.review(pr.full, pr.number, event, text.trim(), drafts), event === 'APPROVE' ? t('pr.approved') : event === 'REQUEST_CHANGES' ? t('pr.changesAsked') : t('pr.commented'))
    if (ok) {
      setText('')
      useDrafts.getState().clear(key)
    }
  }
  const failed = checksState(pr.checks) === 'failed'
  const blocked = pr.draft ? t('pr.blocked.draft') : pr.mergeable === false ? t('pr.blocked.conflict') : null
  const merge = async () => {
    const ok = await confirm({ title: t('pr.mergeConfirm', { n: pr.number, base: pr.base }), description: failed ? t('pr.mergeFailedChecks') : t(`pr.method.${method}Desc`, { base: pr.base }), confirmText: t('pr.merge'), destructive: failed })
    if (ok) await run('merge', () => prApi.merge(pr.full, pr.number, method, pr.head_sha), t('pr.merged'))
  }
  const closePr = async () => {
    if (await confirm({ title: t('pr.closeConfirm', { n: pr.number }), confirmText: t('pr.close'), destructive: true })) await run('close', () => prApi.close(pr.full, pr.number), t('pr.closed'))
  }
  const session = async (reviewMode: boolean) => {
    setBusy(reviewMode ? 'review' : 'work')
    try {
      const msg = reviewMode ? t('pr.reviewPrompt', { n: pr.number, title: pr.title, base: pr.base, repo: pr.full }) : undefined
      const s = await prApi.session(pr.full, pr.number, reviewMode, msg)
      // working on it: the composer starts with what the PR is, the user says what to do
      if (!reviewMode) prefillDraft(s.id, t('pr.workDraft', { n: pr.number, title: pr.title, repo: pr.full, head: pr.head, base: pr.base }))
      placeSession(qc, s)
      void qc.invalidateQueries({ queryKey: ['sessions'] })
      close()
      navigate(`/sessions/${s.id}`)
    } catch (e) {
      toast.error(t('code.failed'), errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  const spin = (k: string, icon: React.ReactNode) => (busy === k ? <Loader2 className="animate-spin" /> : icon)
  const code = !!settings?.code_mode
  const noClone = !pr.local_paths.length
  return (
    <div className="space-y-2 border-t px-3 py-2.5" data-testid="pr-actions">
      <Textarea value={text} onChange={(e) => setText(e.target.value)} minRows={1} maxRows={8} placeholder={drafts.length ? t('pr.reviewPh', { count: drafts.length }) : t('pr.commentPh')} className="text-[13px]"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && text.trim()) {
            e.preventDefault()
            void review('COMMENT')
          }
        }}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" onClick={() => void review('COMMENT')} disabled={!!busy || (!text.trim() && !drafts.length)}>
          {spin('comment', <MessageSquare />)}
          {drafts.length ? t('pr.sendReview', { count: drafts.length }) : t('pr.comment')}
        </Button>
        {pr.can_write && (
          <>
            <Button size="sm" variant="outline" onClick={() => void review('APPROVE')} disabled={!!busy}>
              {spin('APPROVE', <Check />)}
              {t('pr.approve')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void review('REQUEST_CHANGES')} disabled={!!busy || (!text.trim() && !drafts.length)}>
              {spin('REQUEST_CHANGES', null)}
              {t('pr.requestChanges')}
            </Button>
          </>
        )}
        <div className="ml-auto flex items-center gap-1">
          {pr.can_write && (
            <Tooltip content={blocked ?? (failed ? t('pr.checksFailed') : t(`pr.method.${method}Desc`, { base: pr.base }))}>
              <div className="flex">
                <Button size="sm" className={cn(pr.methods.length > 1 && 'rounded-r-none')} onClick={() => void merge()} disabled={!!busy || !!blocked} data-testid="pr-merge">
                  {spin('merge', <GitMerge />)}
                  {t(`pr.method.${method}`)}
                </Button>
                {pr.methods.length > 1 && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button size="sm" className="rounded-l-none border-l border-primary-foreground/20 px-2" aria-label={t('pr.methodPick')} disabled={!!busy || !!blocked}>
                        <ChevronDown />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {pr.methods.map((m) => (
                        <DropdownMenuItem key={m} onSelect={() => setMethod(m)}>
                          {t(`pr.method.${m}`)}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </div>
            </Tooltip>
          )}
          {pr.can_write && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="icon-sm" variant="ghost" aria-label={t('code.moreActions')} disabled={!!busy}>
                  {busy === 'close' ? <Loader2 className="animate-spin" /> : <MoreHorizontal />}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => void closePr()} className="text-destructive">
                  <Trash2 /> {t('pr.close')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t pt-2">
        <span className="text-[11px] text-muted-foreground max-md:hidden">{t('pr.withClaude')}</span>
        <Tooltip content={!code ? t('pr.needCodeMode') : noClone ? t('pr.needClone', { repo: pr.full }) : t('pr.workTip')}>
          <span>
            <Button size="sm" variant="outline" onClick={() => void session(false)} disabled={!!busy || !code || noClone} data-testid="pr-work">
              {spin('work', <Hammer />)}
              {t('pr.work')}
            </Button>
          </span>
        </Tooltip>
        <Tooltip content={!code ? t('pr.needCodeMode') : noClone ? t('pr.needClone', { repo: pr.full }) : t('pr.askReviewTip')}>
          <span>
            <Button size="sm" variant="outline" onClick={() => void session(true)} disabled={!!busy || !code || noClone} data-testid="pr-review">
              {spin('review', <Bot />)}
              {t('pr.askReview')}
            </Button>
          </span>
        </Tooltip>
      </div>
      {pr.outside && <p className="text-[11px] text-muted-foreground">{t('pr.outsideWork')}</p>}
    </div>
  )
}
