/* An agent's own usage on its page: tokens, turns and cost of its sessions, and its last 30 days (the row of this
   agent in Settings -> Usage -> Agent; GET /api/stats/tokens `agents`). Nothing while it has not run. */
import { useTokenStats } from '@/lib/queries'
import { useLang, useT } from '@/i18n'
import { fmtNumber } from '@/lib/format'
import { Sensitive } from '@/components/ui'

export function AgentUsage({ path }: { path: string }) {
  const t = useT()
  const lang = useLang()
  const { data } = useTokenStats()
  const a = data?.agents?.find((x) => x.path === path)
  if (!a || !a.total) return null
  const short = (v: number) => fmtNumber(v, lang, { notation: 'compact', maximumFractionDigits: 1 })
  const max = Math.max(1, ...a.days.map((d) => d.tokens))
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-1.5" data-testid="agent-usage">
      <div className="flex items-center gap-2">
        <span className="flex-1">{t('agents.usage.total')}</span>
        <span className="text-muted-foreground tabular-nums">
          <Sensitive length={10}>{t('agents.usage.line', { tokens: short(a.total), turns: fmtNumber(a.turns, lang), cost: `$${a.cost_usd.toFixed(2)}` })}</Sensitive>
        </span>
      </div>
      {a.days.length > 1 && (
        <div className="flex h-8 items-end gap-px" role="img" aria-label={t('agents.usage.days', { count: a.days.length })}>
          {a.days.map((d) => (
            <span key={d.date} title={`${d.date} · ${short(d.tokens)}`} className="min-w-0 flex-1 rounded-sm bg-primary/70" style={{ height: `${Math.max(4, (d.tokens / max) * 100)}%` }} />
          ))}
        </div>
      )}
    </div>
  )
}
