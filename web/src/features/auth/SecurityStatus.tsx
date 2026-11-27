import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Skeleton } from '@/components/ui'
import { cn } from '@/lib/utils'

type Check = { id: string; level: 'ok' | 'info' | 'warn' | 'fail'; title: string; detail: string; fix: string }

const DOT: Record<Check['level'], string> = { ok: 'bg-success', info: 'bg-muted-foreground', warn: 'bg-warning', fail: 'bg-destructive' }

/** What protects this installation, one line each, with what to do for the ones that are not on. */
export function SecurityStatus() {
  const { data } = useQuery({ queryKey: ['system', 'security'], queryFn: () => api.get<{ checks: Check[] }>('/api/system/security') })
  if (!data) return <Skeleton className="h-24 w-full" />
  return (
    <ul className="divide-y rounded-lg border">
      {data.checks.map((c) => (
        <li key={c.id} className="flex items-start gap-3 px-4 py-3">
          <span className={cn('mt-1.5 size-2 shrink-0 rounded-full', DOT[c.level])} />
          <div className="grid min-w-0 gap-0.5">
            <span className="text-sm font-medium [overflow-wrap:anywhere]">{c.title}</span>
            {c.detail && <span className="text-[13px] text-muted-foreground [overflow-wrap:anywhere]">{c.detail}</span>}
            {c.fix && c.level !== 'ok' && <code className="text-[13px] text-muted-foreground [overflow-wrap:anywhere]">{c.fix}</code>}
          </div>
        </li>
      ))}
    </ul>
  )
}
