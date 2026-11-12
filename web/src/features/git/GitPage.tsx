// Feature page "Git & GitHub" (/git, Settings -> Features -> git_page). Second-level sidebar: the two sources (this server,
// GitHub) then the repositories of the one picked, most recent first. A source: its repositories as cards. A repository:
// graph of branches and commits, commit details, open pull requests, Server | GitHub switch when it has both sides.
// The repository shown is in the URL (?repo=<path or github:owner/name>), so a chat block can link to it.
import * as React from 'react'
import { Link, useSearchParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown, ArrowUp, ExternalLink, FolderGit2, GitBranch, GitPullRequest, KeyRound, Lock, PencilLine, RefreshCw, Server, Star,
} from 'lucide-react'
import { gitKeys, refreshGitRepos, useGitGraph, useGitPulls, useGitRepos } from '@/lib/queries'
import type { GitHubRepo, GitLocalRepo, GitPermission } from '@/lib/types'
import { errorMessage } from '@/lib/api'
import { fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { Badge, Button, EmptyState, Segmented, Sheet, SheetBody, SheetContent, SheetTitle, Skeleton } from '@/components/ui'
import { useCompact, useMediaQuery } from '@/stores/media'
import { Page } from '@/components/shell/Page'
import { ListEntry, PageList } from '@/components/shell/PageList'
import { GitGraph } from './GitGraph'
import { Github } from './GithubMark'
import { CommitDetail } from './CommitDetail'

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

function LocalRow({ r, root, onOpen }: { r: GitLocalRepo; root: string; onOpen: () => void }) {
  const lang = useLang()
  const t = useT()
  const rel = r.path.startsWith(root + '/') ? r.path.slice(root.length + 1) : r.path
  return (
    <li>
      <button type="button" onClick={onOpen} className="flex h-full w-full items-start gap-3 rounded-xl border bg-card p-3.5 text-left transition-colors hover:border-primary/40 hover:bg-accent/40" data-testid="git-local">
        <FolderGit2 className="mt-0.5 size-5 shrink-0 text-primary" />
        <div className="grid min-w-0 flex-1 gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="min-w-0 font-medium [overflow-wrap:anywhere]">{r.name}</span>
            {/* the repository only: its branches (and the worktree folders of the same clone) are in its graph;
                the checked-out branch shows only when it is not the usual one (or HEAD is detached) */}
            {!r.error && !(r.branch && ['main', 'master'].includes(r.branch)) && (
              <span className="max-w-full rounded bg-primary/15 px-1.5 py-px font-mono text-[11px] break-all text-primary">
                {r.branch ?? t('git.detached')}
              </span>
            )}
            <Sync ahead={r.ahead} behind={r.behind} changed={r.changed + r.untracked} />
            {!!r.worktrees && (
              <span className="text-xs text-muted-foreground" data-testid="git-worktrees">
                {t('git.worktrees', { count: r.worktrees })}
              </span>
            )}
            {r.github && (
              <span className="inline-flex min-w-0 items-center gap-1 text-xs text-muted-foreground [overflow-wrap:anywhere]">
                <Github className="size-3 shrink-0" />
                {r.github}
              </span>
            )}
          </div>
          <span className="truncate font-mono text-xs text-muted-foreground">{rel}</span>
          {r.error ? (
            <span className="text-xs text-destructive">{r.error}</span>
          ) : (
            r.last_commit && (
              <span className="truncate text-xs text-muted-foreground">
                {fmtRelative(r.last_commit, lang)} · {r.last_subject}
              </span>
            )
          )}
        </div>
      </button>
    </li>
  )
}

function GithubRow({ r, onOpen }: { r: GitHubRepo; onOpen: () => void }) {
  const t = useT()
  const lang = useLang()
  return (
    <li>
      <button type="button" onClick={onOpen} className="flex h-full w-full items-start gap-3 rounded-xl border bg-card p-3.5 text-left transition-colors hover:border-primary/40 hover:bg-accent/40" data-testid="git-github">
        <Github className="mt-0.5 size-5 shrink-0 text-primary" />
        <div className="grid min-w-0 flex-1 gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">
              <span className="text-muted-foreground">{r.owner}/</span>
              {r.name}
            </span>
            <PermBadge p={r.permission} />
            {r.private ? (
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                <Lock className="size-3" />
                {t('git.private')}
              </span>
            ) : (
              <span className="text-xs text-muted-foreground">{t('git.public')}</span>
            )}
            {r.archived && <Badge variant="muted">{t('git.archived')}</Badge>}
            {r.fork && <Badge variant="muted">fork</Badge>}
            {r.keys.length > 0 && (
              <span className="inline-flex items-center gap-1 font-mono text-[11px] text-muted-foreground" title={r.keys.join(', ')}>
                <KeyRound className="size-3" />
                {r.keys.length === 1 ? r.keys[0] : t('git.keysCount', { count: r.keys.length })}
              </span>
            )}
            {r.local_paths.length > 0 && (
              <span className="inline-flex items-center gap-1 text-xs text-success">
                <Server className="size-3" />
                {t('git.clonedHere')}
              </span>
            )}
          </div>
          {r.description && <span className="line-clamp-1 text-xs text-muted-foreground">{r.description}</span>}
          <span className="flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
            {r.language && <span>{r.language}</span>}
            {r.stars > 0 && (
              <span className="inline-flex items-center gap-0.5">
                <Star className="size-3" />
                {r.stars}
              </span>
            )}
            {r.pushed_at && <span>{t('git.pushed', { when: fmtRelative(Date.parse(r.pushed_at) / 1000, lang) })}</span>}
          </span>
        </div>
      </button>
    </li>
  )
}

// ---- the list (second-level sidebar): the sources only - this server, then one entry per GitHub account ------------

type Source = 'local' | 'github'

function GitNav({ repo, source, account, onPick }: { repo: string | null; source: Source; account: string | null; onPick: (s: Source, account?: string) => void }) {
  const t = useT()
  const { data } = useGitRepos()
  const gh = data?.github
  const accounts = gh?.connected ? gh.accounts : []
  // a repository open: its source stays lit (its account when only one sees it)
  const ghRepo = repo?.startsWith('github:') ? gh?.repos.find((g) => `github:${g.full_name}`.toLowerCase() === repo.toLowerCase()) : null
  const onAccount = (login: string) =>
    source === 'github' && (account ? account === login : ghRepo ? ghRepo.accounts.length === 1 && ghRepo.accounts[0] === login : accounts.length === 1)
  return (
    <nav aria-label={t('git.title')} className="grid content-start gap-0.5 p-2" data-testid="git-nav">
      <ListEntry active={source === 'local'} onClick={() => onPick('local')} icon={Server} label={t('git.tabLocal')} count={data?.local.length} testid="git-src-local" />
      {accounts.length ? (
        accounts.map((a) => (
          <ListEntry key={a.login} active={onAccount(a.login)} onClick={() => onPick('github', accounts.length > 1 ? a.login : undefined)} icon={Github} label={`GitHub @${a.login}`} count={a.repos} testid="git-src-github" />
        ))
      ) : (
        <ListEntry active={source === 'github'} onClick={() => onPick('github')} icon={Github} label="GitHub" testid="git-src-github" />
      )}
    </nav>
  )
}

// ---- the page of a source: the simple cards of before, filtered by the list's search -------------------------------

function SourceCards({ source, account, query, onOpen }: { source: Source; account: string | null; query: string; onOpen: (repo: string) => void }) {
  const t = useT()
  const { data, isLoading, error } = useGitRepos()
  if (isLoading)
    return (
      <div className="grid gap-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-20 rounded-xl" />
        ))}
      </div>
    )
  if (error) return <p className="text-sm text-destructive">{errorMessage(error)}</p>
  if (!data) return null
  const needle = query.trim().toLowerCase()
  if (source === 'local') {
    const local = data.local.filter((r) => !needle || `${r.path} ${r.github || ''} ${r.branch || ''}`.toLowerCase().includes(needle))
    return local.length ? (
      <ul className="grid grid-cols-[minmax(0,1fr)] gap-2 lg:grid-cols-2">
        {local.map((r) => (
          <LocalRow key={r.path} r={r} root={data.root} onOpen={() => onOpen(r.path)} />
        ))}
      </ul>
    ) : (
      <EmptyState icon={FolderGit2} title={needle ? t('git.noMatch') : t('git.noLocal')} description={t('git.localHint', { root: data.root })} />
    )
  }
  const gh = data.github
  const accounts = gh.accounts
  if (!gh.connected) return <ConnectGithub />
  if (!accounts.length)
    return (
      <div className="grid gap-3">
        <TokenErrors errors={gh.errors} />
        <ConnectGithub />
      </div>
    )
  const remote = gh.repos.filter(
    (r) => (!account || r.accounts.includes(account)) && (!needle || `${r.full_name} ${r.description} ${r.keys.join(' ')}`.toLowerCase().includes(needle)),
  )
  return (
    <div className="grid gap-3">
      <TokenErrors errors={gh.errors} />
      {!remote.length && <EmptyState icon={FolderGit2} title={t('git.noMatch')} />}
      <ul className="grid grid-cols-[minmax(0,1fr)] gap-2 lg:grid-cols-2">
        {remote.map((r) => (
          <GithubRow key={r.full_name} r={r} onOpen={() => onOpen(`github:${r.full_name}`)} />
        ))}
      </ul>
    </div>
  )
}

