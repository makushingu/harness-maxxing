// Comments on a document of the file viewer, for the session it was opened from: select a passage, "Comment",
// type, Enter - as many as wanted, across files. They wait in a tray under the document (kept per session in this
// browser) and "Send to the session" posts them as one message, each passage quoted with its comment.
// The passages are marked with the CSS Custom Highlight API (no change to the rendered document).
import * as React from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { ChevronDown, MessageSquarePlus, Send, X } from 'lucide-react'
import { Button, toast } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { useSendMessage } from '@/lib/queries/sessions'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { useIsMobile } from '@/stores/media'
import { useFileViewer } from './viewerStore'
import { basename } from './kinds'

type Item = { id: number; path: string; quote: string; comment: string }
type State = {
  /** Session the viewer was opened from (a link in its conversation), null otherwise. */
  sid: string | null
  bySid: Record<string, Item[]>
  setSid: (sid: string | null) => void
  add: (sid: string, item: Omit<Item, 'id'>) => void
  remove: (sid: string, id: number) => void
  edit: (sid: string, id: number, comment: string) => void
  clear: (sid: string) => void
}

export const useDocComments = create<State>()(
  persist(
    (set) => ({
      sid: null,
      bySid: {},
      setSid: (sid) => set({ sid }),
      add: (sid, item) => set((s) => ({ bySid: { ...s.bySid, [sid]: [...(s.bySid[sid] || []), { ...item, id: Date.now() }] } })),
      edit: (sid, id, comment) => set((s) => ({ bySid: { ...s.bySid, [sid]: (s.bySid[sid] || []).map((i) => (i.id === id ? { ...i, comment } : i)) } })),
      remove: (sid, id) => set((s) => ({ bySid: { ...s.bySid, [sid]: (s.bySid[sid] || []).filter((i) => i.id !== id) } })),
      clear: (sid) =>
        set((s) => {
          const bySid = { ...s.bySid }
          delete bySid[sid]
          return { bySid }
        }),
    }),
    { name: 'mx-doc-comments', storage: createJSONStorage(() => localStorage), partialize: (s) => ({ bySid: s.bySid }) },
  ),
)

/** Called when a conversation opens the viewer: its comments go to that session. */
export const setCommentSession = (sid: string | null) => useDocComments.getState().setSid(sid)
// Opened from anywhere else (Files page...) after being closed: no session to send to.
useFileViewer.subscribe((s, prev) => {
  if (prev.open && !s.open) setCommentSession(null)
})

const NONE: Item[] = []
const HL = 'mx-doc-comment'

/** The message sent: per file, each passage as a blockquote followed by its comment. */
function message(items: Item[], header: (path: string) => string): string {
  const paths = [...new Set(items.map((i) => i.path))]
  return paths
    .map((p) => [header(p), ...items.filter((i) => i.path === p).map((i) => `${i.quote.split('\n').map((l) => `> ${l}`).join('\n')}\n\n${i.comment}`)].join('\n\n'))
    .join('\n\n---\n\n')
}

/** Ranges of `quote` in the text of `root` (first occurrence; whitespace may differ from the selection's). */
function findRange(root: HTMLElement, quote: string): Range | null {
  const nodes: { node: Text; start: number }[] = []
  let text = ''
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    if ((n.parentElement as HTMLElement | null)?.closest('[data-mx-doc-comments]')) continue
    nodes.push({ node: n as Text, start: text.length })
    text += n.nodeValue || ''
  }
  // search with every run of whitespace collapsed, then map back to the raw offsets
  const map: number[] = []
  let flat = ''
  for (let i = 0; i < text.length; i++) {
    if (/\s/.test(text[i])) {
      if (flat.endsWith(' ')) continue
      flat += ' '
    } else flat += text[i]
    map.push(i)
  }
  const q = quote.replace(/\s+/g, ' ').trim()
  const at = q ? flat.indexOf(q) : -1
  if (at < 0) return null
  const from = map[at]
  const to = map[at + q.length - 1] + 1
  const pos = (off: number) => {
    let k = nodes.length - 1
    while (k > 0 && nodes[k].start > off) k--
    return { node: nodes[k].node, offset: Math.min(off - nodes[k].start, nodes[k].node.length) }
  }
  const a = pos(from)
  const b = pos(to)
  const r = document.createRange()
  r.setStart(a.node, a.offset)
  r.setEnd(b.node, b.offset)
  return r
}

type Pick = { x: number; y: number; text: string }

