// Feature page "Git & GitHub" (/git, Settings -> Features -> git_page). Second-level sidebar: the sources (this server,
// one per GitHub account) are heads that fold, each with its repositories under it, most recent first. Nothing is shown
// beside the list until a repository is picked. A repository: graph of branches and commits, commit details, pull requests (a click opens the
// PR view), the separate copies of a clone (Code mode), Server | GitHub switch when it has both sides.
// The repository shown is in the URL (?repo=<path or github:owner/name>), so a chat block can link to it.
import * as React from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown, ArrowUp, ChevronRight, ExternalLink, FolderGit2, GitBranch, GitPullRequest, KeyRound, Link2, Lock, MessageSquarePlus, PencilLine,
  RefreshCw, Server, TriangleAlert,
} from 'lucide-react'
import { gitKeys, refreshGitRepos, useGitGraph, useGitPulls, useGitRepos, useSettings } from '@/lib/queries'
import { useCopies } from '@/features/code/copyApi'
import { openPr } from '@/features/code/prApi'
import type { GitHubRepo, GitLocalRepo, GitOverview, GitPermission } from '@/lib/types'
import { errorMessage } from '@/lib/api'
import { fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { Badge, Button, EmptyState, Segmented, Sheet, SheetBody, SheetContent, SheetTitle, Skeleton } from '@/components/ui'
import { useContextMenu } from '@/components/ui/context-menu'
import { DropdownMenuItem } from '@/components/ui/dropdown-menu'
import { useCompact, useMediaQuery } from '@/stores/media'
import { Page, PageHeader, useDocumentTitle } from '@/components/shell/Page'
import { PageList } from '@/components/shell/PageList'
import { openPageList } from '@/components/shell/TouchNav'
import { GitGraph, commitUrl, pushedShas } from './GitGraph'
import { Github } from './GithubMark'
import { CommitDetail } from './CommitDetail'
import { GitSessionDialog } from './NewSession'

const PERM_TONE: Record<GitPermission, string> = {
  admin: 'bg-violet-500/15 text-violet-600 dark:text-violet-300',
  maintain: 'bg-blue-500/15 text-blue-600 dark:text-blue-300',
  push: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300',
  triage: 'bg-amber-500/15 text-amber-700 dark:text-amber-300',
  pull: 'bg-muted text-muted-foreground',
  none: 'bg-muted text-muted-foreground',
}

function PermBadge({ p }: { p: GitPermission }) {
  const t = useT()
  return <span className={cn('rounded px-1.5 py-px text-[11px] font-medium', PERM_TONE[p])}>{t(`git.perm.${p}`)}</span>
}

function Sync({ ahead, behind, changed }: { ahead?: number; behind?: number; changed?: number }) {
  const t = useT()
  return (
    <>
      {!!ahead && (
        <span className="inline-flex items-center gap-0.5 text-xs text-warning" title={t('git.aheadTip', { count: ahead })}>
          <ArrowUp className="size-3" />
          {ahead}
        </span>
      )}
      {!!behind && (
        <span className="inline-flex items-center gap-0.5 text-xs text-muted-foreground" title={t('git.behindTip', { count: behind })}>
          <ArrowDown className="size-3" />
          {behind}
        </span>
      )}
      {!!changed && (
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <PencilLine className="size-3" />
          {t('git.uncommitted', { count: changed })}
        </span>
      )}
    </>
  )
}

function ConnectGithub() {
  const t = useT()
  return (
    <div className="grid gap-3 rounded-xl border border-dashed p-5 text-[13px]">
      <p className="flex items-center gap-2 font-medium">
        <Github className="size-4" /> {t('git.connectTitle')}
      </p>
      <ol className="ml-5 list-decimal space-y-1 text-muted-foreground">
        <li>
          {t('git.connect1')}{' '}
          <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
            github.com/settings/personal-access-tokens
          </a>
        </li>
        <li>{t('git.connect2')}</li>
        <li>{t('git.connect3')}</li>
      </ol>
      <Button asChild size="sm" className="w-fit">
        <Link to="/settings/keys">
          <KeyRound /> {t('git.toKeys')}
        </Link>
      </Button>
    </div>
  )
}

/** Vault keys holding a GitHub token that GitHub refused (expired, revoked): the other accounts still show. */
function TokenErrors({ errors }: { errors: { key: string; error: string }[] }) {
  const t = useT()
  if (!errors.length) return null
  return (
    <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-[13px]">
      <p className="font-medium">{t('git.tokenErrors', { count: errors.length })}</p>
      <ul className="mt-1 grid gap-0.5 text-xs text-muted-foreground">
        {errors.map((e) => (
          <li key={e.key}>
            <span className="font-mono break-all text-foreground">{e.key}</span> — {e.error}
          </li>
        ))}
      </ul>
    </div>
  )
}

// ---- the list (second-level sidebar): each source (this server, then one per GitHub account) and its repositories -----

type Entry = {
  /** what ?repo= takes: a clone's path, or github:owner/name */
  id: string
  label: string
  /** shown when two clones have the same name: the folder that tells them apart */
  sub?: string
  local?: GitLocalRepo
  remote?: GitHubRepo
}

/** The clones of the server, as the server sorts them (last commit first). A clone reads under its GitHub name
 *  (a folder named "repo" or "up" says nothing). */
function localEntries(data: GitOverview): Entry[] {
  const out: Entry[] = data.local.map((r) => ({ id: r.path, label: r.github ? r.github.split('/')[1] : r.name, local: r }))
  const seen = new Map<string, number>()
  for (const e of out) seen.set(e.label.toLowerCase(), (seen.get(e.label.toLowerCase()) || 0) + 1)
  for (const e of out) {
    if ((seen.get(e.label.toLowerCase()) || 0) < 2) continue
    const parts = e.id.split('/')
    e.sub = parts[parts.length - 1] !== e.label ? parts[parts.length - 1] : parts[parts.length - 2]
  }
  return out
}

const FOLDED_KEY = 'mx-git-folded'
const readFolded = (): string[] => {
  try {
    const v = JSON.parse(localStorage.getItem(FOLDED_KEY) || '[]')
    return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []
  } catch {
    return []
  }
}

function RepoRow({ e, active }: { e: Entry; active: boolean }) {
  const t = useT()
  const touch = useCompact()
  const r = e.local
  const Icon = r ? FolderGit2 : Github
  const ref = React.useRef<HTMLAnchorElement>(null)
  // the repository open (a link from the chat, a reload) is in view in the list
  React.useEffect(() => {
    if (active) ref.current?.scrollIntoView({ block: 'nearest' })
  }, [active])
  // right click (long press on a phone): a session about the repository, in the topic the user picks
  const ctx = useContextMenu({ links: true })
  const [session, setSession] = React.useState(false)
  const github = r?.github || e.remote?.full_name
  const url = github ? `https://github.com/${github}` : null
  return (
    <>
      <Link
        ref={ref}
        {...ctx.props}
        to={`/git?repo=${encodeURIComponent(e.id)}`}
        aria-current={active ? 'page' : undefined}
        title={r ? `${r.path}${r.branch ? ` (${r.branch})` : ''}` : e.remote?.full_name}
        className={cn(
          'flex w-full min-w-0 items-center gap-2 rounded-md pr-2 pl-7 text-[13px] text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
          touch ? 'h-11' : 'h-8',
          active && 'bg-accent font-medium text-foreground hover:bg-accent',
          'pointer-coarse:select-none [-webkit-touch-callout:none]', // the long press opens our menu, not iOS's
        )}
        data-testid="git-entry"
      >
        <Icon className={cn('size-3.5 shrink-0', active && 'text-primary')} />
        <span className="min-w-0 flex-1 truncate">
          {e.label}
          {e.sub && <span className="ml-1.5 text-xs font-normal text-muted-foreground">{e.sub}</span>}
        </span>
        {r?.error && <TriangleAlert className="size-3 shrink-0 text-destructive" aria-label={r.error} />}
        {!!r?.ahead && (
          <span className="inline-flex shrink-0 items-center text-[11px] text-warning tabular-nums" title={t('git.aheadTip', { count: r.ahead })}>
            <ArrowUp className="size-3" />
            {r.ahead}
          </span>
        )}
        {!!r?.behind && (
          <span className="inline-flex shrink-0 items-center text-[11px] tabular-nums" title={t('git.behindTip', { count: r.behind })}>
            <ArrowDown className="size-3" />
            {r.behind}
          </span>
        )}
        {!!r && r.changed + r.untracked > 0 && (
          <span className="inline-flex shrink-0" title={t('git.uncommitted', { count: r.changed + r.untracked })}>
            <PencilLine className="size-3" />
          </span>
        )}
        {e.remote?.private && <Lock className="size-3 shrink-0" aria-label={t('git.private')} />}
        {!!e.remote?.local_paths.length && (
          <span className="inline-flex shrink-0 text-success" title={t('git.clonedHere')}>
            <Server className="size-3" />
          </span>
        )}
      </Link>
      {ctx.menu(
        <>
          <DropdownMenuItem onSelect={() => setSession(true)} data-testid="git-new-session">
            <MessageSquarePlus /> {t('git.session.new')}
          </DropdownMenuItem>
          {url && (
            <>
              <DropdownMenuItem onSelect={() => window.open(url, '_blank', 'noopener,noreferrer')}>
                <ExternalLink /> {t('git.branch.openGithub')}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => void navigator.clipboard?.writeText(url)}>
                <Link2 /> {t('git.copyLink')}
              </DropdownMenuItem>
            </>
          )}
        </>,
      )}
      {session && <GitSessionDialog target={{ github, clones: r ? [r.path] : e.remote?.local_paths, branch: r?.branch || undefined }} onClose={() => setSession(false)} />}
    </>
  )
}

