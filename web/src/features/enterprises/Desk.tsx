// Tab "Front desk": what visitors asked the desk (conversations, one open at a time, deletable) and the weekly insights.
import * as React from 'react'
import { MessagesSquare, Sparkles, Trash2 } from 'lucide-react'
import { useLang, useT, type TKey } from '@/i18n'
import { errorMessage } from '@/lib/api'
import { useDeleteDeskConversation, useDeskConversation, useEnterpriseDesk, useEnterpriseInsights, useRunInsights } from '@/lib/queries'
import { fmtDate, fmtRelative } from '@/lib/format'
import type { Enterprise, EnterpriseInsightItem, EnterpriseInsights } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Badge, Button, confirm, EmptyState, Sensitive, Skeleton, toast } from '@/components/ui'
import { SectionStack, SettingsCard } from '@/pages/settings/sections/ui'

export function DeskTab({ enterprise: e }: { enterprise: Enterprise }) {
  return (
    <div data-testid="enterprise-desk">
      <SectionStack>
        <Insights enterprise={e} />
        <Conversations enterprise={e} />
      </SectionStack>
    </div>
  )
}

const INSIGHT_LISTS: [keyof Pick<EnterpriseInsights, 'questions' | 'topics' | 'pains' | 'unanswered'>, TKey][] = [
  ['questions', 'ent.desk.questions'],
  ['topics', 'ent.desk.topics'],
  ['pains', 'ent.desk.pains'],
  ['unanswered', 'ent.desk.unanswered'],
]

