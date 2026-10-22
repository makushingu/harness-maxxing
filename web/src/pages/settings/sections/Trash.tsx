import { File, Folder, FolderKanban, History, MessageSquare, RotateCcw, Trash2 } from 'lucide-react'
import { useTrash, useTrashDelete, useTrashEmpty, useTrashRestore } from '@/lib/queries'
import { useLang, useT } from '@/i18n'
import type { TrashItem, TrashKind } from '@/lib/types'
import { fmtBytes, fmtRelative } from '@/lib/format'
import { Badge, Button, EmptyState, Sensitive, Skeleton, Tooltip, confirm, toast, useMask } from '@/components/ui'
import { SettingsCard, SectionStack } from './ui'

const ICON: Record<TrashKind, typeof File> = {
  file: File, folder: Folder, topic: FolderKanban, project: FolderKanban, session: MessageSquare, previous_versions: History,
}

function Row({ it }: { it: TrashItem }) {
  const t = useT()
  const lang = useLang()
  const mask = useMask()
  const restore = useTrashRestore()
  const del = useTrashDelete()
  const Icon = ICON[it.kind] || File
  return (
    <li className="flex items-center gap-3 px-4 py-3">
      <Icon className="size-4 shrink-0 text-muted-foreground" />
      <div className="grid min-w-0 flex-1 gap-0.5">
        <span className="flex min-w-0 items-center gap-2 text-sm font-medium">
          <span className="truncate">
            <Sensitive>{it.name}</Sensitive>
          </span>
          <Badge variant="muted" className="shrink-0">{t(`trash.kind.${it.kind}`)}</Badge>
        </span>
        <span className="truncate text-xs text-muted-foreground">
          {fmtRelative(it.at, lang)} · {fmtBytes(it.size)}
          {it.kind !== 'session' && it.sessions > 0 && ` · ${t('trash.sessions', { count: it.sessions })}`}
          {it.original && (
            <>
              {' · '}
              <Sensitive>{it.original || t('trash.root')}</Sensitive>
            </>
          )}
        </span>
      </div>
      {it.restorable && (
        <Button
          variant="outline"
          size="sm"
          loading={restore.isPending}
          onClick={async () => {
            try {
              const r = await restore.mutateAsync(it.id)
              // The row is removed by invalidation; this notification must survive its unmount.
              toast.success(t('trash.restored', { path: mask(r.restored_to || t('trash.root'), 10) }))
            } catch { /* useMut already reports the error. */ }
          }}
        >
          <RotateCcw /> {t('trash.restore')}
        </Button>
      )}
      <Tooltip content={t('trash.deleteForever')}>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={t('trash.deleteForever')}
          loading={del.isPending}
          onClick={async () => {
            if (await confirm({ title: t('trash.deleteConfirm', { name: mask(it.name, 8) }), description: t('trash.deleteDesc'), destructive: true, confirmText: t('trash.deleteForever') }))
              del.mutate(it.id)
          }}
        >
          <Trash2 />
        </Button>
      </Tooltip>
    </li>
  )
}

export function TrashSection() {
  const t = useT()
  const { data, isLoading, isError, refetch } = useTrash()
  const empty = useTrashEmpty()
  const items = data?.items || []
  return (
    <SectionStack>
      <SettingsCard
        title={
          <span className="flex items-center gap-2">
            {t('trash.title')} {!isError && <Badge variant="muted">{items.length}</Badge>}
          </span>
        }
        description={t('trash.desc', { days: data?.keep_days ?? 30 })}
        actions={
          !isError && items.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              loading={empty.isPending}
              onClick={async () => {
                if (await confirm({ title: t('trash.emptyConfirm'), description: t('trash.deleteDesc'), destructive: true, confirmText: t('trash.empty') }))
                  empty.mutate(undefined, { onSuccess: () => toast.success(t('trash.emptied')) })
              }}
            >
              <Trash2 /> {t('trash.empty')}
            </Button>
          )
        }
        className="[&>div:last-child]:p-0 [&>div:last-child]:pt-4"
      >
        {isLoading ? (
          <div className="grid gap-2 p-4">
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
          </div>
        ) : isError ? (
          <EmptyState compact tone="error" icon={Trash2} title={t('trash.loadFailed')} description={t('trash.loadFailedDesc')} action={<Button variant="outline" size="sm" onClick={() => void refetch()}>{t('common.retry')}</Button>} />
        ) : !items.length ? (
          <EmptyState compact icon={Trash2} title={t('trash.none')} description={t('trash.noneDesc')} />
        ) : (
          <ul className="divide-y border-t">
            {items.map((it) => (
              <Row key={it.id} it={it} />
            ))}
          </ul>
        )}
      </SettingsCard>
    </SectionStack>
  )
}