function GitNav({ repo, query }: { repo: string | null; query: string }) {
  const t = useT()
  const touch = useCompact()
  const { data, isLoading } = useGitRepos()
  const [folded, setFolded] = React.useState(readFolded)
  const fold = (id: string) =>
    setFolded((f) => {
      const next = f.includes(id) ? f.filter((x) => x !== id) : [...f, id]
      try {
        localStorage.setItem(FOLDED_KEY, JSON.stringify(next))
      } catch {
        /* private mode: the fold lasts the visit */
      }
      return next
    })
  const gh = data?.github
  const accounts = gh?.connected ? gh.accounts : []
  const needle = query.trim().toLowerCase()
  const local = React.useMemo(() => (data ? localEntries(data) : []), [data])
  const sections: { id: string; icon: React.ComponentType<{ className?: string }>; label: string; count?: number; entries: Entry[] }[] = [
    {
      id: 'local',
      icon: Server,
      label: t('git.tabLocal'),
      count: data?.local.length,
      entries: local.filter((e) => !needle || `${e.label} ${e.id} ${e.local?.github || ''} ${e.local?.branch || ''}`.toLowerCase().includes(needle)),
    },
    ...(accounts.length ? accounts : [null]).map((a) => ({
      id: a ? `github:${a.login}` : 'github',
      icon: Github,
      label: a ? `GitHub @${a.login}` : 'GitHub',
      count: a?.repos,
      entries: (a && gh ? gh.repos : [])
        .filter((g) => accounts.length < 2 || g.accounts.includes(a!.login))
        .filter((g) => !needle || `${g.full_name} ${g.description}`.toLowerCase().includes(needle))
        .map((g) => ({ id: `github:${g.full_name}`, label: g.name, sub: g.owner.toLowerCase() === a!.login.toLowerCase() ? undefined : g.owner, remote: g })),
    })),
  ]
  const on = (e: Entry) => !!repo && repo.toLowerCase() === e.id.toLowerCase()
  const hint = 'py-1 pl-9 text-xs text-muted-foreground'
  return (
    <nav aria-label={t('git.title')} className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] content-start gap-0.5 overflow-y-auto p-2" data-testid="git-nav">
      {sections.map((s) => {
        // a source is a head that folds, not a page; a search shows what it finds, folded or not
        const closed = !needle && folded.includes(s.id)
        return (
          <React.Fragment key={s.id}>
            <button
              type="button"
              onClick={() => !needle && fold(s.id)}
              aria-expanded={!closed}
              className={cn(
                'flex w-full min-w-0 items-center gap-2.5 rounded-md px-2.5 text-sm text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
                touch ? 'h-11' : 'h-9',
              )}
              data-testid="git-fold"
            >
              <s.icon className="size-4 shrink-0" />
              <span className="min-w-0 flex-1 truncate text-left font-medium text-foreground">{s.label}</span>
              {s.count != null && s.count > 0 && <span className="min-w-5 text-right text-xs tabular-nums">{s.count}</span>}
              <ChevronRight className={cn('size-3.5 shrink-0 transition-transform', !closed && 'rotate-90')} />
            </button>
            {!closed && (
              <>
                {isLoading && s.id === 'local' && [0, 1, 2].map((i) => <Skeleton key={i} className="my-1 ml-7 h-5" />)}
                {s.entries.map((e) => <RepoRow key={e.id} e={e} active={on(e)} />)}
                {!!needle && !!data && !s.entries.length && <p className={hint}>{t('git.noMatch')}</p>}
                {!needle && !!data && s.id === 'local' && !local.length && <p className={hint}>{t('git.noLocal')}</p>}
                {!needle && !!gh && s.id === 'github' && (
                  <Link to="/git" className={cn(hint, 'rounded-md pr-2 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring')} data-testid="git-connect-link">
                    {t('git.connectTitle')}
                  </Link>
                )}
              </>
            )}
          </React.Fragment>
        )
      })}
      {accounts.length > 0 && !needle && (
        <Link to="/settings/keys" className={cn(hint, 'mt-1 rounded-md pr-2 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring')}>
          {t('git.addAccount')}
        </Link>
      )}
    </nav>
  )
}

