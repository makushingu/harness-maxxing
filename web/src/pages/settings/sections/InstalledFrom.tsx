// What `maxxing community install` recorded for an installed extension, skill or theme: where it came from, when, the
// hash of the content that was read, and whether its files changed since (GET /api/community/installed).
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { fmtDate } from '@/lib/format'
import { useLang, useT } from '@/i18n'

interface InstalledPackage {
  kind: 'extension' | 'skill' | 'theme'
  id: string
  sha256: string
  source: string
  installed_at: number
  state: 'ok' | 'modified' | 'removed'
}

export function InstalledFrom({ kind, id }: { kind: InstalledPackage['kind']; id: string }) {
  const t = useT()
  const lang = useLang()
  const { data } = useQuery({
    queryKey: ['workspace', 'community-installed'],
    queryFn: () => api.get<{ packages: InstalledPackage[] }>('/api/community/installed'),
    staleTime: 60_000,
  })
  const p = data?.packages.find((x) => x.kind === kind && x.id === id && x.state !== 'removed')
  if (!p) return null
  const date = fmtDate(p.installed_at, lang, undefined, { timeStyle: undefined })
  return (
    <p className="text-[13px] text-muted-foreground [overflow-wrap:anywhere]" data-testid="installed-from">
      {p.source ? t('pkg.from', { source: p.source, date }) : t('pkg.on', { date })}
      {' · '}
      <span className="font-mono text-xs" title={p.sha256}>sha256 {p.sha256.slice(0, 12)}</span>
      {p.state === 'modified' && <span className="text-warning"> · {t('pkg.modified')}</span>}
    </p>
  )
}
