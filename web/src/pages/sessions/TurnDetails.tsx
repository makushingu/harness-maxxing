/* What a turn did, step by step: the window opened from the line under an answer (its ⚙ menu -> "Turn details").
   Read from the session's log when asked (GET /api/sessions/{id}/turns[/{n}]): nothing is stored for it, and its
   code and texts (group `trace`) load only when it opens. */
import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Brain, ChevronLeft, ChevronRight, Download, Info, Wrench } from 'lucide-react'
import { api, seg } from '@/lib/api'
import type { TurnDetail, TurnInfo, TurnStep } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { fmtDate, fmtNumber } from '@/lib/format'
import { Button, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, Sensitive, Skeleton } from '@/components/ui'
import { fmtCost, fmtMs, fmtTokens, modelLabel } from './util'

/** The turn a result line belongs to: the last one started before the line was written. */
function turnAt(turns: TurnInfo[], at: number): number | null {
  let found: number | null = null
  for (const tn of turns) if (tn.at != null && tn.at <= at + 1) found = tn.n
  return found ?? (turns.length ? turns[turns.length - 1].n : null)
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid gap-0.5 rounded-lg border bg-fill-1 px-2.5 py-1.5">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span className="text-sm font-medium tabular-nums">{value}</span>
    </div>
  )
}

function StepRow({ s, start }: { s: TurnStep; start: number | null }) {
  const t = useT()
  const lang = useLang()
  const offset = s.at != null && start != null ? `+${fmtMs(Math.max(0, Math.round((s.at - start) * 1000)))}` : ''
  const sub = s.kind !== 'note' && s.sub
  return (
    <li className={cn('flex items-start gap-2 py-1.5 text-[13px]', sub && 'pl-5')} data-testid={`step-${s.kind}`}>
      <span className="w-16 shrink-0 pt-px text-right text-[11px] text-muted-foreground tabular-nums">{offset}</span>
      {s.kind === 'model' ? (
        <>
          <Brain className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1">
            {t('trace.model')}
            <span className="text-muted-foreground">
              {' · '}
              {t('trace.context', { tokens: fmtTokens(s.context), share: fmtNumber(s.context ? s.cache_read / s.context : 0, lang, { style: 'percent', maximumFractionDigits: 0 }) })}
              {s.thinking && ` · ${t('trace.thinking')}`}
              {sub && ` · ${t('trace.sub')}`}
            </span>
          </span>
        </>
      ) : s.kind === 'tool' ? (
        <>
          {s.error ? <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-destructive" /> : <Wrench className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />}
          <span className="min-w-0 flex-1 break-words">
            <Sensitive length={16}>{s.summary || s.name}</Sensitive>
            {sub && <span className="text-muted-foreground">{` · ${t('trace.sub')}`}</span>}
          </span>
          <span className={cn('shrink-0 text-[11px] tabular-nums', s.error ? 'text-destructive' : 'text-muted-foreground')}>
            {s.error ? t('trace.failed') : s.duration_s != null ? fmtMs(Math.round(s.duration_s * 1000)) : s.done ? '' : t('trace.noResult')}
          </span>
        </>
      ) : (
        <>
          <Info className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 break-words text-muted-foreground">{s.text}</span>
        </>
      )}
    </li>
  )
}

export default function TurnDetails({ sid, at, onClose }: { sid: string; at: number; onClose: () => void }) {
  const t = useT()
  const lang = useLang()
  const list = useQuery({ queryKey: ['sessions', sid, 'turns'], queryFn: () => api.get<{ turns: TurnInfo[] }>(`/api/sessions/${seg(sid)}/turns`), staleTime: 0 })
  const turns = list.data?.turns
  const [picked, setPicked] = React.useState<number | null>(null)
  const n = picked ?? (turns ? turnAt(turns, at) : null)
  const one = useQuery({
    queryKey: ['sessions', sid, 'turns', n],
    queryFn: () => api.get<{ turn: TurnDetail }>(`/api/sessions/${seg(sid)}/turns/${n}`),
    enabled: n != null,
    staleTime: 0,
  })
  const turn = one.data?.turn
  const last = turns?.length ? turns[turns.length - 1].n : 0
  const state = turn ? t(`trace.state.${turn.state}` as 'trace.state.done') : ''
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="md:max-w-2xl" data-testid="turn-details">
        <DialogHeader>
          <DialogTitle>{n != null ? t('trace.title', { n, count: last }) : t('trace.open')}</DialogTitle>
          <DialogDescription>{t('trace.desc')}</DialogDescription>
        </DialogHeader>
        {list.isError || one.isError || (turns && n == null) ? (
          <p className="py-6 text-center text-sm text-muted-foreground">{t('trace.none')}</p>
        ) : !turn ? (
          <div className="grid gap-2">
            <Skeleton className="h-14" />
            <Skeleton className="h-48" />
          </div>
        ) : (
          <div className="grid min-w-0 gap-3">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Fact label={t('trace.duration')} value={turn.duration_s != null ? fmtMs(Math.round(turn.duration_s * 1000)) : state} />
              <Fact label={t('trace.calls')} value={t('trace.callsValue', { model: turn.model_calls, tools: turn.tool_calls })} />
              <Fact label={t('trace.tokens')} value={`${fmtTokens(turn.total_tokens)} · ${fmtTokens(turn.tokens.output)} ${t('trace.out')}`} />
              <Fact label={t('trace.cost')} value={turn.cost_usd != null ? <Sensitive length={4}>{fmtCost(turn.cost_usd)}</Sensitive> : '–'} />
            </div>
            <p className="text-xs text-muted-foreground">
              {[turn.at != null ? fmtDate(turn.at, lang) : '', state, turn.model ? modelLabel(turn.model, []) : '', turn.errors ? t('trace.errors', { count: turn.errors }) : '']
                .filter(Boolean)
                .join(' · ')}
            </p>
            <ol className="max-h-[50vh] min-w-0 divide-y overflow-y-auto rounded-lg border px-2.5" data-testid="turn-steps">
              {turn.steps.length ? turn.steps.map((s, i) => <StepRow key={i} s={s} start={turn.at} />) : <li className="py-4 text-center text-sm text-muted-foreground">{t('trace.noSteps')}</li>}
            </ol>
            {turn.steps_dropped > 0 && <p className="text-xs text-muted-foreground">{t('trace.dropped', { count: turn.steps_dropped })}</p>}
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" size="sm" disabled={n == null || n <= 1} onClick={() => n != null && setPicked(n - 1)} aria-label={t('trace.prev')}>
                <ChevronLeft /> {t('trace.prev')}
              </Button>
              <Button variant="outline" size="sm" disabled={n == null || n >= last} onClick={() => n != null && setPicked(n + 1)} aria-label={t('trace.next')}>
                {t('trace.next')} <ChevronRight />
              </Button>
              <span className="flex-1" />
              <Button asChild variant="ghost" size="sm">
                <a href={`/api/sessions/${seg(sid)}/turns/${n}?download=1`} download={`harness-turn-${sid.slice(0, 8)}-${n}.json`} data-testid="turn-download">
                  <Download /> JSON
                </a>
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
