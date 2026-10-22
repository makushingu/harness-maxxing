import { useNavigate } from 'react-router'
import { Brain, Sparkles } from 'lucide-react'
import { useCompactMemory, useMemory, useSaveSettings, useSettings } from '@/lib/queries'
import { fmtBytes } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Button, EmptyState, Select, Sensitive, Skeleton, toast } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { SettingsCard, SectionStack } from './ui'

const LIMITS = [0, 100, 150, 200, 300, 500, 1000]

export function MemorySection() {
  const t = useT()
  const navigate = useNavigate()
  const { data: settings } = useSettings()
  const save = useSaveSettings()
  const mem = useMemory()
  const compact = useCompactMemory()
  const limit = settings?.memory_max_lines ?? mem.data?.max_lines ?? 200
  const files = mem.data?.files || []
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
            <Button variant="outline" size="sm" onClick={() => navigate('/crons')}>
              {t('memory.openCrons')}
            </Button>
          </SettingRow>
        </div>
      </SettingsCard>

      <SettingsCard
        title={t('memory.files')}
        description={limit ? (over.length ? t('memory.overCount', { count: over.length, limit }) : t('memory.allUnder', { limit })) : t('memory.filesDesc')}
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
                  <th className="px-2 py-1.5 text-right font-medium">{t('memory.lineCount')}</th>
                  <th className="px-2 py-1.5 text-right font-medium">{t('memory.size')}</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {[...files]
                  .sort((a, b) => Number(b.over) - Number(a.over) || b.lines - a.lines)
                  .map((f) => (
                    <tr key={f.path}>
                      <td className="max-w-0 truncate px-2 py-1.5 font-mono text-[12.5px]">
                        <Sensitive length={12}>{f.path}</Sensitive>
                      </td>
                      <td className={cn('px-2 py-1.5 text-right tabular-nums', f.over && 'font-semibold text-destructive')}>{f.lines}</td>
                      <td className="px-2 py-1.5 text-right text-muted-foreground tabular-nums">{fmtBytes(f.bytes)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </SettingsCard>
    </SectionStack>
  )
}
