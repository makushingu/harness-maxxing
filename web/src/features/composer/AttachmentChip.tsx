// A file of the message being written: its thumbnail or icon, name, size or upload progress, a remove button.
// Once uploaded, a click opens it in the file viewer (← / → between the files of the message: `list`).
import { FileText, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Sensitive } from '@/components/ui'
import { fmtBytes } from '@/lib/format'
import { isImage } from '@/pages/sessions/util'
import { openFileViewer } from '@/features/files/viewerStore'

/** `progress`: 0..1 while uploading, below 0 when the upload gives no progress. */
export type Att = { lid: string; name: string; size: number; path: string | null; progress: number; error: string | null; preview: string | null }

export function AttachmentChip({ att, onRemove, list }: { att: Att; onRemove: () => void; list?: string[] }) {
  const t = useT()
  const done = !!att.path
  return (
    <div className={cn('group relative flex h-12 max-w-52 items-center gap-2 overflow-hidden rounded-lg border bg-background pr-7 pl-1 pointer-coarse:pr-10', att.error && 'border-destructive/50', done && !att.error && 'hover:bg-fill-1')}>
      {done && !att.error && (
        // the whole chip under the remove button: opens the uploaded file in the viewer
        <button
          type="button"
          onClick={() => openFileViewer(att.path!, list)}
          aria-label={att.name}
          data-testid="attachment-open"
          className="absolute inset-0 rounded-lg focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        />
      )}
      {att.preview && isImage(att.name) ? (
        <img src={att.preview} alt="" className="pointer-events-none size-10 shrink-0 rounded-md object-cover" />
      ) : (
        <span className="pointer-events-none flex size-10 shrink-0 items-center justify-center rounded-md bg-muted">
          <FileText className="size-4 text-muted-foreground" />
        </span>
      )}
      <span className="pointer-events-none grid min-w-0 text-xs leading-tight">
        <span className="truncate font-medium">
          <Sensitive length={8}>{att.name}</Sensitive>
        </span>
        <span className={cn('truncate text-[11px]', att.error ? 'text-destructive' : 'text-muted-foreground')}>
          {att.error ? t('common.failed') : done ? (att.size ? fmtBytes(att.size) : '') : att.progress < 0 ? '…' : `${Math.round(att.progress * 100)} %`}
        </span>
      </span>
      {!done && !att.error && att.progress >= 0 && <span className="absolute bottom-0 left-0 h-0.5 bg-primary transition-[width]" style={{ width: `${Math.round(att.progress * 100)}%` }} />}
      <button
        type="button"
        onClick={onRemove}
        aria-label={t('common.remove')}
        className="absolute top-1 right-1 z-10 flex size-5 items-center justify-center rounded-md text-muted-foreground pointer-coarse:top-0 pointer-coarse:right-0 pointer-coarse:h-full pointer-coarse:w-10 pointer-coarse:rounded-none before:absolute before:-inset-2.5 before:content-[''] hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <X className="size-3.5" />
      </button>
    </div>
  )
}
