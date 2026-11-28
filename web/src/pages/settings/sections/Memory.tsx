import { useNavigate } from 'react-router'
import { Brain, Check, Sparkles, Undo2, X } from 'lucide-react'
import { useCompactMemory, useMemory, useMemoryReview, useMemoryReviewAction, useSaveSettings, useSettings } from '@/lib/queries'
import type { MemoryReviewAction, MemoryReviewItem } from '@/lib/types'
import { fmtBytes, fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { Button, EmptyState, Select, Sensitive, Skeleton, toast, useMask } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { SettingsCard, SectionStack } from './ui'

const LIMITS = [0, 100, 150, 200, 300, 500, 1000]

export function MemorySection() {
  const t = useT()
  const lang = useLang()
  const mask = useMask()
  const navigate = useNavigate()
  const { data: settings } = useSettings()
  const save = useSaveSettings()
  const mem = useMemory()
  const compact = useCompactMemory()
  const limit = settings?.memory_max_lines ?? mem.data?.max_lines ?? 100
  const files = mem.data?.files || []
  const size = fmtBytes((limit * 1024) / 10) // the weight that goes with the line limit (memory.py)
  const over = files.filter((f) => f.over)
  const options = (LIMITS.includes(limit) ? LIMITS : [...LIMITS, limit].sort((a, b) => a - b)).map((n) => ({
    value: String(n),
    label: n ? t('memory.lines', { count: n }) : t('memory.noLimit'),
  }))

  const run = () =>
    compact.mutate(undefined, {
      onSuccess: ({ session }) => {
        toast.action(t('memory.started'), t('memory.startedDesc'), {
          label: t('notify.open'),
          onClick: () => navigate(`/sessions?path=${encodeURIComponent(session.path)}&session=${session.id}`),
        })
      },
    })

  return (
    <SectionStack>
      <SettingsCard
        title={t('memory.title')}
        description={t('memory.desc')}
        actions={
          <Button size="sm" onClick={run} loading={compact.isPending}>
            <Sparkles /> {t('memory.cleanNow')}
          </Button>
        }
      >
        <div className="divide-y">
          <SettingRow label={t('memory.limit')} description={t('memory.limitDesc')}>
            <Select
              value={String(limit)}
              onValueChange={(v) => save.mutate({ memory_max_lines: Number(v) })}
              options={options}
              aria-label={t('memory.limit')}
              className="w-40"
              disabled={!settings}
            />
          </SettingRow>
          <SettingRow label={t('memory.daily')} description={t('memory.dailyDesc')}>
            <Button variant="outline" size="sm" onClick={() => navigate('/settings/crons')}>
              {t('memory.openCrons')}
            </Button>
          </SettingRow>
        </div>
      </SettingsCard>

      <SettingsCard
        title={t('memory.files')}
        description={limit ? (over.length ? t('memory.overCount', { count: over.length, limit, size }) : t('memory.allUnder', { limit, size })) : t('memory.filesDesc')}
      >
        {mem.isPending ? (
          <div className="grid gap-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-8" />
            ))}
          </div>
        ) : files.length === 0 ? (
          <EmptyState compact icon={Brain} title={t('memory.none')} />
        ) : (
          <div className="-mx-2 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="px-2 py-1.5 font-medium">{t('memory.file')}</th>
                  <th className="px-2 py-1.5 text-right font-medium max-md:hidden">{t('memory.modified')}</th>
                  <th className="px-2 py-1.5 text-right font-medium">{t('memory.lineCount')}</th>
                  <th className="px-2 py-1.5 text-right font-medium">{t('memory.size')}</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {[...files]
                  .sort((a, b) => Number(b.over) - Number(a.over) || b.bytes - a.bytes)
                  .map((f) => (
                    <tr key={f.path}>
                      <td className="w-full max-w-0 truncate px-2 py-1.5 font-mono text-[12.5px] max-md:whitespace-normal max-md:[overflow-wrap:anywhere]" title={mask(f.path, 12)}>
                        <Sensitive length={12}>{f.path}</Sensitive>
                      </td>
                      <td className="w-px px-2 py-1.5 text-right whitespace-nowrap text-muted-foreground max-md:hidden">{f.modified ? fmtRelative(f.modified, lang) : ''}</td>
                      <td className={cn('w-px px-2 py-1.5 text-right whitespace-nowrap tabular-nums', !!limit && f.lines > limit && 'font-semibold text-destructive')}>{f.lines}</td>
                      <td className={cn('w-px px-2 py-1.5 text-right whitespace-nowrap tabular-nums', f.heavy ? 'font-semibold text-destructive' : 'text-muted-foreground')}>{fmtBytes(f.bytes)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </SettingsCard>

      <ReviewCard />
    </SectionStack>
  )
}

const DONE: Record<MemoryReviewAction, string[]> = { accept: ['added', 'replaced', 'removed', 'skill written', 'skill moved to the Trash'], refuse: ['rejected'], undo: ['taken back', 'skill removed'] }

/** What Harness wrote into the memory by itself, or proposes: where each line comes from, and the way back. */
function ReviewCard() {
  const t = useT()
  const lang = useLang()
  const navigate = useNavigate()
  const review = useMemoryReview()
  const act = useMemoryReviewAction()
  const items = review.data?.items || []
  const run = (it: MemoryReviewItem, action: MemoryReviewAction) =>
    act.mutate(
      { id: it.id, action },
      { onSuccess: ({ result }) => (DONE[action].includes(result) ? toast.success(t(`memory.review.did.${action}`)) : toast.error(t('memory.review.notDone'), result)) },
    )
  const busy = (it: MemoryReviewItem, action: MemoryReviewAction) => act.isPending && act.variables?.id === it.id && act.variables.action === action

  return (
    <SettingsCard title={t('memory.review.title')} description={t(`memory.review.desc.${review.data?.mode || 'auto'}`)}>
      {review.isPending ? (
        <Skeleton className="h-16" />
      ) : items.length === 0 ? (
        <EmptyState compact icon={Brain} title={t('memory.review.none')} />
      ) : (
        <ul className="divide-y" data-testid="memory-review">
          {items.map((it) => (
            <li key={it.id} className="flex flex-wrap items-start gap-x-3 gap-y-2 py-3 first:pt-0 last:pb-0">
              <div className="min-w-0 flex-1 basis-64">
                <p className="text-sm [overflow-wrap:anywhere]">
                  {it.state === 'new' && <span className="mr-2 rounded-full bg-primary/15 px-2 py-0.5 text-xs font-medium text-primary">{t('memory.review.waiting')}</span>}
                  <Sensitive length={24}>{it.level === 'skill' ? t(it.action === 'remove' ? 'memory.review.skillRemove' : 'memory.review.skill', { name: it.text }) : it.text}</Sensitive>
                </p>
                {it.old && (
                  <p className="mt-0.5 text-xs text-muted-foreground line-through [overflow-wrap:anywhere]">
                    <Sensitive length={24}>{it.old}</Sensitive>
                  </p>
                )}
                <p className="mt-1 text-xs text-muted-foreground [overflow-wrap:anywhere]">
                  {fmtRelative(it.at, lang)} · <span className="font-mono">{it.file}</span>
                  {it.why && ` · ${it.why}`}
                  {it.session && (
                    <>
                      {' · '}
                      <button type="button" className="underline underline-offset-2 hover:text-foreground" onClick={() => navigate(`/sessions?path=${encodeURIComponent(it.session!.path)}&session=${it.session!.id}`)}>
                        {t('memory.review.session')}
                      </button>
                    </>
                  )}
                </p>
              </div>
              <div className="flex shrink-0 gap-2">
                {it.can.includes('accept') && (
                  <Button size="sm" onClick={() => run(it, 'accept')} loading={busy(it, 'accept')}>
                    <Check /> {t('memory.review.accept')}
                  </Button>
                )}
                {it.can.includes('refuse') && (
                  <Button size="sm" variant="outline" onClick={() => run(it, 'refuse')} loading={busy(it, 'refuse')}>
                    <X /> {t('memory.review.refuse')}
                  </Button>
                )}
                {it.can.includes('undo') && (
                  <Button size="sm" variant="outline" onClick={() => run(it, 'undo')} loading={busy(it, 'undo')}>
                    <Undo2 /> {t('memory.review.undo')}
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </SettingsCard>
  )
}