export function DocComments({ path, scope }: { path: string; scope: React.RefObject<HTMLElement | null> }) {
  const t = useT()
  const sid = useDocComments((s) => s.sid)
  const items = useDocComments((s) => (sid ? s.bySid[sid] || NONE : NONE))
  const { add, edit, remove, clear } = useDocComments.getState()
  const send = useSendMessage()
  const [pick, setPick] = React.useState<Pick | null>(null)
  const [editing, setEditing] = React.useState(false)
  const [comment, setComment] = React.useState('')
  const [fixing, setFixing] = React.useState<{ id: number; text: string } | null>(null)
  const cancelled = React.useRef(false) // Escape: the blur that follows must not save
  const phone = useIsMobile()
  const [open, setOpen] = React.useState<boolean | null>(null) // null: unfolded on a computer, folded on a phone
  const unfolded = open ?? !phone
  const live = React.useRef({ editing, comment })
  live.current = { editing, comment }

  // A selection inside the document -> the "Comment" button under it.
  React.useEffect(() => {
    if (!sid) return
    let timer = 0
    const update = () => {
      const root = scope.current
      const sel = window.getSelection()
      if (!root || !sel || sel.isCollapsed || !sel.rangeCount) {
        if (!live.current.editing) setPick(null)
        return
      }
      const range = sel.getRangeAt(0)
      const node = range.commonAncestorContainer
      const el = node instanceof Element ? node : node.parentElement
      if (!el || !root.contains(el) || el.closest('[data-mx-doc-comments]')) return
      const text = sel.toString().trim()
      if (!text) return
      const box = root.getBoundingClientRect()
      const r = range.getBoundingClientRect()
      setPick({ x: Math.max(8, Math.min(r.left - box.left, box.width - 288)), y: r.bottom - box.top + 6, text })
      setEditing(false)
      setComment('')
    }
    const onUp = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(update, 10)
    }
    const onSel = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(update, 400) // touch: the selection handles move, no mouseup
    }
    document.addEventListener('pointerup', onUp)
    document.addEventListener('selectionchange', onSel)
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('pointerup', onUp)
      document.removeEventListener('selectionchange', onSel)
    }
  }, [sid, scope])

  React.useEffect(() => {
    setPick(null)
    setEditing(false)
  }, [path])

  // A click anywhere else closes it (an unsaved comment being typed stays open: Escape or Cancel drops it).
  React.useEffect(() => {
    if (!pick) return
    const onDown = (e: PointerEvent) => {
      if ((e.target as Element | null)?.closest?.('[data-mx-doc-pop]')) return
      if (live.current.editing && live.current.comment.trim()) return
      setPick(null)
      setEditing(false)
    }
    document.addEventListener('pointerdown', onDown, true)
    return () => document.removeEventListener('pointerdown', onDown, true)
  }, [pick])

  /** Bring a commented passage of this file into view. */
  const reveal = (i: Item) => {
    const root = scope.current
    const r = root && i.path === path ? findRange(root, i.quote) : null
    const el = r?.startContainer.parentElement
    el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }

  // Mark the commented passages of this file (and again when the document re-renders).
  React.useEffect(() => {
    const root = scope.current
    const hl = (CSS as unknown as { highlights?: Map<string, unknown> }).highlights
    const H = (window as unknown as { Highlight?: new (...r: Range[]) => unknown }).Highlight
    if (!root || !hl || !H) return
    const mine = items.filter((i) => i.path === path)
    let timer = 0
    const paint = () => {
      const ranges = mine.map((i) => findRange(root, i.quote)).filter((r): r is Range => !!r)
      if (ranges.length) hl.set(HL, new H(...ranges))
      else hl.delete(HL)
    }
    paint()
    const obs = new MutationObserver(() => {
      window.clearTimeout(timer)
      timer = window.setTimeout(paint, 150)
    })
    obs.observe(root, { childList: true, subtree: true, characterData: true })
    return () => {
      obs.disconnect()
      window.clearTimeout(timer)
      hl.delete(HL)
    }
  }, [items, path, scope])

  if (!sid) return null

  const save = () => {
    if (!pick || !comment.trim()) return
    add(sid, { path, quote: pick.text, comment: comment.trim() })
    window.getSelection()?.removeAllRanges()
    setPick(null)
    setEditing(false)
    setComment('')
  }

  const sendAll = () =>
    send.mutate(
      { id: sid, text: message(items, (p) => t('viewer.comments.header', { path: p })) },
      {
        onSuccess: () => {
          clear(sid)
          toast.success(t('viewer.comments.sent'))
        },
        onError: (e) => toast.error(errorMessage(e)),
      },
    )

  return (
    <>
      <style>{`::highlight(${HL}){background-color:color-mix(in oklch,var(--primary) 32%,transparent);color:inherit}`}</style>
      {pick && (
        <div
          data-mx-doc-comments
          data-mx-doc-pop
          className={cn('absolute z-20 rounded-lg border bg-popover shadow-lg', editing ? 'w-[min(280px,calc(100%-16px))] p-2' : 'p-0.5')}
          style={{ left: pick.x, top: pick.y }}
          onPointerUp={(e) => e.stopPropagation()}
        >
          {editing ? (
            <>
              <div className="mb-1.5 truncate border-l-2 border-primary pl-2 text-xs text-muted-foreground">« {pick.text} »</div>
              <textarea
                autoFocus
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault()
                    save()
                  } else if (e.key === 'Escape') {
                    e.stopPropagation()
                    setPick(null)
                  }
                }}
                placeholder={t('viewer.comments.placeholder')}
                rows={2}
                className="block w-full resize-none rounded-md border bg-background px-2 py-1.5 text-[13px] outline-none focus:border-primary"
              />
              <div className="mt-1.5 flex justify-end gap-1">
                <Button variant="ghost" size="sm" onClick={() => setPick(null)}>
                  {t('common.cancel')}
                </Button>
                <Button size="sm" onClick={save} disabled={!comment.trim()}>
                  {t('viewer.comments.add')}
                </Button>
              </div>
            </>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
              <MessageSquarePlus /> {t('viewer.comments.comment')}
            </Button>
          )}
        </div>
      )}
      {items.length > 0 && (
        // A phone: folded to one line (the document keeps the room), hidden while a comment is typed (the keyboard).
        <div data-mx-doc-comments className={cn('m-3 mt-0 shrink-0 rounded-xl border border-primary/40 bg-card p-2 pl-3 max-md:m-2 max-md:mt-0', editing && pick && 'max-md:hidden')}>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => setOpen(!unfolded)} aria-expanded={unfolded} className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-[13.5px] font-semibold">
              <ChevronDown className={cn('size-4 shrink-0 text-muted-foreground transition-transform', !unfolded && '-rotate-90')} />
              <span className="truncate">{t('viewer.comments.pending', { count: items.length })}</span>
            </button>
            {unfolded && (
              <Button variant="ghost" size="sm" onClick={() => clear(sid)}>
                {t('viewer.comments.clear')}
              </Button>
            )}
            {!unfolded && (
              <Button size="sm" onClick={sendAll} loading={send.isPending} aria-label={t('viewer.comments.send', { count: items.length })}>
                <Send /> {items.length}
              </Button>
            )}
          </div>
          {unfolded && (
          <>
          <ol className="mt-1 max-h-48 overflow-y-auto max-md:max-h-[30vh]">
            {items.map((i, n) => (
              <li key={i.id} className="flex items-start gap-2 border-t py-1.5 text-[13px]">
                <span className="mt-0.5 flex size-[18px] shrink-0 items-center justify-center rounded-full bg-primary text-[10.5px] font-bold text-primary-foreground">{n + 1}</span>
                <div className="min-w-0 flex-1">
                  <button type="button" onClick={() => reveal(i)} title={t('viewer.comments.reveal')} className="block w-full truncate text-left text-muted-foreground hover:text-foreground">
                    {i.path !== path && <span className="mr-1 font-medium">{basename(i.path)} ·</span>}« {i.quote} »
                  </button>
                  {fixing?.id === i.id ? (
                    <textarea
                      autoFocus
                      value={fixing.text}
                      rows={2}
                      onChange={(e) => setFixing({ id: i.id, text: e.target.value })}
                      onBlur={() => {
                        if (!cancelled.current && fixing.text.trim()) edit(sid, i.id, fixing.text.trim())
                        cancelled.current = false
                        setFixing(null)
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                          e.preventDefault()
                          e.currentTarget.blur()
                        } else if (e.key === 'Escape') {
                          e.stopPropagation()
                          cancelled.current = true
                          e.currentTarget.blur()
                        }
                      }}
                      className="block w-full resize-none rounded-md border bg-background px-2 py-1 text-[13px] outline-none focus:border-primary"
                    />
                  ) : (
                    <button type="button" onClick={() => setFixing({ id: i.id, text: i.comment })} title={t('viewer.comments.edit')} className="block w-full cursor-text whitespace-pre-wrap text-left">
                      {i.comment}
                    </button>
                  )}
                </div>
                <Button variant="ghost" size="icon-sm" aria-label={t('viewer.comments.remove')} onClick={() => remove(sid, i.id)}>
                  <X />
                </Button>
              </li>
            ))}
          </ol>
          <Button className="mt-2 max-md:w-full" onClick={sendAll} loading={send.isPending}>
            <Send /> {t('viewer.comments.send', { count: items.length })}
          </Button>
          </>
          )}
        </div>
      )}
    </>
  )
}
