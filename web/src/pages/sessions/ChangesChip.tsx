// Under an answer whose turn changed git repositories: "app · 3 files · +12 −4" (or "2 repositories · …"). A click
// opens the Changes view of that turn in the file viewer (features/code/ChangesPane.tsx).
import { GitCompare } from 'lucide-react'
import type { ChangesEvent } from '@/lib/types'
import { Sensitive } from '@/components/ui'
import { useT } from '@/i18n'
import { openFileViewer } from '@/features/files/viewerStore'
import { changesPath } from '@/features/code/api'

export function ChangesChip({ sid, ev }: { sid: string; ev: ChangesEvent }) {
  const t = useT()
  const files = ev.repos.reduce((s, r) => s + r.files.length + (r.more || 0), 0)
  const add = ev.repos.reduce((s, r) => s + r.add, 0)
  const del = ev.repos.reduce((s, r) => s + r.del, 0)
  const only = ev.repos.length === 1 ? ev.repos[0] : null
  return (
    <button
      type="button"
      onClick={() => openFileViewer(changesPath({ sid, scope: 'turn', n: ev.n }))}
      className="inline-flex items-center gap-1 rounded-md border bg-background px-1.5 py-0.5 text-[11px] text-foreground outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:py-1.5"
      data-testid="changes-chip"
    >
      <GitCompare className="size-3 text-muted-foreground" />
      {only ? <Sensitive>{only.name}</Sensitive> : t('sessions.changes.repos', { count: ev.repos.length })}
      <span aria-hidden>·</span>
      {t('sessions.changes.files', { count: files })}
      <span className="text-success">+{add}</span>
      <span className="text-destructive">−{del}</span>
    </button>
  )
}
