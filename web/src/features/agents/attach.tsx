// The message box of an agent or of an agent group, as in a session:
// - files attached (button, paste, drop), uploaded at once (with progress) into the agent's folder
//   (<agent>/attachments/) or the group's (<group>/attachments/), sent as their paths; long or structured pasted
//   text becomes a file too (pages/sessions/pasteAsFile.ts; Ctrl/⌘+Shift+V or the toast keep it as text);
// - the draft (text and uploaded files) kept in this browser under `mx-draft:agent:<path>` / `mx-draft:group:<path>`
//   until the message is sent;
// - the same keys: Enter sends (a newline on a touch keyboard), Shift+Enter = newline, Ctrl/⌘+Enter sends, Esc leaves.
import * as React from 'react'
import { Paperclip } from 'lucide-react'
import { loadGroups, useT } from '@/i18n'
import { Button, Tooltip, toast } from '@/components/ui'
import { uploadAttachment } from '@/lib/queries'
import { errorMessage } from '@/lib/api'
import { busyEnd, busyStart } from '@/lib/busy'
import { AttachmentChip, fromDraftAtt, toDraftAtts, type Att } from '@/pages/sessions/Composer'
import { loadAtts, loadDraft, saveAtts, saveDraft } from '@/pages/sessions/store'
import { pastedFile, pastedName } from '@/pages/sessions/pasteAsFile'
import { quotesMarkdown } from '@/pages/sessions/util'

/** Files a message (the server's agents.ATTACH_MAX). */
export const MAX_FILES = 10

/** Draft key of an agent's box (`agent:<path>`) or a group's (`group:<path>`): never a session's (its id or `new:<path>`). */
export const agentDraftKey = (kind: 'agent' | 'group', path: string) => `${kind}:${path}`

/** Keeps a draft stored until the message is sent: `hold` when it leaves, `release(sent)` when the server answered
 *  (sent: what is in the box now is stored; refused: the box gets the message back, stored with it). */
function useHeld(store: () => void) {
  const held = React.useRef(false)
  const save = React.useRef(store)
  save.current = store
  const hold = React.useCallback(() => {
    held.current = true
  }, [])
  const release = React.useCallback((sent: boolean) => {
    held.current = false
    if (sent) save.current()
  }, [])
  return { held, hold, release }
}

/** The text of the message being written, stored with `key` (localStorage, like a session's draft). */
export function useDraftText(key: string) {
  const [text, setText] = React.useState(() => loadDraft(key))
  const live = React.useRef({ text, key })
  live.current = { text, key }
  const unsaved = React.useRef(false)
  const { held, hold, release } = useHeld(() => {
    saveDraft(live.current.key, live.current.text)
    unsaved.current = false
  })
  const loaded = React.useRef(true) // just read from the draft: nothing to store yet
  React.useEffect(() => {
    if (loaded.current) {
      loaded.current = false
      return
    }
    if (held.current) return
    unsaved.current = true
    const id = setTimeout(() => {
      saveDraft(key, text)
      unsaved.current = false
    }, 250)
    return () => clearTimeout(id)
  }, [text, key, held])
  // The page goes away (reload, update, closed tab) or the box closes: the text typed in the last 250 ms is kept too.
  React.useEffect(() => {
    const flush = () => {
      if (!unsaved.current || held.current) return
      saveDraft(live.current.key, live.current.text)
      unsaved.current = false
    }
    const onHidden = () => document.visibilityState === 'hidden' && flush()
    window.addEventListener('pagehide', flush)
    document.addEventListener('visibilitychange', onHidden)
    return () => {
      flush()
      window.removeEventListener('pagehide', flush)
      document.removeEventListener('visibilitychange', onHidden)
    }
  }, [held])
  return { text, setText, hold, release }
}

/** `heard` (a dictation) put at the caret of `el` in `text`, with a space on each side when needed. */
export function insertAtCaret(el: HTMLTextAreaElement | null, text: string, heard: string): { text: string; caret: number } {
  const start = el ? el.selectionStart : text.length
  const end = el ? el.selectionEnd : text.length
  const before = text.slice(0, start)
  const after = text.slice(end)
  const ins = (before && !/\s$/.test(before) ? ' ' : '') + heard + (after && !/^\s/.test(after) ? ' ' : '')
  return { text: before + ins + after, caret: before.length + ins.length }
}

