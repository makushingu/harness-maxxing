// Feature page "Git & GitHub" (/git, Settings -> Features -> git_page). Second-level sidebar: every repository once, by
// workspace project (a clone and its GitHub side are one entry; GitHub repositories not cloned here in their own group).
// Overview: what needs attention, a table of the server's clones, a table of the GitHub repositories. A repository: graph
// of branches and commits, commit details, open pull requests, Server | GitHub switch when it has both sides.
// The repository shown is in the URL (?repo=<path or github:owner/name>), so a chat block can link to it.
import * as React from 'react'
import { Link, useSearchParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown, ArrowUp, CheckCircle2, ChevronRight, ExternalLink, FolderGit2, GitBranch, GitPullRequest, KeyRound, LayoutGrid, Lock, PencilLine, RefreshCw, Server,
} from 'lucide-react'
import { gitKeys, refreshGitRepos, useGitGraph, useGitPulls, useGitRepos } from '@/lib/queries'
import type { GitHubRepo, GitLocalRepo, GitOverview, GitPermission } from '@/lib/types'
import { errorMessage } from '@/lib/api'
import { fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { Badge, Button, EmptyState, Segmented, Sheet, SheetBody, SheetContent, SheetTitle, Skeleton } from '@/components/ui'
import { useCompact, useMediaQuery } from '@/stores/media'
import { Page } from '@/components/shell/Page'
import { ListChips, ListEntry, PageList } from '@/components/shell/PageList'
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

// ---- the list (second-level sidebar): every repository once, by workspace project ----------------------------------

type Entry = {
  /** what ?repo= takes: a clone's path, or github:owner/name for a repository not cloned here */
  id: string
  /** github:owner/name of a clone (its GitHub side) */
  gh: string | null
  label: string
  /** shown when two entries have the same name: the folder holding the clone */
  sub?: string
  group: string
  local?: GitLocalRepo
  remote?: GitHubRepo
  when: number
}

const GROUP_EXT = '~ext'
const GROUP_OTHER = '~other'
const GROUP_GITHUB = '~github'

/** The workspace project a clone belongs to (its folder), else Extensions / elsewhere on the server. */
function groupOf(path: string): string {
  const m = path.match(/\/projects\/([^/]+)\//)
  if (m) return m[1]
  if (/\/extensions\//.test(path)) return GROUP_EXT
  return GROUP_OTHER
}

const todoOf = (r: GitLocalRepo) => !r.error && (r.ahead > 0 || r.behind > 0 || r.changed + r.untracked > 0)

function entriesOf(data: GitOverview | undefined): Entry[] {
  if (!data) return []
  const out: Entry[] = []
  for (const r of data.local) {
    out.push({
      id: r.path,
      gh: r.github ? `github:${r.github}` : null,
      // a clone named "repo" or "code" reads better under its GitHub name
      label: r.github ? r.github.split('/')[1] : r.name,
      group: groupOf(r.path),
      local: r,
      when: r.last_commit || 0,
    })
  }
  if (data.github.connected) {
    for (const g of data.github.repos) {
      if (g.local_paths.length) continue
      out.push({ id: `github:${g.full_name}`, gh: `github:${g.full_name}`, label: g.name, group: GROUP_GITHUB, remote: g, when: g.pushed_at ? Date.parse(g.pushed_at) / 1000 : 0 })
    }
  }
  const seen = new Map<string, number>()
  for (const e of out) seen.set(e.label.toLowerCase(), (seen.get(e.label.toLowerCase()) || 0) + 1)
  for (const e of out) {
    if ((seen.get(e.label.toLowerCase()) || 0) < 2) continue
    e.sub = e.local ? e.local.path.split('/').slice(-2, -1)[0] : e.remote?.owner
  }
  return out
}

function groupLabel(g: string, t: ReturnType<typeof useT>) {
  return g === GROUP_EXT ? t('git.group.ext') : g === GROUP_OTHER ? t('git.group.other') : g === GROUP_GITHUB ? t('git.group.github') : g
}

const groupRank = (g: string) => (g === GROUP_EXT ? 1 : g === GROUP_OTHER ? 2 : g === GROUP_GITHUB ? 3 : 0)

function GitNav({ repo, query, onOpen }: { repo: string | null; query: string; onOpen: (r: string | null) => void }) {
  const t = useT()
  const touch = useCompact()
  const { data, isLoading } = useGitRepos()
  const [filter, setFilter] = React.useState<'all' | 'todo'>('all')
  const [folded, setFolded] = React.useState<Set<string>>(() => new Set([GROUP_GITHUB]))
  const all = React.useMemo(() => entriesOf(data), [data])
  const todo = all.filter((e) => e.local && todoOf(e.local)).length
  const needle = query.trim().toLowerCase()
  const shown = all.filter(
    (e) =>
      (filter === 'all' || (e.local && todoOf(e.local))) &&
      (!needle || `${e.label} ${e.id} ${e.gh || ''} ${e.remote?.description || ''}`.toLowerCase().includes(needle)),
  )
  const groups = [...new Set(shown.map((e) => e.group))].sort((a, b) => groupRank(a) - groupRank(b) || a.localeCompare(b))
  const active = (e: Entry) => !!repo && (repo === e.id || (!!e.gh && repo.toLowerCase() === e.gh.toLowerCase()))
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className={cn('grid gap-0.5 p-2 pb-1', touch && 'gap-1')}>
        <ListEntry active={!repo} onClick={() => onOpen(null)} icon={LayoutGrid} label={t('git.overview')} testid="git-overview" />
        <ListChips
          className="mt-1"
          label={t('git.filter')}
          value={filter}
          onChange={setFilter}
          items={[
            { key: 'all', label: t('git.chip.all'), count: all.length },
            { key: 'todo', label: t('git.chip.todo'), count: todo, dot: <span className="size-1.5 rounded-full bg-warning" /> },
          ]}
        />
      </div>
      <nav aria-label={t('git.title')} className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] content-start overflow-y-auto px-2 pb-3" data-testid="git-nav">
        {isLoading && [0, 1, 2, 3].map((i) => <Skeleton key={i} className="mx-2.5 my-1.5 h-5" />)}
        {!isLoading && !shown.length && <p className="px-2.5 py-2 text-[13px] text-muted-foreground">{t('git.noMatch')}</p>}
        {groups.map((g) => {
          const list = shown.filter((e) => e.group === g).sort((a, b) => b.when - a.when)
          const closed = !needle && folded.has(g) && !list.some(active)
          return (
            <div key={g} className="mt-2">
              <button
                type="button"
                onClick={() => setFolded((f) => { const n = new Set(f); if (n.has(g)) n.delete(g); else n.add(g); return n })}
                className="flex h-6 w-full items-center gap-1 rounded px-2.5 text-left text-[11px] font-semibold tracking-wide text-muted-foreground uppercase hover:text-foreground pointer-coarse:h-9"
                aria-expanded={!closed}
              >
                <ChevronRight className={cn('size-3 shrink-0 transition-transform', !closed && 'rotate-90')} />
                <span className="min-w-0 flex-1 truncate">{groupLabel(g, t)}</span>
                <span className="font-normal tabular-nums">{list.length}</span>
              </button>
              {!closed &&
                list.map((e) => {
                  const on = active(e)
                  const r = e.local
                  return (
                    <button
                      key={e.id}
                      type="button"
                      onClick={() => onOpen(e.id)}
                      aria-current={on ? 'page' : undefined}
                      title={r ? r.path : e.remote?.full_name}
                      className={cn(
                        'flex w-full min-w-0 items-center gap-2 rounded-md px-2.5 text-left text-[13px] text-muted-foreground outline-none transition-colors hover:bg-accent/50 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
                        touch ? 'h-11' : 'h-8',
                        on && 'bg-accent font-medium text-foreground hover:bg-accent',
                      )}
                      data-testid="git-entry"
                    >
                      {r ? <FolderGit2 className={cn('size-4 shrink-0', on && 'text-primary')} /> : <Github className={cn('size-4 shrink-0', on && 'text-primary')} />}
                      <span className="min-w-0 flex-1 truncate">
                        {e.label}
                        {e.sub && <span className="ml-1.5 text-xs font-normal text-muted-foreground">{e.sub}</span>}
                      </span>
                      {r && !!r.ahead && (
                        <span className="inline-flex items-center text-[11px] text-warning tabular-nums" title={t('git.aheadTip', { count: r.ahead })}>
                          <ArrowUp className="size-3" />
                          {r.ahead}
                        </span>
                      )}
                      {r && r.changed + r.untracked > 0 && <PencilLine className="size-3 shrink-0 text-muted-foreground" aria-label={t('git.uncommitted', { count: r.changed + r.untracked })} />}
                      {e.remote?.private && <Lock className="size-3 shrink-0 text-muted-foreground" />}
                    </button>
                  )
                })}
            </div>
          )
        })}
      </nav>
    </div>
  )
}

// ---- the overview: what needs attention, then a table of the server's clones and one of the GitHub repositories ----

function Section({ title, count, children, actions }: { title: React.ReactNode; count?: number; children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <section className="grid grid-cols-[minmax(0,1fr)] gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        {count != null && <span className="text-xs text-muted-foreground tabular-nums">{count}</span>}
        {actions && <span className="ml-auto flex items-center gap-2">{actions}</span>}
      </div>
      {children}
    </section>
  )
}

const TH = 'h-9 px-3 text-left text-xs font-medium text-muted-foreground whitespace-nowrap'
const TD = 'px-3 py-2 align-middle'

function Overview({ onOpen }: { onOpen: (repo: string) => void }) {
  const t = useT()
  const lang = useLang()
  const { data, isLoading, error } = useGitRepos()
  const [account, setAccount] = React.useState<string | null>(null)
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
  const root = data.root
  const rel = (p: string) => (p.startsWith(root + '/') ? p.slice(root.length + 1) : p)
  const local = [...data.local].sort((a, b) => (b.last_commit || 0) - (a.last_commit || 0))
  const todo = local.filter(todoOf)
  const gh = data.github
  const accounts = gh.accounts
  const remote = [...gh.repos]
    .filter((r) => !account || r.accounts.includes(account))
    .sort((a, b) => (b.pushed_at ? Date.parse(b.pushed_at) : 0) - (a.pushed_at ? Date.parse(a.pushed_at) : 0))
  const nameOf = (r: GitLocalRepo) => (r.github ? r.github.split('/')[1] : r.name)
  const project = (r: GitLocalRepo) => groupLabel(groupOf(r.path), t)
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-8">
      <Section title={t('git.todo')} count={todo.length || undefined}>
        {todo.length ? (
          <ul className="grid grid-cols-[minmax(0,1fr)] gap-2 sm:grid-cols-2 xl:grid-cols-3" data-testid="git-todo">
            {todo.map((r) => (
              <li key={r.path}>
                <button type="button" onClick={() => onOpen(r.path)} className="grid h-full w-full gap-1 rounded-xl border bg-card p-3 text-left transition-colors hover:border-primary/40 hover:bg-accent/40">
                  <span className="flex min-w-0 items-center gap-2">
                    <FolderGit2 className="size-4 shrink-0 text-primary" />
                    <span className="min-w-0 truncate font-medium">{nameOf(r)}</span>
                    <span className="ml-auto truncate text-xs text-muted-foreground">{project(r)}</span>
                  </span>
                  <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <Sync ahead={r.ahead} behind={r.behind} changed={r.changed + r.untracked} />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="flex items-center gap-2 rounded-xl border border-dashed p-4 text-[13px] text-muted-foreground">
            <CheckCircle2 className="size-4 text-success" /> {t('git.todoNone')}
          </p>
        )}
      </Section>

      <Section title={t('git.tabLocal')} count={local.length}>
        {local.length ? (
          <div className="overflow-x-auto rounded-xl border bg-card">
            <table className="w-full text-[13px]" data-testid="git-table-local">
              <thead className="border-b">
                <tr>
                  <th className={TH}>{t('git.col.repo')}</th>
                  <th className={cn(TH, 'max-md:hidden')}>{t('git.col.project')}</th>
                  <th className={cn(TH, 'max-sm:hidden')}>{t('git.col.branch')}</th>
                  <th className={TH}>{t('git.col.state')}</th>
                  <th className={cn(TH, 'max-lg:hidden')}>{t('git.col.last')}</th>
                </tr>
              </thead>
              <tbody>
                {local.map((r) => (
                  <tr key={r.path} onClick={() => onOpen(r.path)} className="cursor-pointer border-b last:border-0 hover:bg-accent/40">
                    <td className={TD}>
                      <button type="button" className="grid min-w-0 text-left" onClick={(e) => { e.stopPropagation(); onOpen(r.path) }}>
                        <span className="flex items-center gap-1.5 font-medium whitespace-nowrap">
                          {nameOf(r)}
                          {r.github && <Github className="size-3 shrink-0 text-muted-foreground" />}
                        </span>
                        <span className="max-w-[26ch] truncate font-mono text-[11px] text-muted-foreground">{rel(r.path)}</span>
                      </button>
                    </td>
                    <td className={cn(TD, 'whitespace-nowrap text-muted-foreground max-md:hidden')}>{project(r)}</td>
                    <td className={cn(TD, 'max-sm:hidden')}>
                      <span className={cn('rounded px-1.5 py-px font-mono text-[11px]', r.branch ? 'bg-muted' : 'bg-warning/15 text-warning')}>{r.branch ?? t('git.detached')}</span>
                    </td>
                    <td className={TD}>
                      {r.error ? (
                        <span className="text-xs text-destructive">{t('git.error')}</span>
                      ) : todoOf(r) ? (
                        <span className="flex items-center gap-x-2 whitespace-nowrap">
                          <Sync ahead={r.ahead} behind={r.behind} changed={r.changed + r.untracked} />
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground">{t('git.clean')}</span>
                      )}
                    </td>
                    <td className={cn(TD, 'max-w-[40ch] max-lg:hidden')}>
                      {r.last_commit && (
                        <span className="block truncate text-xs text-muted-foreground">
                          <span className="text-foreground">{fmtRelative(r.last_commit, lang)}</span> · {r.last_subject}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState icon={FolderGit2} title={t('git.noLocal')} description={t('git.localHint', { root })} />
        )}
      </Section>

      <Section
        title="GitHub"
        count={gh.connected ? remote.length : undefined}
        actions={
          accounts.length > 0 && (
            <span className="flex flex-wrap items-center gap-1.5" data-testid="git-accounts">
              {accounts.map((a) => (
                <button
                  key={a.login}
                  type="button"
                  onClick={() => setAccount((cur) => (cur === a.login ? null : a.login))}
                  title={`${t('git.viaKeys')} ${a.keys.join(', ')}`}
                  aria-pressed={account === a.login}
                  className={cn('inline-flex items-center gap-1.5 rounded-full border py-0.5 pr-2.5 pl-0.5 text-xs transition-colors hover:bg-accent', account === a.login && 'border-primary bg-primary/10')}
                >
                  {a.avatar ? <img src={a.avatar} alt="" className="size-5 rounded-full" /> : <Github className="m-0.5 size-4" />}
                  <span className="font-medium">@{a.login}</span>
                  <span className="text-muted-foreground">{a.repos}</span>
                </button>
              ))}
              <Link to="/settings/keys" className="text-xs text-primary hover:underline">
                {t('git.addAccount')}
              </Link>
            </span>
          )
        }
      >
        {!gh.connected ? (
          <ConnectGithub />
        ) : !accounts.length ? (
          <div className="grid gap-3">
            <TokenErrors errors={gh.errors} />
            <ConnectGithub />
          </div>
        ) : (
          <>
            <TokenErrors errors={gh.errors} />
            <div className="overflow-x-auto rounded-xl border bg-card">
              <table className="w-full text-[13px]" data-testid="git-table-github">
                <thead className="border-b">
                  <tr>
                    <th className={TH}>{t('git.col.repo')}</th>
                    <th className={cn(TH, 'max-sm:hidden')}>{t('git.col.visibility')}</th>
                    <th className={cn(TH, 'max-md:hidden')}>{t('git.col.rights')}</th>
                    <th className={TH}>{t('git.col.here')}</th>
                    <th className={cn(TH, 'max-lg:hidden')}>{t('git.col.pushed')}</th>
                  </tr>
                </thead>
                <tbody>
                  {remote.map((r) => (
                    <tr key={r.full_name} onClick={() => onOpen(`github:${r.full_name}`)} className="cursor-pointer border-b last:border-0 hover:bg-accent/40">
                      <td className={TD}>
                        <button type="button" className="grid min-w-0 text-left" onClick={(e) => { e.stopPropagation(); onOpen(`github:${r.full_name}`) }}>
                          <span className="flex flex-wrap items-center gap-1.5">
                            <span className="font-medium">
                              <span className="font-normal text-muted-foreground">{r.owner}/</span>
                              {r.name}
                            </span>
                            {r.archived && <Badge variant="muted">{t('git.archived')}</Badge>}
                            {r.fork && <Badge variant="muted">fork</Badge>}
                          </span>
                          {r.description && <span className="max-w-[48ch] truncate text-xs text-muted-foreground">{r.description}</span>}
                        </button>
                      </td>
                      <td className={cn(TD, 'text-xs text-muted-foreground max-sm:hidden')}>
                        {r.private ? (
                          <span className="inline-flex items-center gap-1">
                            <Lock className="size-3" />
                            {t('git.private')}
                          </span>
                        ) : (
                          t('git.public')
                        )}
                      </td>
                      <td className={cn(TD, 'max-md:hidden')}>
                        <PermBadge p={r.permission} />
                      </td>
                      <td className={TD}>
                        {r.local_paths.length ? (
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); onOpen(r.local_paths[0]) }}
                            title={r.local_paths.map(rel).join('\n')}
                            className="inline-flex items-center gap-1 text-xs text-success hover:underline"
                          >
                            <Server className="size-3" />
                            {r.local_paths.length > 1 ? t('git.clones', { count: r.local_paths.length }) : t('git.clonedHere')}
                          </button>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className={cn(TD, 'text-xs whitespace-nowrap text-muted-foreground max-lg:hidden')}>{r.pushed_at ? fmtRelative(Date.parse(r.pushed_at) / 1000, lang) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Section>
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
  // below lg the side column falls under a long graph: the picked commit opens in a bottom sheet instead
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
  const [query, setQuery] = React.useState('')
  const [refreshing, setRefreshing] = React.useState(false)
  const open = (r: string | null) => setParams(r ? { repo: r } : {}, { replace: false })
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
  return (
    <>
      <PageList id="git" label={t('git.title')} search={{ value: query, onChange: setQuery, placeholder: t('git.searchList') }}>
        <GitNav repo={repo} query={query} onOpen={open} />
      </PageList>
      {repo ? (
        <RepoView key={repo} repo={repo} onSwitch={open} refresh={refresh} />
      ) : (
        <Page title={t('git.overview')} description={t('git.desc')} actions={refresh} width="wide">
          <Overview onOpen={open} />
        </Page>
      )}
    </>
  )
}
