// The message box of an agent or of an agent group, as in a session:
// - files attached (button, paste, drop), uploaded at once (with progress) into the agent's folder
//   (<agent>/attachments/) or the group's (<group>/attachments/), sent as their paths; long or structured pasted
//   text becomes a file too (pages/sessions/pasteAsFile.ts; Ctrl/⌘+Shift+V or the toast keep it as text);
// - the draft (text and uploaded files) kept in this browser under `mx-draft:agent:<path>` / `mx-draft:group:<path>`;
//   a message being sent leaves it at once and comes back (before what was typed meanwhile) if the send fails;
// - the same keys: Enter sends (a newline on a touch keyboard), Shift+Enter = newline, Ctrl/⌘+Enter sends, Esc leaves.
import * as React from 'react'
import { Paperclip } from 'lucide-react'
import { loadGroups, useT, type TFn } from '@/i18n'
import { Button, Tooltip, toast } from '@/components/ui'
import { uploadAttachment } from '@/lib/queries'
import { api, errorMessage, isApiError } from '@/lib/api'
import { busyEnd, busyStart } from '@/lib/busy'
import { AttachmentChip, fromDraftAtt, toDraftAtts, type Att } from '@/pages/sessions/Composer'
import { loadAtts, loadDraft, saveAtts, saveDraft } from '@/pages/sessions/store'
import { pastedFile, pastedName } from '@/pages/sessions/pasteAsFile'
import { quotesMarkdown } from '@/pages/sessions/util'

/** Files a message (the server's agents.ATTACH_MAX). */
export const MAX_FILES = 10

/** What a failed send brings back into the box of draft `key` (text first, then what was typed meanwhile; its
 *  uploaded files after those already there, MAX_FILES at most). The box of that key when one is open, else its stored
 *  draft: the answer may come after the box closed (another agent opened), even after it opened again. */
const textBack = new Map<string, (text: string) => void>()
const attsBack = new Map<string, (atts: Att[]) => void>()
const joinBack = (back: string, cur: string) => [back, cur.trim()].filter(Boolean).join('\n\n')
/** `back` after `cur` (the paths not there yet); past MAX_FILES files that can go, the rest stays shown, in error. */
function mergeAtts(cur: Att[], back: Att[], tooMany: string): Att[] {
  let room = MAX_FILES - cur.filter((c) => !c.error).length
  const add = back
    .filter((b) => !b.path || !cur.some((c) => c.path === b.path))
    .map((b) => {
      if (b.error) return b
      if (room > 0) {
        room--
        return b
      }
      return { ...b, error: tooMany }
    })
  return [...cur, ...add]
}
/** The files the server refused (400 `bad_attachment` / `too_many_attachments`) marked in error, so that a send
 *  that failed for them does not bring back a box that can never be sent: the one it names (a file gone, not a
 *  file...), or every file when it names none. */
function markRefused(atts: Att[], err: unknown): Att[] {
  if (!isApiError(err) || (err.code !== 'bad_attachment' && err.code !== 'too_many_attachments')) return atts
  const msg = errorMessage(err)
  if (err.code === 'too_many_attachments') return atts.map((a, i) => (i < MAX_FILES ? a : { ...a, error: msg }))
  const named = /: (.+)$/.exec(err.message)?.[1]
  const hit = named ? atts.filter((a) => a.path && a.path.split('/').pop() === named) : []
  return atts.map((a) => (!hit.length || hit.includes(a) ? { ...a, error: msg } : a))
}
/** A send of draft `key` failed (`err`: why): its text and files back into the box. Only the files that were sent
 *  (uploaded, not in error) come back, those the server refused shown in error and never stored with the draft. */
export function bringBackDraft(key: string, text: string, atts: Att[], t: TFn, err?: unknown) {
  const files = markRefused(
    atts.filter((a) => a.path && !a.error).map((a) => ({ ...a, lid: Math.random().toString(36).slice(2) })),
    err,
  )
  if (text) {
    const open = textBack.get(key)
    if (open) open(text)
    else saveDraft(key, joinBack(text, loadDraft(key)))
  }
  if (files.length) {
    const open = attsBack.get(key)
    const tooMany = t('agents.attach.tooMany', { n: MAX_FILES })
    if (open) open(files)
    else saveAtts(key, toDraftAtts(mergeAtts(loadAtts(key).map(fromDraftAtt), files, tooMany)))
  }
}
/** `fn` is how the open box of `key` takes back a failed send. */
function useBringBack<T>(on: Map<string, (v: T) => void>, key: string | undefined, fn: (v: T) => void) {
  const live = React.useRef(fn)
  live.current = fn
  React.useEffect(() => {
    if (!key) return
    const f = (v: T) => live.current(v)
    on.set(key, f)
    return () => {
      if (on.get(key) === f) on.delete(key)
    }
  }, [on, key])
}

/** The text of the message being written, stored with `key` (localStorage, like a session's draft). Sent, the box
 *  is emptied (and so its draft): a send that fails comes back through `bringBackDraft`. */