/** `text` with `quote` (a selection of the conversation) added as a Markdown quote at its end: the reply goes after it. */
export const withQuote = (text: string, quote: string) => `${[text.trimEnd(), quotesMarkdown([quote.trim()])].filter(Boolean).join('\n\n')}\n\n`

/** The files of the message being written. `path`: the agent's or the group's path; `url`: the upload route
 *  (none = /api/uploads?path=, which takes an agent's folder). `draftKey`: the uploaded files are kept with the
 *  draft; `putText`: where "Paste as text" puts a paste that became a file back (none = pasted text stays text). */
export function useAttachments(path: string, url?: string, opts: { draftKey?: string; putText?: (text: string, start: number, end: number) => void } = {}) {
  const t = useT()
  const { draftKey } = opts
  const [atts, setAtts] = React.useState<Att[]>(() => (draftKey ? loadAtts(draftKey).map(fromDraftAtt) : []))
  const kept = React.useRef(atts)
  kept.current = atts
  const { held, hold, release } = useHeld(() => draftKey && saveAtts(draftKey, toDraftAtts(kept.current)))
  React.useEffect(() => {
    if (draftKey && !held.current) saveAtts(draftKey, toDraftAtts(atts))
  }, [atts, draftKey, held])
  const putText = React.useRef(opts.putText)
  putText.current = opts.putText
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
  /** Uploads `all` (up to MAX_FILES in the message): the local ids of those taken. */
  const add = React.useCallback(
    (all: File[]): string[] => {
      const files = all.slice(0, Math.max(0, MAX_FILES - count.current))
      if (files.length < all.length) toast.error(t('agents.attach.tooMany', { n: MAX_FILES }))
      count.current += files.length
      const lids: string[] = []
      for (const f of files) {
        const lid = Math.random().toString(36).slice(2)
        lids.push(lid)
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
      return lids
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
  // Ctrl+Shift+V / ⌘⇧V just before the paste: kept as text whatever it is.
  const plainPaste = React.useRef(0)
  const onPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(e.clipboardData?.files || [])
    if (files.length) {
      e.preventDefault()
      add(files)
      return
    }
    const pasted = e.clipboardData?.getData('text/plain') || ''
    const back = putText.current
    const as = !back || count.current >= MAX_FILES || Date.now() - plainPaste.current < 1000 ? null : pastedFile(pasted)
    if (!as) return
    e.preventDefault()
    const el = e.currentTarget
    const at = [el.selectionStart, el.selectionEnd]
    const [lid] = add([new File([pasted], pastedName(as.ext), { type: as.type })])
    void loadGroups(['paste']).then(() =>
      toast.action(t('paste.asFile'), t('paste.asFileHint'), {
        label: t('paste.asText'),
        onClick: () => {
          remove(lid)
          putText.current?.(pasted, at[0], at[1])
        },
      }),
    )
  }
  /** The keys of the box, as in a session: 'send' (Enter, Ctrl/⌘+Enter; on a touch keyboard Enter is a newline and
   *  the button sends), 'escape', or null (default handling). Notes Ctrl/⌘+Shift+V for `onPaste`. */
  const keyAction = (e: React.KeyboardEvent<HTMLTextAreaElement>): 'send' | 'escape' | null => {
    if (e.nativeEvent.isComposing) return null
    if ((e.key === 'v' || e.key === 'V') && e.shiftKey && (e.metaKey || e.ctrlKey)) plainPaste.current = Date.now()
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey || !e.shiftKey)) {
      if (!e.metaKey && !e.ctrlKey && window.matchMedia('(pointer: coarse)').matches) return null
      e.preventDefault()
      return 'send'
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      return 'escape'
    }
    return null
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
  return { atts, add, remove, restore, uploading, paths, onPaste, keyAction, dropProps, hold, release }
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