function Insights({ enterprise: e }: { enterprise: Enterprise }) {
  const t = useT()
  const lang = useLang()
  const { data, isLoading } = useEnterpriseInsights(e.id)
  const run = useRunInsights()
  const analyze = () =>
    run.mutate(
      { id: e.id },
      { onSuccess: (r) => toast.success(t(r.built ? 'ent.desk.analyzed' : 'ent.desk.nothingNew')), onError: (err) => toast.error(errorMessage(err)) },
    )
  const empty = !data || INSIGHT_LISTS.every(([k]) => (data[k] || []).length === 0)
  return (
    <SettingsCard
      title={t('ent.desk.insights')}
      description={t('ent.desk.insightsDesc')}
      actions={
        <Button size="sm" variant="outline" onClick={analyze} loading={run.isPending} data-testid="desk-analyze">
          <Sparkles /> {t('ent.desk.analyze')}
        </Button>
      }
    >
      {isLoading ? (
        <Skeleton className="h-32" />
      ) : empty ? (
        <p className="text-[13px] text-muted-foreground" data-testid="desk-insights-empty">
          {t('ent.desk.insightsEmpty')}
        </p>
      ) : (
        <div className="grid gap-5" data-testid="desk-insights">
          <p className="text-xs text-muted-foreground">{t('ent.desk.insightsMeta', { week: data.week, count: data.conversations ?? 0, when: data.at ? fmtRelative(data.at, lang) : '-' })}</p>
          <div className="grid gap-5 md:grid-cols-2">
            {INSIGHT_LISTS.map(([k, label]) => (
              <section key={k} className="grid content-start gap-2" aria-label={t(label)}>
                <h4 className="text-sm font-medium">{t(label)}</h4>
                {(data[k] || []).length === 0 ? (
                  <p className="text-[13px] text-muted-foreground">{t('ent.desk.none')}</p>
                ) : (
                  <ul className="divide-y rounded-lg border">
                    {(data[k] as EnterpriseInsightItem[]).map((x, i) => (
                      <li key={i} className="flex items-start justify-between gap-3 px-3 py-2 text-[13px]">
                        <span className="min-w-0">
                          <Sensitive length={24}>{x.text}</Sensitive>
                          {x.department && e.departments[x.department] && <span className="block text-xs text-muted-foreground">{e.departments[x.department].name || x.department}</span>}
                        </span>
                        {x.count > 0 && <Badge variant="muted">{x.count}</Badge>}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            ))}
          </div>
        </div>
      )}
    </SettingsCard>
  )
}

function Conversations({ enterprise: e }: { enterprise: Enterprise }) {
  const t = useT()
  const lang = useLang()
  const { data, isLoading, error, refetch } = useEnterpriseDesk(e.id)
  const [open, setOpen] = React.useState<string | null>(null)
  const items = data?.conversations || []
  const current = open && items.some((c) => c.id === open) ? open : null
  return (
    <SettingsCard title={t('ent.desk.conversations')} description={t('ent.desk.conversationsDesc', { days: data?.retention_days ?? e.settings.desk?.retention_days ?? 30 })}>
      {isLoading ? (
        <Skeleton className="h-40" />
      ) : error || !data ? (
        <EmptyState
          tone="error"
          compact
          title={t('ent.desk.loadError')}
          description={errorMessage(error)}
          action={
            <Button variant="outline" size="sm" onClick={() => void refetch()}>
              {t('common.retry')}
            </Button>
          }
        />
      ) : items.length === 0 ? (
        <EmptyState compact icon={MessagesSquare} title={t('ent.desk.empty')} description={t('ent.desk.emptyDesc')} />
      ) : (
        <div className="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <ul className="max-h-[32rem] divide-y overflow-y-auto rounded-lg border" data-testid="desk-conversations">
            {items.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => setOpen(c.id)}
                  aria-current={current === c.id}
                  className={cn('grid w-full gap-0.5 px-3 py-2 text-left text-[13px] outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring max-md:min-h-12', current === c.id && 'bg-accent')}
                >
                  <span className="line-clamp-2">
                    <Sensitive length={24}>{c.summary || t('ent.desk.noSummary')}</Sensitive>
                  </span>
                  <span className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                    <span>{fmtDate(c.last, lang)}</span>
                    <span>{t('ent.desk.messages', { count: c.messages })}</span>
                    {c.pending && <Badge variant="warning">{t('ent.desk.pending')}</Badge>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <div className="min-w-0 rounded-lg border" data-testid="desk-conversation">
            {current ? <ConversationView key={current} enterprise={e} conv={current} onGone={() => setOpen(null)} /> : <p className="p-4 text-[13px] text-muted-foreground">{t('ent.desk.pick')}</p>}
          </div>
        </div>
      )}
    </SettingsCard>
  )
}

function ConversationView({ enterprise: e, conv, onGone }: { enterprise: Enterprise; conv: string; onGone: () => void }) {
  const t = useT()
  const lang = useLang()
  const { data, isLoading, error } = useDeskConversation(e.id, conv)
  const del = useDeleteDeskConversation()
  const remove = async () => {
    const ok = await confirm({ title: t('ent.desk.deleteTitle'), description: t('ent.desk.deleteDesc'), confirmText: t('ent.desk.delete'), destructive: true })
    if (ok) del.mutate({ id: e.id, conv }, { onSuccess: onGone })
  }
  return (
    <div className="grid gap-3 p-3">
      <div className="flex items-center justify-end">
        <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive" onClick={remove} loading={del.isPending} data-testid="desk-delete">
          <Trash2 /> {t('ent.desk.delete')}
        </Button>
      </div>
      {isLoading ? (
        <Skeleton className="h-32" />
      ) : error || !data ? (
        <p role="alert" className="text-[13px] text-destructive">
          {errorMessage(error)}
        </p>
      ) : (
        <ol className="grid gap-2">
          {data.map((m, i) => (
            <li key={i} className={cn('grid max-w-[90%] gap-0.5 rounded-lg px-3 py-2 text-[13px]', m.role === 'visitor' ? 'justify-self-start bg-muted' : m.role === 'assistant' ? 'justify-self-end border' : 'justify-self-center text-muted-foreground')}>
              <span className="text-xs text-muted-foreground">
                {m.role === 'visitor' ? t('ent.desk.visitor') : m.role === 'assistant' ? m.label || t('ent.desk.assistant') : t('ent.desk.system')} · {fmtDate(m.at, lang)}
              </span>
              <span className="break-words whitespace-pre-wrap">
                <Sensitive length={30}>{m.text}</Sensitive>
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
