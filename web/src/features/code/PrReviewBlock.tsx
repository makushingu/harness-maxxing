// A ```pr-review block in a conversation: the review Claude wrote for a pull request ("Ask Claude to review" in the PR
// view). Nothing is sent by Claude: the user reads it, may change the verdict, then publishes it on GitHub in one click.
//   {"repo": "owner/name", "number": 7, "event": "COMMENT", "summary": "…", "comments": [{"path": "a.ts", "line": 12, "body": "…"}]}
import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Check, GitPullRequest, Loader2, Send } from 'lucide-react'
import { Button, CodeBlock, Select, Sensitive, toast } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { openPr, prApi, prKeys, type DraftComment, type ReviewEvent } from './prApi'

type Review = { repo: string; number: number; event: ReviewEvent; summary: string; comments: DraftComment[] }
const EVENTS: ReviewEvent[] = ['COMMENT', 'APPROVE', 'REQUEST_CHANGES']
const REPO_RE = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/

function parse(code: string): Review | null {
  try {
    const j = JSON.parse(code) as Partial<Review>
    if (typeof j.repo !== 'string' || !REPO_RE.test(j.repo) || !Number.isInteger(j.number)) return null
    const comments = (Array.isArray(j.comments) ? j.comments : [])
      .filter((c): c is DraftComment => !!c && typeof c.path === 'string' && Number.isInteger(c.line) && typeof c.body === 'string' && !!c.body.trim())
      .slice(0, 100)
    return { repo: j.repo, number: j.number as number, event: EVENTS.includes(j.event as ReviewEvent) ? (j.event as ReviewEvent) : 'COMMENT', summary: typeof j.summary === 'string' ? j.summary : '', comments }
  } catch {
    return null
  }
}

const sentKey = (code: string) => {
  let h = 0
  for (let i = 0; i < code.length; i++) h = (h * 31 + code.charCodeAt(i)) | 0
  return `mx-pr-review:${h}`
}

function PrReviewBlock({ code, className }: { code: string; className?: string }) {
  const t = useT()
  const qc = useQueryClient()
  const r = React.useMemo(() => parse(code), [code])
  const [event, setEvent] = React.useState<ReviewEvent>(r?.event ?? 'COMMENT')
  const [busy, setBusy] = React.useState(false)
  const [sent, setSent] = React.useState(() => localStorage.getItem(sentKey(code)) === '1')
  if (!r) return <CodeBlock code={code} className={className} />
  const publish = async () => {
    setBusy(true)
    try {
      await prApi.review(r.repo, r.number, event, r.summary, r.comments)
      localStorage.setItem(sentKey(code), '1')
      setSent(true)
      void qc.invalidateQueries({ queryKey: prKeys.one(r.repo, r.number) })
      toast.success(t('pr.published'))
    } catch (e) {
      toast.error(t('code.failed'), errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className={cn('overflow-hidden rounded-lg border', className)} data-testid="pr-review-block">
      <div className="flex flex-wrap items-center gap-2 border-b bg-fill-1 px-3 py-2 text-[13px]">
        <GitPullRequest className="size-4 text-muted-foreground" />
        <span className="font-medium">{t('pr.draftTitle')}</span>
        <button type="button" onClick={() => void openPr(r.repo, r.number)} className="text-muted-foreground hover:text-foreground hover:underline">
          <Sensitive>{`${r.repo} #${r.number}`}</Sensitive>
        </button>
      </div>
      {r.summary.trim() && <p className="border-b px-3 py-2 text-[13px] whitespace-pre-wrap">{r.summary}</p>}
      {r.comments.length > 0 && (
        <ul className="list-none divide-y p-0 text-[13px]">
          {r.comments.map((c, i) => (
            <li key={i} className="px-3 py-1.5">
              <span className="font-mono text-[11px] text-muted-foreground"><Sensitive>{`${c.path}:${c.line}`}</Sensitive></span>
              <p className="whitespace-pre-wrap">{c.body}</p>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2 border-t px-3 py-2">
        {sent ? (
          <span className="inline-flex items-center gap-1 text-[13px] text-success"><Check className="size-4" />{t('pr.published')}</span>
        ) : (
          <>
            <Select value={event} onValueChange={(v) => setEvent(v as ReviewEvent)} options={EVENTS.map((e) => ({ value: e, label: t(`pr.event.${e}`) }))} aria-label={t('pr.eventLabel')} className="h-8 w-auto" />
            <Button size="sm" onClick={() => void publish()} disabled={busy} data-testid="pr-review-publish">
              {busy ? <Loader2 className="animate-spin" /> : <Send />}
              {t('pr.publish')}
            </Button>
            <span className="text-[11px] text-muted-foreground">{t('pr.publishHint')}</span>
          </>
        )}
      </div>
    </div>
  )
}

export default PrReviewBlock
