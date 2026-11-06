// Files attached to a message of an agent or of an agent group: button, paste, drop; uploaded at once (with progress)
// into the agent's folder (<agent>/attachments/) or the group's (<group>/attachments/), sent as their paths.
import * as React from 'react'
import { Paperclip } from 'lucide-react'
import { useT } from '@/i18n'
import { Button, Tooltip, toast } from '@/components/ui'
import { uploadAttachment } from '@/lib/queries'
import { errorMessage } from '@/lib/api'
import { busyEnd, busyStart } from '@/lib/busy'
import { AttachmentChip, type Att } from '@/pages/sessions/Composer'

/** Files a message (the server's agents.ATTACH_MAX). */
export const MAX_FILES = 10

/** The files of the message being written. `path`: the agent's or the group's path; `url`: the upload route
 *  (none = /api/uploads?path=, which takes an agent's folder). */
export function useAttachments(path: string, url?: string) {
  const t = useT()
  const [atts, setAtts] = React.useState<Att[]>([])
  const ctrls = React.useRef(new Map<string, AbortController>())
  const previews = React.useRef(new Set<string>())
  React.useEffect(() => {
    const live = previews.current
    const up = ctrls.current
    return () => {
      for (const c of up.values()) c.abort()
      for (const p of live) URL.revokeObjectURL(p)
    }
  }, [])
  const count = React.useRef(0)
  count.current = atts.length
  const add = React.useCallback(
    (all: File[]) => {
      const files = all.slice(0, Math.max(0, MAX_FILES - count.current))
      if (files.length < all.length) toast.error(t('agents.attach.tooMany', { n: MAX_FILES }))
      count.current += files.length
      for (const f of files) {
        const lid = Math.random().toString(36).slice(2)
        const preview = f.type.startsWith('image/') ? URL.createObjectURL(f) : null
        if (preview) previews.current.add(preview)
        setAtts((a) => [...a, { lid, name: f.name || 'file', size: f.size, path: null, progress: 0, error: null, preview }])
        const ctrl = new AbortController()
        ctrls.current.set(lid, ctrl)
        busyStart()
        uploadAttachment(path, f, (l, tot) => setAtts((a) => a.map((x) => (x.lid === lid ? { ...x, progress: tot ? l / tot : 0 } : x))), ctrl.signal, url)
          .then((saved) => setAtts((a) => a.map((x) => (x.lid === lid ? { ...x, path: saved.path, name: saved.name, progress: 1 } : x))))
          .catch((e) => {
            if ((e as Error)?.name === 'AbortError') return
            setAtts((a) => a.map((x) => (x.lid === lid ? { ...x, error: errorMessage(e) } : x)))
            toast.error(t('sessions.uploadFailed', { name: f.name }))
          })
          .finally(() => {
            ctrls.current.delete(lid)
            busyEnd()
          })
      }
    },
    [path, url, t],
  )
  const remove = (lid: string) => {
    ctrls.current.get(lid)?.abort()
    setAtts((a) => {
      const x = a.find((y) => y.lid === lid)
      if (x?.preview) {
        URL.revokeObjectURL(x.preview)
        previews.current.delete(x.preview)
      }
      return a.filter((y) => y.lid !== lid)
    })
  }
  /** Back to a list of saved files (a message that could not be sent keeps them). */
  const restore = (kept: Att[]) => setAtts(kept)
  const uploading = atts.some((a) => !a.path && !a.error)
  const paths = atts.filter((a) => a.path && !a.error).map((a) => a.path!)
  const onPaste = (e: React.ClipboardEvent) => {
    const files = Array.from(e.clipboardData?.files || [])
    if (!files.length) return
    e.preventDefault()
    add(files)
  }
  const dropProps = {
    onDragOver: (e: React.DragEvent) => {
      if (Array.from(e.dataTransfer.types).includes('Files')) e.preventDefault()
    },
    onDrop: (e: React.DragEvent) => {
      const files = Array.from(e.dataTransfer.files || [])
      if (!files.length) return
      e.preventDefault()
      add(files)
    },
  }
  return { atts, add, remove, restore, uploading, paths, onPaste, dropProps }
}

export function AttachList({ atts, onRemove }: { atts: Att[]; onRemove: (lid: string) => void }) {
  if (!atts.length) return null
  return (
    <div data-testid="agent-attachments" className="flex max-h-[6.75rem] flex-wrap gap-1.5 overflow-y-auto overscroll-contain px-1 pt-1 pb-1.5 [scrollbar-width:thin]">
      {atts.map((a) => (
        <AttachmentChip key={a.lid} att={a} onRemove={() => onRemove(a.lid)} />
      ))}
    </div>
  )
}

export function AttachButton({ onFiles }: { onFiles: (files: File[]) => void }) {
  const t = useT()
  const input = React.useRef<HTMLInputElement>(null)
  return (
    <>
      <input
        ref={input}
        type="file"
        multiple
        hidden
        onChange={(e) => {
          onFiles(Array.from(e.target.files || []))
          e.target.value = ''
        }}
      />
      <Tooltip content={t('sessions.composer.attach')}>
        <Button variant="ghost" size="icon-sm" aria-label={t('sessions.composer.attach')} onClick={() => input.current?.click()} data-testid="agent-attach">
          <Paperclip />
        </Button>
      </Tooltip>
    </>
  )
}