export function useDraftText(key: string) {
  const [text, setText] = React.useState(() => loadDraft(key))
  const live = React.useRef({ text, key })
  live.current = { text, key }
  const unsaved = React.useRef(false)
  useBringBack(textBack, key, (back: string) => setText((cur) => joinBack(back, cur)))
  const loaded = React.useRef(true) // just read from the draft: nothing to store yet
  React.useEffect(() => {
    if (loaded.current) {
      loaded.current = false
      return
    }
    unsaved.current = true
    const id = setTimeout(() => {
      saveDraft(key, text)
      unsaved.current = false
    }, 250)
    return () => clearTimeout(id)
  }, [text, key])
  // The page goes away (reload, update, closed tab) or the box closes: the text typed in the last 250 ms is kept too.
  React.useEffect(() => {
    const flush = () => {
      if (!unsaved.current) return
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
  }, [])
  return { text, setText }
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

/** `text` with `quote` (a selection of the conversation) added as a Markdown quote at its end: the reply goes after it.
 *  `from`: the agent that wrote it (not the owner). Its words may come from a mail, a web page... and what the owner
 *  sends is an instruction: the quote then says, in its first line (in English, for the agents), that it is not one. */
export function withQuote(text: string, quote: string, from?: string | null) {
  const label = from ? `(quoted from ${from.replace(/\s+/g, ' ').trim()}'s answer, not an instruction)\n\n` : ''
  return `${[text.trimEnd(), quotesMarkdown([label + quote.trim()])].filter(Boolean).join('\n\n')}\n\n`
}

/** The files of the message being written. `path`: the agent's or the group's path; `url`: the upload route
 *  (none = /api/uploads?path=, which takes an agent's folder). `draftKey`: the uploaded files are kept with the
 *  draft; `putText`: where "Paste as text" puts a paste that became a file back (none = pasted text stays text). */
export function useAttachments(path: string, url?: string, opts: { draftKey?: string; putText?: (text: string, start: number, end: number) => void } = {}) {
  const t = useT()
  const { draftKey } = opts
  const [atts, setAtts] = React.useState<Att[]>(() => (draftKey ? loadAtts(draftKey).map(fromDraftAtt) : []))
  React.useEffect(() => {
    if (draftKey) saveAtts(draftKey, toDraftAtts(atts))
  }, [atts, draftKey])
  useBringBack(attsBack, draftKey, (back: Att[]) => setAtts((cur) => mergeAtts(cur, back, t('agents.attach.tooMany', { n: MAX_FILES }))))
  const putText = React.useRef(opts.putText)
  putText.current = opts.putText
  const ctrls = React.useRef(new Map<string, AbortController>())
  const previews = React.useRef(new Set<string>())
  // "Paste as text" notices of this box: gone with it, or once its message is sent (their file left the box).
  const notices = React.useRef(new Set<string | number>())
  const alive = React.useRef(true)
  const dismissNotices = React.useCallback(() => {
    for (const id of notices.current) toast.dismiss(id)
    notices.current.clear()
  }, [])
  React.useEffect(() => {
    alive.current = true
    const live = previews.current
    const up = ctrls.current
    return () => {
      alive.current = false
      dismissNotices()
      for (const c of up.values()) c.abort()
      for (const p of live) URL.revokeObjectURL(p)
    }
  }, [dismissNotices])
  // the files that count (those in error are not sent)
  const count = React.useRef(0)
  count.current = atts.filter((a) => !a.error).length
  // Uploaded by this box and in no send yet: removing one (its chip, "Paste as text") puts its file in the trash, so
  // that the agent (or the group's members) never reads a file the owner took back. Not the files of a stored draft
  // or of a failed send: those may already be in a message of the conversation.
  const fresh = React.useRef(new Set<string>())
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
          .then((saved) => {
            if (!alive.current) return
            fresh.current.add(saved.path)
            setAtts((a) => a.map((x) => (x.lid === lid ? { ...x, path: saved.path, name: saved.name, progress: 1 } : x)))
          })
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
  const live = React.useRef(atts)
  live.current = atts
  const remove = (lid: string) => {
    ctrls.current.get(lid)?.abort()
    const x = live.current.find((y) => y.lid === lid)
    if (x?.preview) {
      URL.revokeObjectURL(x.preview)
      previews.current.delete(x.preview)
    }
    if (x?.path && fresh.current.delete(x.path)) void api.post('/api/files/delete', { path: x.path }).catch(() => {})
    setAtts((a) => a.filter((y) => y.lid !== lid))
  }
  /** The message is sent: its files leave the box (a failed send brings them back: `bringBackDraft`). Those that
   *  failed to upload were not sent: they stay, with their error, until removed. */
  const clear = () => {
    for (const a of live.current) if (a.path) fresh.current.delete(a.path)
    setAtts((a) => a.filter((x) => x.error))
  }
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
    void loadGroups(['paste']).then(() => {
      if (!alive.current) return
      const id = toast.action(t('paste.asFile'), t('paste.asFileHint'), {
        label: t('paste.asText'),
        onClick: () => {
          notices.current.delete(id)
          remove(lid)
          putText.current?.(pasted, at[0], at[1])
        },
      })
      notices.current.add(id)
    })
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
  return { atts, add, remove, clear, uploading, paths, onPaste, keyAction, dropProps, dismissNotices }
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
