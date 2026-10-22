import { ExternalLink, FileText } from 'lucide-react'
import { useGitCommit } from '@/lib/queries'
import { errorMessage } from '@/lib/api'
import { fmtDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { CopyButton, Skeleton } from '@/components/ui'

/** One commit: full message, author, date, files touched with +/- (the diff stays in git / GitHub). */
export function CommitDetail({ repo, sha, className }: { repo: string; sha: string; className?: string }) {
  const t = useT()
  const lang = useLang()
  const { data, isLoading, error } = useGitCommit(repo, sha)
  if (isLoading) return <Skeleton className={cn('h-28 rounded-lg', className)} />
  if (error || !data) return <p className={cn('text-[13px] text-destructive', className)}>{errorMessage(error)}</p>
  const [title, ...body] = data.message.split('\n')
  const add = data.files.reduce((n, f) => n + (f.additions || 0), 0)
  const del = data.files.reduce((n, f) => n + (f.deletions || 0), 0)
  return (
    <div className={cn('grid gap-3 rounded-lg border bg-card p-3 text-[13px]', className)} data-testid="git-commit">
      <div className="grid gap-1">
        <p className="font-medium break-words">{title}</p>
        {body.join('\n').trim() && <pre className="font-sans text-[13px] whitespace-pre-wrap text-muted-foreground">{body.join('\n').trim()}</pre>}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>{data.author}</span>
        <span>{fmtDate(data.date, lang)}</span>
        <span className="inline-flex items-center gap-1 font-mono">
          {data.sha.slice(0, 10)}
          <CopyButton text={data.sha} className="size-5" />
        </span>
        {data.parents.length > 1 && <span>{t('git.mergeOf', { count: data.parents.length })}</span>}
        {data.url && (
          <a href={data.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
            GitHub <ExternalLink className="size-3" />
          </a>
        )}
      </div>
      {data.files.length > 0 && (
        <div className="grid gap-1">
          <p className="text-xs text-muted-foreground">
            {t('git.filesChanged', { count: data.files_total })} · <span className="text-success">+{add}</span> <span className="text-destructive">−{del}</span>
          </p>
          <ul className="grid max-h-56 gap-0.5 overflow-auto">
            {data.files.map((f) => (
              <li key={f.path} className="flex items-center gap-2 font-mono text-xs">
                <FileText className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate" title={f.path}>
                  {f.path}
                </span>
                {f.additions !== null ? (
                  <span className="shrink-0 tabular-nums">
                    <span className="text-success">+{f.additions}</span> <span className="text-destructive">−{f.deletions}</span>
                  </span>
                ) : (
                  <span className="shrink-0 text-muted-foreground">bin</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
