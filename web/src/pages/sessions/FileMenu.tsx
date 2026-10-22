// Right click (long press on Android) on a file of a conversation - a picture, a video, an attachment, a path in
// an answer: Open, Download, Quote, Copy path. Quote adds ONE line to the composer's quotes (`📎 /abs/path`):
// Claude gets the path and reads the file only if it needs to, the picture itself never fills the context.
import * as React from 'react'
import { createPortal } from 'react-dom'
import { Copy, Download, Eye, Quote } from 'lucide-react'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger, toast } from '@/components/ui'
import { downloadFile } from '@/features/files/download'
import { copyText } from '@/lib/utils'
import { useT } from '@/i18n'
import { useOpenPreview } from './FilePreview'
import { FILE_HREF } from './util'

type At = { x: number; y: number; path: string }

/** The file under an element of the thread (buttons carry data-mx-file, answer links #mx-file=), absolute paths only. */
function fileAt(el: Element | null): string | null {
  const hit = el?.closest<HTMLElement>(`[data-mx-file], a[href^="${FILE_HREF}"]`)
  if (!hit) return null
  const p = hit.dataset.mxFile ?? decodeURIComponent((hit.getAttribute('href') || '').slice(FILE_HREF.length))
  return p.startsWith('/') ? p : null
}

export function FileMenu({ scope, onQuote }: { scope: React.RefObject<HTMLElement | null>; onQuote: (path: string) => void }) {
  const t = useT()
  const open = useOpenPreview()
  const [at, setAt] = React.useState<At | null>(null)

  React.useEffect(() => {
    const el = scope.current
    if (!el) return
    // Capture: a file inside a message wins over the message's own menu (copy / delete).
    const onMenu = (e: MouseEvent) => {
      const path = fileAt(e.target as Element)
      if (!path) return
      e.preventDefault()
      e.stopPropagation()
      setAt({ x: e.clientX, y: e.clientY, path })
    }
    el.addEventListener('contextmenu', onMenu, true)
    return () => el.removeEventListener('contextmenu', onMenu, true)
  }, [scope])

  if (!at) return null
  const { path } = at
  return createPortal(
    <DropdownMenu open onOpenChange={(o) => !o && setAt(null)}>
      <DropdownMenuTrigger asChild>
        <span aria-hidden tabIndex={-1} className="pointer-events-none fixed size-0" style={{ left: at.x, top: at.y }} />
      </DropdownMenuTrigger>
      {/* The trigger is an invisible point: closing never sends the focus there (Quote focuses the composer). */}
      <DropdownMenuContent align="start" sideOffset={2} className="min-w-48" data-testid="file-menu" onCloseAutoFocus={(e) => e.preventDefault()}>
        <DropdownMenuItem onSelect={() => open(path)}>
          <Eye /> {t('files.open')}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => void downloadFile(path)}>
          <Download /> {t('files.download')}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setTimeout(() => onQuote(path), 0)} data-testid="file-menu-quote">
          <Quote /> {t('sessions.quote.action')}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void copyText(path).then((ok) => ok && toast.success(t('files.pathCopied')))}>
          <Copy /> {t('files.copyPath')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>,
    document.body,
  )
}
