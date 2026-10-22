// A quoted file (`📎 /abs/path`) shown as a small card - thumbnail for pictures and videos, else an icon - in the
// composer's quotes and in the sent message. Click: open it in the file viewer.
import { Play } from 'lucide-react'
import { Sensitive, usePresentation } from '@/components/ui'
import { iconFor } from '@/features/files/kinds'
import { cn } from '@/lib/utils'
import { useOpenPreview } from './FilePreview'
import { baseName, isImage, isVideo } from './util'
import { Thumb } from '@/features/files/Thumb'

export function QuotedFile({ path, className }: { path: string; className?: string }) {
  const open = useOpenPreview()
  const masked = usePresentation()
  const media = isImage(path) || isVideo(path)
  const Icon = iconFor('file', baseName(path))
  return (
    <button
      type="button"
      data-mx-file={path}
      onClick={() => open(path)}
      title={path}
      className={cn('flex max-w-full min-w-0 items-center gap-2 rounded-md text-left outline-none hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring', className)}
    >
      <span className="relative flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-md border bg-muted">
        {media && !masked ? <Thumb path={path} w={160} loading="lazy" className="size-full object-cover" /> : <Icon className="size-4 text-muted-foreground" />}
        {isVideo(path) && !masked && (
          <span className="absolute inset-0 flex items-center justify-center bg-black/25">
            <Play className="size-3 fill-white text-white" />
          </span>
        )}
      </span>
      <span className="min-w-0 truncate text-[13px]">
        <Sensitive length={10}>{baseName(path)}</Sensitive>
      </span>
    </button>
  )
}
