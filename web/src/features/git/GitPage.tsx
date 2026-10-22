// Feature page "Git & GitHub" (/git, Settings -> Features -> git_page): every clone on the server and every repository of the GitHub account with
// the token's rights; a click opens the repository: graph of branches and commits, commit details, open pull requests.
// The repository shown is in the URL (?repo=<path or github:owner/name>), so a chat block can link to it.
import * as React from 'react'
import { Link, useSearchParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown, ArrowLeft, ArrowUp, ExternalLink, FolderGit2, GitBranch, GitPullRequest, KeyRound, Lock, PencilLine, RefreshCw, Search, Server, Star,
} from 'lucide-react'
import { gitKeys, refreshGitRepos, useGitGraph, useGitPulls, useGitRepos } from '@/lib/queries'
import type { GitHubRepo, GitLocalRepo, GitPermission } from '@/lib/types'
import { errorMessage } from '@/lib/api'
import { fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { Badge, Button, EmptyState, Input, Segmented, Sheet, SheetBody, SheetContent, SheetTitle, Skeleton } from '@/components/ui'
import { useMediaQuery } from '@/stores/media'
import { Page } from '@/components/shell/Page'
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
            <span className="font-medium">{r.name}</span>
            {/* the repository only: its branches (and the worktree folders of the same clone) are in its graph;
                the checked-out branch shows only when it is not the usual one (or HEAD is detached) */}
            {!r.error && !(r.branch && ['main', 'master'].includes(r.branch)) && (
              <span className="rounded bg-primary/15 px-1.5 py-px font-mono text-[11px] text-primary">
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
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                <Github className="size-3" />
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

function RepoList({ onOpen }: { onOpen: (repo: string) => void }) {
  const t = useT()
  const qc = useQueryClient()
  const { data, isLoading, error } = useGitRepos()
  const [tab, setTab] = React.useState<'local' | 'github'>('local')
  const [q, setQ] = React.useState('')
  const [refreshing, setRefreshing] = React.useState(false)
  const refresh = async () => {
    setRefreshing(true)
    try {
      qc.setQueryData(gitKeys.repos, await refreshGitRepos())
      await qc.invalidateQueries({ queryKey: ['git', 'graph'] })
    } finally {
      setRefreshing(false)
    }
  }
  const needle = q.trim().toLowerCase()
  const local = (data?.local || []).filter((r) => !needle || `${r.path} ${r.github || ''} ${r.branch || ''}`.toLowerCase().includes(needle))
  const gh = data?.github
  const [account, setAccount] = React.useState<string | null>(null)
  const remote = (gh?.repos || []).filter(
    (r) => (!account || r.accounts.includes(account)) && (!needle || `${r.full_name} ${r.description} ${r.keys.join(' ')}`.toLowerCase().includes(needle)),
  )
  const accounts = gh?.accounts || []
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          value={tab}
          onChange={setTab}
          aria-label={t('git.source')}
          options={[
            { value: 'local', label: `${t('git.tabLocal')} · ${data?.local.length ?? '…'}` },
            {
              value: 'github',
              label: accounts.length === 1 ? `GitHub @${accounts[0].login} · ${gh!.repos.length}` : accounts.length > 1 ? `GitHub · ${t('git.accountsCount', { count: accounts.length })} · ${gh!.repos.length}` : 'GitHub',
            },
          ]}
        />
        <div className="relative ml-auto min-w-40 flex-1 sm:w-64 sm:flex-none">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('git.search')} className="pl-8" />
        </div>
        <Button variant="outline" size="icon" loading={refreshing} onClick={() => void refresh()} aria-label={t('git.refresh')}>
          <RefreshCw />
        </Button>
      </div>
      {isLoading ? (
        <div className="grid gap-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-20 rounded-xl" />
          ))}
        </div>
      ) : error ? (
        <p className="text-sm text-destructive">{errorMessage(error)}</p>
      ) : tab === 'local' ? (
        local.length ? (
          <>
            <p className="text-xs text-muted-foreground">{t('git.localHint', { root: data!.root })}</p>
            <ul className="grid gap-2 lg:grid-cols-2">
              {local.map((r) => (
                <LocalRow key={r.path} r={r} root={data!.root} onOpen={() => onOpen(r.path)} />
              ))}
            </ul>
          </>
        ) : (
          <EmptyState icon={FolderGit2} title={t('git.noLocal')} description={t('git.localHint', { root: data?.root || '' })} />
        )
      ) : !gh?.connected ? (
        <ConnectGithub />
      ) : !accounts.length ? (
        <div className="grid gap-3">
          <TokenErrors errors={gh.errors} />
          <ConnectGithub />
        </div>
      ) : (
        <div className="grid gap-3">
          <div className="flex flex-wrap items-center gap-2" data-testid="git-accounts">
            <span className="text-xs text-muted-foreground">{t('git.accounts')}</span>
            {accounts.map((a) => (
              <button
                key={a.login}
                type="button"
                onClick={() => setAccount((cur) => (cur === a.login ? null : a.login))}
                title={`${t('git.viaKeys')} ${a.keys.join(', ')}`}
                aria-pressed={account === a.login}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-full border py-0.5 pr-2.5 pl-0.5 text-xs transition-colors hover:bg-accent',
                  account === a.login && 'border-primary bg-primary/10',
                )}
              >
                {a.avatar ? <img src={a.avatar} alt="" className="size-5 rounded-full" /> : <Github className="m-0.5 size-4" />}
                <span className="font-medium">@{a.login}</span>
                <span className="text-muted-foreground">
                  {a.repos} · {t('git.keysCount', { count: a.keys.length })}
                </span>
              </button>
            ))}
            <Link to="/settings/keys" className="ml-1 text-xs text-primary hover:underline">
              {t('git.addAccount')}
            </Link>
          </div>
          <TokenErrors errors={gh.errors} />
          <ul className="grid gap-2 lg:grid-cols-2">
            {remote.map((r) => (
              <GithubRow key={r.full_name} r={r} onOpen={() => onOpen(`github:${r.full_name}`)} />
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function RepoView({ repo, onBack, onSwitch }: { repo: string; onBack: () => void; onSwitch: (repo: string) => void }) {
  const t = useT()
  const lang = useLang()
  const [limit, setLimit] = React.useState(200)
  const { data, error, isLoading, isFetching } = useGitGraph(repo, { limit })
  const { data: overview } = useGitRepos()
  const pulls = useGitPulls(repo)
  const [selected, setSelected] = React.useState<string | null>(null)
  React.useEffect(() => setSelected(null), [repo])
  // below lg the side column falls under a long graph: the picked commit opens in a bottom sheet instead
  const wide = useMediaQuery('(min-width: 1024px)')
  const r = data?.repo
  const isGh = repo.startsWith('github:')
  // the other side of the same repository (clone <-> GitHub), when there is one
  const other = isGh
    ? overview?.local.find((l) => l.github && `github:${l.github}`.toLowerCase() === repo.toLowerCase())?.path
    : r?.github && overview?.github.connected
      ? `github:${r.github}`
      : null
  const ghInfo = isGh ? overview?.github.repos.find((g) => `github:${g.full_name}`.toLowerCase() === repo.toLowerCase()) : null
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft /> {t('git.allRepos')}
        </Button>
        {isGh ? <Github className="size-5 text-primary" /> : <FolderGit2 className="size-5 text-primary" />}
        <h2 className="text-lg font-semibold">{isGh ? repo.slice(7) : r?.name || repo.split('/').pop()}</h2>
        {r?.branch && <span className="rounded bg-primary/15 px-1.5 py-px font-mono text-xs text-primary">{r.branch}</span>}
        {(r?.permission || ghInfo?.permission) && <PermBadge p={(r?.permission || ghInfo?.permission)!} />}
        <Sync ahead={r?.ahead} behind={r?.behind} changed={(r?.changed || 0) + (r?.untracked || 0)} />
        <span className="ml-auto flex items-center gap-2">
          {other && (
            <Button variant="outline" size="sm" onClick={() => onSwitch(other)}>
              {isGh ? <Server /> : <Github />} {isGh ? t('git.seeLocal') : t('git.seeGithub')}
            </Button>
          )}
          {(r?.url || (r?.github && `https://github.com/${r.github}`)) && (
            <Button variant="ghost" size="sm" asChild>
              <a href={r?.url || `https://github.com/${r!.github}`} target="_blank" rel="noopener noreferrer">
                GitHub <ExternalLink />
              </a>
            </Button>
          )}
        </span>
      </div>
      {!isGh && r?.path && (
        <p className="-mt-2 font-mono text-xs break-all text-muted-foreground">
          {r.path}
          {r.upstream && ` · ${t('git.tracks', { upstream: r.upstream })}`}
        </p>
      )}
      {isGh && r?.description && <p className="-mt-2 text-[13px] text-muted-foreground">{r.description}</p>}
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
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
        <div className="grid gap-4 lg:sticky lg:top-4">
          {!wide ? null : selected ? (
            <CommitDetail repo={data?.repo.id || repo} sha={selected} />
          ) : (
            <p className="rounded-xl border border-dashed p-4 text-[13px] text-muted-foreground">{t('git.pickCommit')}</p>
          )}
          {isGh && (
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
                <ul className="grid gap-1.5">
                  {pulls.data.map((p) => (
                    <li key={p.number}>
                      <a href={p.url} target="_blank" rel="noopener noreferrer" className="grid gap-0.5 rounded-md p-1.5 text-[13px] hover:bg-accent/60">
                        <span className="truncate">
                          <span className="text-muted-foreground">#{p.number}</span> {p.title}
                          {p.draft && <span className="ml-1 text-xs text-muted-foreground">({t('git.draft')})</span>}
                        </span>
                        <span className="flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
                          <GitBranch className="size-3" />
                          {p.head} → {p.base} · {p.author} · {fmtRelative(p.updated, lang)}
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
  )
}

export default function GitPage() {
  const t = useT()
  const [params, setParams] = useSearchParams()
  const repo = params.get('repo')
  const open = (r: string | null) => setParams(r ? { repo: r } : {}, { replace: false })
  return (
    <Page title={t('git.title')} description={t('git.desc')}>
      {repo ? <RepoView repo={repo} onBack={() => open(null)} onSwitch={open} /> : <RepoList onOpen={open} />}
    </Page>
  )
}