function RepoView({ repo, onSwitch, refresh }: { repo: string; onSwitch: (repo: string) => void; refresh: React.ReactNode }) {
  const t = useT()
  const lang = useLang()
  const [limit, setLimit] = React.useState(200)
  const { data, error, isLoading, isFetching } = useGitGraph(repo, { limit })
  const { data: overview } = useGitRepos()
  const pulls = useGitPulls(repo)
  const [selected, setSelected] = React.useState<string | null>(null)
  React.useEffect(() => setSelected(null), [repo])
  // below 1700 px the side column would squeeze the graph: the picked commit opens in a bottom sheet instead
  const wide = useMediaQuery('(min-width: 1700px)')
  const r = data?.repo
  const isGh = repo.startsWith('github:')
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
              <GitGraph commits={data.commits} selected={selected} onSelect={setSelected} github={r?.github} onGithub={r?.kind === 'github'} />
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
            <CommitDetail repo={data?.repo.id || repo} sha={selected} />
          ) : (
            <p className="rounded-xl border border-dashed p-4 text-[13px] text-muted-foreground">{t('git.pickCommit')}</p>
          )}
          {isGh && (wide || !!pulls.data?.length) && (
            <div className="grid gap-2 rounded-xl border bg-card p-3">
              <p className="flex items-center gap-2 text-sm font-medium">
                <GitPullRequest className="size-4" /> {t('git.pulls')}
                {pulls.data && <span className="text-xs font-normal text-muted-foreground">{pulls.data.length}</span>}
              </p>
              {pulls.isLoading ? (
                <Skeleton className="h-10" />
              ) : pulls.error ? (
                <p className="text-xs text-destructive">{errorMessage(pulls.error)}</p>
              ) : !pulls.data?.length ? (
                <p className="text-xs text-muted-foreground">{t('git.noPulls')}</p>
              ) : (
                <ul className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
                  {pulls.data.map((p) => (
                    <li key={p.number}>
                      <a href={p.url} target="_blank" rel="noopener noreferrer" className="grid grid-cols-[minmax(0,1fr)] gap-0.5 rounded-md p-1.5 text-[13px] hover:bg-accent/60">
                        <span className="truncate">
                          <span className="text-muted-foreground">#{p.number}</span> {p.title}
                          {p.draft && <span className="ml-1 text-xs text-muted-foreground">({t('git.draft')})</span>}
                        </span>
                        <span className="flex min-w-0 items-center gap-1 font-mono text-[11px] text-muted-foreground">
                          <GitBranch className="size-3 shrink-0" />
                          <span className="truncate">
                            {p.head} → {p.base} · {p.author} · {fmtRelative(p.updated, lang)}
                          </span>
                        </span>
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>
      {!wide && (
        <Sheet open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
          <SheetContent side="bottom" aria-describedby={undefined}>
            <SheetTitle className="sr-only">{selected?.slice(0, 7)}</SheetTitle>
            <SheetBody className="pt-2">{selected && <CommitDetail repo={data?.repo.id || repo} sha={selected} className="border-0 p-0" />}</SheetBody>
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
  // the source shown: ?source=github, else the side of the repository open, else the server
  const source: Source = params.get('source') === 'github' || (!params.get('source') && repo?.startsWith('github:')) ? 'github' : 'local'
  const account = params.get('account')
  const [query, setQuery] = React.useState('')
  const [refreshing, setRefreshing] = React.useState(false)
  const { data } = useGitRepos()
  const open = (r: string) => setParams({ repo: r, ...(source === 'github' && !r.startsWith('github:') ? { source: 'github' } : {}), ...(account ? { account } : {}) })
  const pick = (s: Source, login?: string) => setParams(s === 'github' ? { source: 'github', ...(login ? { account: login } : {}) } : {})
  const doRefresh = async () => {
    setRefreshing(true)
    try {
      qc.setQueryData(gitKeys.repos, await refreshGitRepos())
      await qc.invalidateQueries({ queryKey: ['git', 'graph'] })
    } finally {
      setRefreshing(false)
    }
  }
  const refresh = (
    <Button variant="outline" size="icon-sm" loading={refreshing} onClick={() => void doRefresh()} aria-label={t('git.refresh')} title={t('git.refresh')}>
      <RefreshCw />
    </Button>
  )
  const gh = data?.github
  return (
    <>
      <PageList id="git" label={t('git.title')} search={{ value: query, onChange: setQuery, placeholder: t('git.searchList') }}>
        <GitNav repo={repo} source={source} account={account} onPick={pick} />
      </PageList>
      {repo ? (
        <RepoView key={repo} repo={repo} onSwitch={(r) => setParams({ repo: r })} refresh={refresh} />
      ) : (
        <Page
          title={source === 'github' ? (account ? `GitHub @${account}` : gh?.accounts.length === 1 ? `GitHub @${gh.accounts[0].login}` : 'GitHub') : t('git.tabLocal')}
          description={source === 'github' ? t('git.ghHint') : data ? t('git.localHint', { root: data.root }) : undefined}
          actions={
            <>
              {source === 'github' && (
                <Button variant="ghost" size="sm" asChild>
                  <Link to="/settings/keys">{t('git.addAccount')}</Link>
                </Button>
              )}
              {refresh}
            </>
          }
        >
          <SourceCards source={source} account={account} query={query} onOpen={open} />
        </Page>
      )}
    </>
  )
}
