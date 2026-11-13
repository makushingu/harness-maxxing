// The end of a failed turn (usage limit, API down, crashed process) as one card: what happened in plain words,
// Resume, the model of the next turn, and the technical lines behind "Details". The card of a turn the thread no
// longer ends on (something was sent since) only tells what happened.
import * as React from 'react'
import { ChevronRight, CircleAlert, ExternalLink, Hourglass, RotateCw, ServerCrash } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Button, Sensitive } from '@/components/ui'
import type { Cut } from './log'

/** What the card of the failed turn the thread ends on can do (set by the session column; unset: nothing). */
export type CutActions = {
  /** Sends `text` as the next message of the session. */
  resume?: (text: string) => void
  /** The model picker of the session, as in the composer. */
  model?: React.ReactNode
  /** Why the session stopped, as the server keeps it (sign-in lost, out of memory…). */
  error?: string | null
}
export const CutContext = React.createContext<CutActions>({})

type Kind = 'limit' | 'busy' | 'error'
const kindOf = (cut: Cut): Kind => (cut.api === 'rate_limit' ? 'limit' : cut.api === 'server_error' || cut.api === 'overloaded' ? 'busy' : 'error')
const ICON = { limit: Hourglass, busy: ServerCrash, error: CircleAlert }
/** The page Claude Code points at to manage the usage (only a claude.ai / anthropic.com address becomes a link). */
const usageUrl = (text = '') => /https:\/\/(?:claude\.ai|(?:[a-z0-9-]+\.)*anthropic\.com)\/[^\s,)]*/.exec(text)?.[0] || null
const bare = (detail = '') => detail.replace(/^Turn failed: /, '')

export function CutCard({ cut, last, children }: { cut: Cut; /** The thread ends on this turn. */ last: boolean; /** The result line of the turn, if it has one. */ children?: React.ReactNode }) {
  const t = useT()
  const { resume, model, error } = React.useContext(CutContext)
  const [open, setOpen] = React.useState(false)
  const kind = kindOf(cut)
  const Icon = ICON[kind]
  const detail = bare(cut.detail)
  // What the server kept about the stop says more than the process's last lines, unless it is those lines.
  const kept = last && error && !detail.includes(error) && !error.includes(detail || '\0') ? error : ''
  const said = kind === 'error' ? cut.text || kept : ''
  const lines = [kind === 'error' ? (cut.text ? kept : '') : cut.text, detail].filter(Boolean).join('\n')
  const url = kind === 'limit' ? usageUrl(cut.text) : null
  const resumeText = t('cut.resumeText')
  const title = t(`cut.${kind}.title`)
  return (
    <div role={last ? 'alert' : undefined} data-testid="cut-card" data-kind={kind} className="rounded-lg border bg-fill-1 text-xs">
      <div className="flex items-start gap-2.5 px-3 pt-2.5 pb-2">
        <Icon className={cn('mt-0.5 size-4 shrink-0', kind === 'error' ? 'text-destructive' : 'text-warning')} />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] leading-5 font-medium text-foreground">{title}</div>
          <p className="mt-0.5 leading-5 text-muted-foreground [overflow-wrap:anywhere]">{said ? <Sensitive>{said}</Sensitive> : t(`cut.${kind}.text`)}</p>
          {(last && (resume || model)) || url || lines ? (
            <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1.5">
              {last && resume && (
                <Button size="sm" disabled={!resumeText} onClick={() => resume(resumeText)} data-testid="cut-resume">
                  <RotateCw /> {t('cut.resume')}
                </Button>
              )}
              {last && model}
              {url && (
                <a href={url} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1 rounded-md px-2 font-medium text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
                  {t('cut.usage')} <ExternalLink className="size-3" />
                </a>
              )}
              {lines && (
                <button
                  type="button"
                  aria-expanded={open}
                  onClick={() => setOpen((o) => !o)}
                  className="ml-auto inline-flex h-8 items-center gap-0.5 rounded-md px-2 text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                >
                  {t('cut.details')} <ChevronRight className={cn('size-3 transition-transform', open && 'rotate-90')} />
                </button>
              )}
            </div>
          ) : null}
          {open && lines && (
            <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-sunken px-2.5 py-2 font-mono text-[11px] leading-4 whitespace-pre-wrap text-muted-foreground [overflow-wrap:anywhere]">
              <Sensitive>{lines}</Sensitive>
            </pre>
          )}
        </div>
      </div>
      {children && <div className="border-t px-3 py-1.5">{children}</div>}
    </div>
  )
}