// ---- nothing is open: the page stays empty (a repository is picked in the list), but for what GitHub needs ----------

function GitHome() {
  const t = useT()
  const touch = useCompact()
  const { data, error } = useGitRepos()
  useDocumentTitle(t('git.title'))
  const gh = data?.github
  const none = !!data && !data.local.length && !gh?.repos.length
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col" data-testid="git-home">
      {touch && <PageHeader title={t('git.title')} />}
      <div className="flex min-h-0 flex-1 overflow-y-auto p-6">
        <div className="m-auto grid w-full max-w-xl justify-items-center gap-4">
          {error ? (
            <p className="text-sm text-destructive">{errorMessage(error)}</p>
          ) : (
            <EmptyState
              icon={FolderGit2}
              title={none ? t('git.noLocal') : t('git.pick')}
              description={none ? t('git.localHint', { root: data.root }) : undefined}
              action={
                touch && !none ? (
                  <Button variant="outline" onClick={openPageList}>
                    <FolderGit2 /> {t('git.list')}
                  </Button>
                ) : undefined
              }
            />
          )}
          {gh && (!!gh.errors.length || !gh.accounts.length) && (
            <div className="grid w-full gap-3">
              <TokenErrors errors={gh.errors} />
              {!gh.accounts.length && <ConnectGithub />}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function RepoView({ repo, onSwitch, refresh }: { repo: string; onSwitch: (repo: string) => void; refresh: React.ReactNode }) {
  const t = useT()
  const [limit, setLimit] = React.useState(200)
  const { data, error, isLoading, isFetching } = useGitGraph(repo, { limit })
  const { data: overview } = useGitRepos()
  const [selected, setSelected] = React.useState<string | null>(null)
  React.useEffect(() => setSelected(null), [repo])
  // below 1700 px the side column would squeeze the graph: the picked commit opens in a bottom sheet instead
  const wide = useMediaQuery('(min-width: 1700px)')
  const r = data?.repo
  const isGh = repo.startsWith('github:')
  // a commit of a clone opens on GitHub once an origin/ branch holds it
  const pushed = React.useMemo(() => (data && data.repo.kind !== 'github' ? pushedShas(data.commits) : null), [data])
  const urlOf = (sha: string) => commitUrl(sha, r?.github, pushed)
  // the pull requests of the repository, also on a clone of a GitHub repository
  const prRepo = isGh ? repo : r?.github && overview?.github.connected ? `github:${r.github}` : null
  // the other side of the same repository (clone <-> GitHub), when there is one
  const other = isGh
    ? overview?.local.find((l) => l.github && `github:${l.github}`.toLowerCase() === repo.toLowerCase())?.path
    : r?.github && overview?.github.connected
      ? `github:${r.github}`
      : null
  const ghInfo = isGh ? overview?.github.repos.find((g) => `github:${g.full_name}`.toLowerCase() === repo.toLowerCase()) : null
  const touch = useCompact()
  const title = isGh ? repo.slice(7) : r?.github ? r.github.split('/')[1] : r?.name || repo.split('/').pop() || repo
  const description = (
    <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      {r?.branch && <span className="max-w-full rounded bg-primary/15 px-1.5 py-px font-mono text-[11px] [overflow-wrap:anywhere] text-primary">{r.branch}</span>}
      {(r?.permission || ghInfo?.permission) && <PermBadge p={(r?.permission || ghInfo?.permission)!} />}
      <Sync ahead={r?.ahead} behind={r?.behind} changed={(r?.changed || 0) + (r?.untracked || 0)} />
      {!isGh && r?.path ? (
        <span className="min-w-0 truncate font-mono text-xs">
          {r.path}
          {r.upstream && ` · ${t('git.tracks', { upstream: r.upstream })}`}
        </span>
      ) : (
        isGh && r?.description && <span className="min-w-0 truncate text-xs">{r.description}</span>
      )}
    </span>
  )
  const actions = (
    <>
      {other && (
        <Segmented
          aria-label={t('git.source')}
          value={isGh ? 'github' : 'local'}
          onChange={() => onSwitch(other)}
          options={[
            // touch: icons only, the title keeps the room
            { value: 'local', label: touch ? <span className="sr-only">{t('git.side.local')}</span> : t('git.side.local'), icon: <Server className="size-3.5" /> },
            { value: 'github', label: touch ? <span className="sr-only">GitHub</span> : 'GitHub', icon: <Github className="size-3.5" /> },
          ]}
        />
      )}
      {(r?.url || (r?.github && `https://github.com/${r.github}`)) && (
        <Button variant="ghost" size={touch ? 'icon-sm' : 'sm'} asChild>
          <a href={r?.url || `https://github.com/${r!.github}`} target="_blank" rel="noopener noreferrer" aria-label={t('git.branch.openGithub')}>
            {!touch && 'GitHub'} <ExternalLink />
          </a>
        </Button>
      )}
      {!touch && refresh}
    </>
  )
  return (
    <Page title={title} description={description} actions={actions} width="wide">
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
      <div className="grid items-start gap-4 min-[1700px]:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 rounded-xl border bg-card p-1.5">
          {isLoading ? (
            <div className="grid gap-2 p-2">
              {Array.from({ length: 10 }, (_, i) => (
                <Skeleton key={i} className="h-5" />
              ))}
            </div>
          ) : error ? (
            <p className="p-3 text-sm text-destructive">{errorMessage(error)}</p>
          ) : data && !data.commits.length ? (
            <p className="p-3 text-sm text-muted-foreground">{t('git.noCommits')}</p>
          ) : data ? (
            <>
              <GitGraph
                commits={data.commits}
                selected={selected}
                onSelect={setSelected}
                github={r?.github}
                onGithub={r?.kind === 'github'}
                clones={r?.kind === 'local' && r.path ? [r.path] : overview?.github.repos.find((g) => g.full_name === r?.github)?.local_paths}
              />
              {data.truncated && (
                <div className="flex items-center justify-center gap-3 p-2 text-xs text-muted-foreground">
                  {isGh && r?.branches && r.branches_shown && r.branches > r.branches_shown
                    ? t('git.branchesShown', { shown: r.branches_shown, total: r.branches })
                    : t('git.truncated', { count: data.commits.length })}
                  {limit < 1000 && (
                    <Button variant="outline" size="sm" loading={isFetching} onClick={() => setLimit((l) => Math.min(1000, l * 2.5))}>
                      {t('git.more')}
                    </Button>
                  )}
                </div>
              )}
            </>
          ) : null}
        </div>
        <div className="grid gap-4 max-[1699px]:order-first min-[1700px]:sticky min-[1700px]:top-4">
          {!wide ? null : selected ? (
            <CommitDetail repo={data?.repo.id || repo} sha={selected} url={urlOf(selected)} />
          ) : (
            <p className="rounded-xl border border-dashed p-4 text-[13px] text-muted-foreground">{t('git.pickCommit')}</p>
          )}
          {prRepo && <PullList repo={prRepo} wide={wide} />}
          {!isGh && r?.path && <CopyList clone={r.path} />}
        </div>
      </div>
      {!wide && (
        <Sheet open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
          <SheetContent side="bottom" aria-describedby={undefined}>
            <SheetTitle className="sr-only">{selected?.slice(0, 7)}</SheetTitle>
            <SheetBody className="pt-2">{selected && <CommitDetail repo={data?.repo.id || repo} sha={selected} url={urlOf(selected)} className="border-0 p-0" />}</SheetBody>
          </SheetContent>
        </Sheet>
      )}
    </div>
    </Page>
  )
}

export default function GitPage() {
  const t = useT()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const repo = params.get('repo')
  const [query, setQuery] = React.useState('')
  const [refreshing, setRefreshing] = React.useState(false)
  const doRefresh = async () => {
    setRefreshing(true)
    try {
      qc.setQueryData(gitKeys.repos, await refreshGitRepos())
      await qc.invalidateQueries({ queryKey: ['git', 'graph'] })
    } finally {
      setRefreshing(false)
    }
  }
  const refresh = (variant: 'outline' | 'ghost') => (
    <Button variant={variant} size="icon-sm" loading={refreshing} onClick={() => void doRefresh()} aria-label={t('git.refresh')} title={t('git.refresh')} className={variant === 'ghost' ? 'shrink-0 text-muted-foreground' : undefined}>
      <RefreshCw />
    </Button>
  )
  return (
    <>
      <PageList id="git" label={t('git.title')} search={{ value: query, onChange: setQuery, placeholder: t('git.searchList') }} actions={refresh('ghost')}>
        <GitNav repo={repo} query={query} />
      </PageList>
      {repo ? <RepoView key={repo} repo={repo} onSwitch={(r) => setParams({ repo: r })} refresh={refresh('outline')} /> : <GitHome />}
    </>
  )
}

type PullFilter = 'open' | 'mine' | 'closed'

/** The pull requests of a GitHub repository: a click opens one in the PR view (read, comment, review, merge). */
function PullList({ repo, wide }: { repo: string; wide: boolean }) {
  const t = useT()
  const lang = useLang()
  const [filter, setFilter] = React.useState<PullFilter>('open')
  const pulls = useGitPulls(repo, filter === 'closed' ? 'closed' : 'open')
  const list = (pulls.data ?? []).filter((p) => filter !== 'mine' || p.review_me)
  if (!wide && filter === 'open' && !pulls.data?.length) return null
  return (
    <div className="grid gap-2 rounded-xl border bg-card p-3" data-testid="git-pulls">
      <div className="flex flex-wrap items-center gap-2">
        <p className="flex items-center gap-2 text-sm font-medium">
          <GitPullRequest className="size-4" /> {t('git.pullsTitle')}
        </p>
        <Segmented
          size="sm"
          className="ml-auto"
          aria-label={t('git.pulls')}
          value={filter}
          onChange={setFilter}
          options={[
            { value: 'open', label: t('git.pullsOpen') },
            { value: 'mine', label: t('git.pullsMine') },
            { value: 'closed', label: t('git.pullsClosed') },
          ]}
        />
      </div>
      {pulls.isLoading ? (
        <Skeleton className="h-10" />
      ) : pulls.error ? (
        <p className="text-xs text-destructive">{errorMessage(pulls.error)}</p>
      ) : !list.length ? (
        <p className="text-xs text-muted-foreground">{filter === 'mine' ? t('git.noPullsMine') : t('git.noPulls')}</p>
      ) : (
        <ul className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
          {list.map((p) => (
            <li key={p.number}>
              <button type="button" onClick={() => void openPr(repo.slice(7), p.number)} className="grid w-full grid-cols-[minmax(0,1fr)] gap-0.5 rounded-md p-1.5 text-left text-[13px] hover:bg-muted" data-testid="git-pull">
                <span className="flex min-w-0 items-center gap-1.5">
                  <span className="truncate">
                    <span className="text-muted-foreground">#{p.number}</span> {p.title}
                  </span>
                  {p.draft && <span className="shrink-0 text-xs text-muted-foreground">({t('git.draft')})</span>}
                  {p.state === 'merged' && <Badge variant="default" className="shrink-0">{t('git.merged')}</Badge>}
                  {p.outside && <Badge variant="warning" className="shrink-0">{t('git.outside')}</Badge>}
                  {p.review_me && p.state === 'open' && <Badge variant="muted" className="shrink-0">{t('git.reviewMe')}</Badge>}
                </span>
                <span className="flex min-w-0 items-center gap-1 font-mono text-[11px] text-muted-foreground">
                  <GitBranch className="size-3 shrink-0" />
                  <span className="truncate">
                    {p.head} → {p.base} · {p.author} · {fmtRelative(p.updated, lang)}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** The separate copies of a clone (Code mode): each with its session, a click opens the session. */
function CopyList({ clone }: { clone: string }) {
  const t = useT()
  const navigate = useNavigate()
  const { data: settings } = useSettings()
  const copies = useCopies(!!settings?.code_mode)
  const list = (copies.data ?? []).filter((c) => c.repo === clone)
  if (!list.length) return null
  return (
    <div className="grid gap-2 rounded-xl border bg-card p-3" data-testid="git-copies">
      <p className="flex items-center gap-2 text-sm font-medium">
        <FolderGit2 className="size-4" /> {t('git.copies')}
        <span className="text-xs font-normal text-muted-foreground">{list.length}</span>
      </p>
      <ul className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
        {list.map((c) => (
          <li key={c.sid}>
            <button type="button" onClick={() => navigate(`/sessions/${c.sid}`)} className="grid w-full grid-cols-[minmax(0,1fr)] gap-0.5 rounded-md p-1.5 text-left text-[13px] hover:bg-muted">
              <span className="truncate">{c.title}</span>
              <span className="flex min-w-0 items-center gap-1 font-mono text-[11px] text-muted-foreground">
                <GitBranch className="size-3 shrink-0" />
                <span className="truncate">
                  {c.branch} ← {c.base}
                  {c.ahead ? ` · ↑${c.ahead}` : ''}
                  {c.dirty ? ` · ${t('git.copyDirty', { count: c.dirty })}` : ''}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
