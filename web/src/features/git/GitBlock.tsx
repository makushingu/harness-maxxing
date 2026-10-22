// ```git blocks in the chat: Claude writes a few lines, the app draws the real graph of that repository, read live.
//   repo: /root/sites/acme            (a clone on the server - or github:owner/name)
//   branches: main, feat/login        (optional: only these branches)
//   limit: 30                         (optional: number of commits, 30 by default)
//   highlight: 3f2a9c1, 8be04d2       (optional: commits to point out)
// Part of the app for everyone (the Git page, Settings -> Features, only adds the full view).
import * as React from 'react'
import { ArrowDown, ArrowUp, ExternalLink, GitBranch, Maximize2, PencilLine } from 'lucide-react'
import { Github } from './GithubMark'
import { Link } from 'react-router'
import { useGitGraph, useSettings } from '@/lib/queries'
import { errorMessage } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { CodeBlock, Skeleton } from '@/components/ui'
import { GitGraph } from './GitGraph'
import { CommitDetail } from './CommitDetail'

export type GitBlockSpec = { repo: string; branches: string[]; limit: number; highlight: string[] }

export function parseGitBlock(code: string): GitBlockSpec | null {
  const spec: GitBlockSpec = { repo: '', branches: [], limit: 30, highlight: [] }
  for (const line of code.split('\n')) {
    const m = /^\s*(\w+)\s*:\s*(.*?)\s*$/.exec(line)
    if (!m) continue
    const [, k, v] = m
    const list = () => v.split(/[,\s]+/).filter(Boolean)
    if (k === 'repo' || k === 'path') spec.repo = v
    else if (k === 'branches' || k === 'branch') spec.branches = list()
    else if (k === 'limit') spec.limit = Math.max(1, Math.min(300, parseInt(v, 10) || 30))
    else if (k === 'highlight' || k === 'commits') spec.highlight = list().map((s) => s.toLowerCase())
  }
  if (!spec.repo && /^\s*(\/|github:)\S+\s*$/.test(code)) spec.repo = code.trim() // just a path
  return spec.repo ? spec : null
}

/** Waits until a streamed block stops changing before asking the server (no request per typed character). */
function useSettled<T>(value: T, ms = 500): T {
  const [v, setV] = React.useState(value)
  const key = JSON.stringify(value)
  React.useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ms])
  return v
}

export function GitBlock({ code, className }: { code: string; className?: string }) {
  const t = useT()
  const spec = useSettled(parseGitBlock(code))
  const { data, error, isLoading } = useGitGraph(spec?.repo || null, { limit: spec?.limit, branches: spec?.branches })
  const { data: settings } = useSettings()
  const page = !!settings?.git_page
  const [selected, setSelected] = React.useState<string | null>(null)
  const [showCode, setShowCode] = React.useState(false)
  const highlight = React.useMemo(() => new Set(spec?.highlight || []), [spec])

  if (!spec || showCode) return <CodeBlock code={code} language="yaml" className={className} />
  const repo = data?.repo
  return (
    <div className={cn('not-prose overflow-hidden rounded-xl border bg-card', className)} data-testid="git-block">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b bg-muted/30 px-3 py-2 text-[13px]">
        {repo?.kind === 'github' ? <Github className="size-4 text-muted-foreground" /> : <GitBranch className="size-4 text-muted-foreground" />}
        <span className="font-medium">{repo?.github && repo.kind === 'github' ? repo.github : repo?.name || spec.repo.split('/').pop()}</span>
        {repo?.branch && (
          <span className="rounded bg-primary/15 px-1.5 py-px font-mono text-[11px] text-primary">{repo.branch}</span>
        )}
        {!!repo?.ahead && (
          <span className="inline-flex items-center gap-0.5 text-xs text-warning" title={t('git.aheadTip', { count: repo.ahead })}>
            <ArrowUp className="size-3" />
            {repo.ahead}
          </span>
        )}
        {!!repo?.behind && (
          <span className="inline-flex items-center gap-0.5 text-xs text-muted-foreground" title={t('git.behindTip', { count: repo.behind })}>
            <ArrowDown className="size-3" />
            {repo.behind}
          </span>
        )}
        {!!(repo?.changed || repo?.untracked) && (
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <PencilLine className="size-3" />
            {t('git.uncommitted', { count: (repo.changed || 0) + (repo.untracked || 0) })}
          </span>
        )}
        <span className="ml-auto flex items-center gap-2">
          <button type="button" className="text-xs text-muted-foreground hover:text-foreground" onClick={() => setShowCode(true)}>
            {t('git.showCode')}
          </button>
          {page && repo && (
            <Link to={`/git?repo=${encodeURIComponent(repo.id)}`} className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
              <Maximize2 className="size-3" /> {t('git.openPage')}
            </Link>
          )}
          {repo?.url && (
            <a href={repo.url} target="_blank" rel="noopener noreferrer" className="text-muted-foreground hover:text-foreground" aria-label="GitHub">
              <ExternalLink className="size-3.5" />
            </a>
          )}
        </span>
      </div>
      <div className="max-h-[420px] overflow-auto p-1.5">
        {isLoading && !data ? (
          <div className="grid gap-1.5 p-1.5">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-5" />
            ))}
          </div>
        ) : error ? (
          <p className="p-2 text-[13px] text-destructive">
            {errorMessage(error)} <span className="font-mono text-xs text-muted-foreground">({spec.repo})</span>
          </p>
        ) : data && !data.commits.length ? (
          <p className="p-2 text-[13px] text-muted-foreground">{t('git.noCommits')}</p>
        ) : data ? (
          <GitGraph commits={data.commits} selected={selected} highlight={highlight} onSelect={(sha) => setSelected((s) => (s === sha ? null : sha))} compact github={repo?.github} onGithub={repo?.kind === 'github'} />
        ) : null}
      </div>
      {selected && data && (
        <div className="border-t p-2">
          <CommitDetail repo={data.repo.id} sha={selected} className="border-0 bg-transparent p-1" />
        </div>
      )}
      {data?.truncated && <p className="border-t px-3 py-1.5 text-xs text-muted-foreground">{t('git.truncated', { count: data.commits.length })}</p>}
    </div>
  )
}
export default GitBlock
