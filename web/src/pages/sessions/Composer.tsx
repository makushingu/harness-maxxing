// Message composer: autosize textarea, drafts, attachments (button / drop / paste), queue stack, quotes,
// send / stop. Enter sends, Shift+Enter = newline, Ctrl/⌘+Enter sends, Esc blurs.
import * as React from 'react'
import { ArrowUp, Clock, CornerDownRight, FileText, MessageCircleQuestion, Paperclip, Pencil, Quote, Square, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { loadGroups, useT } from '@/i18n'
import { Button, Sensitive, Spinner, Textarea, Tooltip, toast } from '@/components/ui'
import { uploadAttachment } from '@/lib/queries'
import { errorMessage } from '@/lib/api'
import { DRAFT_EVENT, loadDraft, loadQuotes, onSeed, registerComposer, saveDraft, saveQuotes, takeSeed, type Pending, type Seed } from './store'
import { fmtBytes } from '@/lib/format'
import type { QueueItem } from '@/lib/types'
import { baseName, isImage, quotedFile, quotesMarkdown, thumbUrl } from './util'
import { QuotedFile } from './QuotedFile'
import { pastedFile, pastedName } from './pasteAsFile'
import { VoiceButton } from '@/features/voice/VoiceButton'

const NO_ITEMS: QueueItem[] = []

type Att = { lid: string; name: string; size: number; path: string | null; progress: number; error: string | null; preview: string | null }

export type ComposerHandle = { addFiles: (files: File[]) => void; focus: () => void; quote: (text: string) => void; bringBack: (s: Seed) => void }

export const Composer = React.forwardRef<ComposerHandle, {
  colKey: string
  draftKey: string
  topicPath: string
  running?: boolean
  /** Reason the composer cannot send (shown inline); null = enabled. */
  disabledReason?: string | null
  queueCount?: number
  queued?: Pending[]
  /** The server's view of the queue (all of it, also what another tab, Telegram or the server queued). */
  queueItems?: QueueItem[]
  onClearQueue?: () => void | Promise<unknown>
  /** Steer: run the queued messages now (the current turn is cut short, Claude continues with them). */
  onSteer?: () => void
  steering?: boolean
  /** A steer was accepted: the current turn is ending, the queued messages start right after. */
  steerPending?: boolean
  /** Edit: takes the queued messages back (server queue emptied) - they are put in the composer. */
  onTakeQueue?: () => Promise<{ text: string; attachments: string[] }[]>
  /** Side question: the waiting messages become a question Claude answers apart, without interrupting the turn. */
  onAsk?: () => void
  asking?: boolean
  clearingQueue?: boolean
  onSend: (text: string, attachments: string[]) => Promise<boolean>
  /** Voice message sent directly (setting on by default): the recording is sent as it is, the server transcribes it. */
  onSendVoice?: (file: File) => Promise<boolean>
  onStop?: () => void
  stopping?: boolean
  toolbar?: React.ReactNode
  /** One-line notice tucked on top of the composer, like the waiting messages (which take priority). */
  notice?: React.ReactNode
  placeholder?: string
  autoFocus?: boolean
  /** Lines the text grows to before it scrolls (fewer in a small grid pane, so the conversation stays visible). */
  maxRows?: number
}>(function Composer(props, ref) {
  const { colKey, draftKey, topicPath, running, disabledReason, queueCount = 0, queued = [], queueItems = NO_ITEMS, onClearQueue, clearingQueue, onSteer, steering, steerPending, onTakeQueue, onAsk, asking, onSend, onStop, stopping, toolbar, notice, placeholder, autoFocus, maxRows = 12 } = props
  const t = useT()
  const [text, setText] = React.useState(() => loadDraft(draftKey))
  const [quotes, setQuotes] = React.useState<string[]>(() => loadQuotes(draftKey))
  const [atts, setAtts] = React.useState<Att[]>([])
  const [sending, setSending] = React.useState(false)
  const ta = React.useRef<HTMLTextAreaElement | null>(null)
  const fileInput = React.useRef<HTMLInputElement>(null)
  const ctrls = React.useRef(new Map<string, AbortController>())
  const previews = React.useRef(new Set<string>())
  const live = React.useRef({ text, quotes, draftKey })
  live.current = { text, quotes, draftKey }
  const mounted = React.useRef(true)

  const releasePreview = (preview: string | null) => {
    if (!preview) return
    URL.revokeObjectURL(preview)
    previews.current.delete(preview)
  }

  // A link typed a request in this draft (prefillDraft) while the composer was already open: show it.
  React.useEffect(() => {
    const onDraft = (e: Event) => {
      if ((e as CustomEvent<string>).detail === draftKey) setText(loadDraft(draftKey))
    }
    window.addEventListener(DRAFT_EVENT, onDraft)
    return () => window.removeEventListener(DRAFT_EVENT, onDraft)
  }, [draftKey])

  // Draft key changes (new column → real session): carry the text over.
  const prevKey = React.useRef(draftKey)
  React.useEffect(() => {
    if (prevKey.current !== draftKey) {
      saveDraft(prevKey.current, '')
      saveQuotes(prevKey.current, [])
      prevKey.current = draftKey
    }
  }, [draftKey])
  React.useEffect(() => {
    const id = setTimeout(() => saveDraft(draftKey, text), 250)
    return () => clearTimeout(id)
  }, [text, draftKey])
  React.useEffect(() => saveQuotes(draftKey, quotes), [quotes, draftKey])

  React.useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      saveDraft(live.current.draftKey, live.current.text)
      saveQuotes(live.current.draftKey, live.current.quotes)
      ctrls.current.forEach((c) => c.abort())
      previews.current.forEach((p) => URL.revokeObjectURL(p))
      previews.current.clear()
    }
  }, [])

  const addFiles = React.useCallback(
    (files: File[]): string[] => {
      const lids: string[] = []
      for (const f of files) {
        const lid = Math.random().toString(36).slice(2)
        lids.push(lid)
        const preview = f.type.startsWith('image/') ? URL.createObjectURL(f) : null
        if (preview) previews.current.add(preview)
        setAtts((a) => [...a, { lid, name: f.name || 'file', size: f.size, path: null, progress: 0, error: null, preview }])
        const ctrl = new AbortController()
        ctrls.current.set(lid, ctrl)
        uploadAttachment(topicPath, f, (l, tot) => setAtts((a) => a.map((x) => (x.lid === lid ? { ...x, progress: tot ? l / tot : 0 } : x))), ctrl.signal)
          .then((saved) => setAtts((a) => a.map((x) => (x.lid === lid ? { ...x, path: saved.path, name: saved.name, progress: 1 } : x))))
          .catch((e) => {
            if ((e as Error)?.name === 'AbortError') return
            setAtts((a) => a.map((x) => (x.lid === lid ? { ...x, error: errorMessage(e) } : x)))
            toast.error(t('sessions.uploadFailed', { name: f.name }))
          })
          .finally(() => ctrls.current.delete(lid))
      }
      return lids
    },
    [topicPath, t],
  )

  const removeAtt = (lid: string) => {
    ctrls.current.get(lid)?.abort()
    setAtts((a) => {
      const x = a.find((y) => y.lid === lid)
      releasePreview(x?.preview ?? null)
      return a.filter((y) => y.lid !== lid)
    })
  }

  // Quote (selection in a reply): added once, sent as Markdown blockquotes above the typed text.
  const quote = React.useCallback((q: string) => {
    const v = q.trim()
    if (v) setQuotes((cur) => (cur.includes(v) ? cur : [...cur, v]))
  }, [])
  // A message comes back here (text first, then what was already typed; its quotes and attachments too), cursor at the end.
  const bringBack = React.useCallback((s: Seed) => {
    if (s.text) setText((cur) => [s.text, cur.trim()].filter(Boolean).join('\n\n'))
    if (s.quotes.length) setQuotes((cur) => [...s.quotes.filter((q) => !cur.includes(q)), ...cur])
    if (s.attachments.length)
      setAtts((a) => [
        ...a,
        ...s.attachments
          .filter((p) => !a.some((x) => x.path === p))
          .map((p) => ({ lid: Math.random().toString(36).slice(2), name: p.split('/').pop() || p, size: 0, path: p, progress: 1, error: null, preview: isImage(p) ? thumbUrl(p, 160) : null })),
      ])
    requestAnimationFrame(() => {
      const el = ta.current
      if (el) {
        el.focus()
        el.setSelectionRange(el.value.length, el.value.length)
      }
    })
  }, [])
  React.useImperativeHandle(ref, () => ({ addFiles, focus: () => ta.current?.focus(), quote, bringBack }), [addFiles, quote, bringBack])
  // "New session from this message": the seed may be waiting when this composer mounts, or arrive while it is open.
  React.useEffect(() => {
    const s = takeSeed(draftKey)
    if (s) bringBack(s)
    return onSeed(draftKey, bringBack)
  }, [draftKey, bringBack])

  // Edit: the queued messages come back here. When every queued message is known to this tab (typed here), they
  // come back at once and the stack sinks; the server's answer only corrects what changed meanwhile (a message
  // that already started, one queued from Telegram).
  const [taking, setTaking] = React.useState(false)
  const [taken, setTaken] = React.useState(false)
  React.useEffect(() => {
    if (queueCount === 0) setTaken(false)
  }, [queueCount])
  const editQueue = async () => {
    if (!onTakeQueue) return
    const toSeed = (msgs: { text: string; attachments: string[] }[]): Seed => ({ text: msgs.map((m) => m.text).filter(Boolean).join('\n\n'), quotes: [], attachments: msgs.flatMap((m) => m.attachments) })
    const local = queued.length > 0 && queued.length === queueCount ? toSeed(queued) : null
    if (local) {
      bringBack(local)
      setTaken(true)
    } else setTaking(true)
    // Swap the text put in the composer for `next` (the user may have typed after it: that part stays).
    const swapText = (shown: string, next: string) =>
      setText((cur) => {
        if (!shown || !cur.startsWith(shown)) return next ? [next, cur.trim()].filter(Boolean).join('\n\n') : cur
        const rest = cur.slice(shown.length).replace(/^\n\n/, '')
        return [next, rest].filter(Boolean).join('\n\n')
      })
    try {
      const msgs = await onTakeQueue()
      if (!local) {
        if (!msgs.length) toast.info(t('sessions.queue.editNothing'))
        else bringBack(toSeed(msgs))
        return
      }
      const got = toSeed(msgs)
      if (got.text !== local.text) swapText(local.text, got.text)
      const gone = local.attachments.filter((p) => !got.attachments.includes(p))
      if (gone.length) setAtts((a) => a.filter((x) => !x.path || !gone.includes(x.path)))
      const extra = got.attachments.filter((p) => !local.attachments.includes(p))
      if (extra.length) bringBack({ text: '', quotes: [], attachments: extra })
      window.setTimeout(() => setTaken(false), 3000) // a message queued since then shows again
    } catch {
      // the toast of the mutation says why; the messages are still queued: take back what was put here
      if (local) {
        swapText(local.text, '')
        setAtts((a) => a.filter((x) => !x.path || !local.attachments.includes(x.path)))
        setTaken(false)
      }
    } finally {
      setTaking(false)
    }
  }

  // New files go at the end of the strip: keep them in view.
  const attBox = React.useRef<HTMLDivElement>(null)
  const attCount = React.useRef(atts.length)
  React.useEffect(() => {
    if (atts.length > attCount.current) attBox.current?.scrollTo({ top: attBox.current.scrollHeight, behavior: 'smooth' })
    attCount.current = atts.length
  }, [atts.length])

  const uploading = atts.some((a) => !a.path && !a.error)
  const failedUpload = atts.find((a) => a.error)
  const ready = atts.filter((a) => a.path)
  const empty = !text.trim() && ready.length === 0 && quotes.length === 0
  const blocked = disabledReason || uploading || !!failedUpload
  const reason = disabledReason || (uploading ? t('sessions.composer.uploading') : failedUpload ? t('sessions.uploadFailed', { name: failedUpload.name }) : null)

  // Sends are chained (never dropped, never reordered) — typing the next message while the previous
  // one is still in flight is fine.
  const chain = React.useRef<Promise<unknown>>(Promise.resolve())
  const inflight = React.useRef(0)
  const send = (voiceText?: string) => {
    const typed = text.trim()
    const body = voiceText ? (typed ? `${typed}\n\n${voiceText}` : voiceText) : typed
    if (blocked || (!body && ready.length === 0 && quotes.length === 0)) return
    const paths = ready.map((a) => a.path!) as string[]
    const sent = [quotesMarkdown(quotes), body].filter(Boolean).join('\n\n')
    setText('')
    const keep = atts
    setAtts([])
    const kept = quotes
    setQuotes([])
    inflight.current++
    setSending(true)
    chain.current = chain.current.then(async () => {
      const ok = await onSend(sent, paths).catch(() => false)
      if (--inflight.current === 0 && mounted.current) setSending(false)
      if (!ok) {
        // Preserve the refused message AND anything typed/attached while it was in flight.
        // If the column was closed meanwhile, keep the text in its persisted draft.
        const restore = (cur: string) => [body, cur].filter(Boolean).join('\n\n')
        const back = (cur: string[]) => [...kept, ...cur.filter((q) => !kept.includes(q))]
        if (mounted.current) {
          setText(restore)
          setAtts((cur) => [...keep, ...cur])
          setQuotes(back)
        } else {
          saveDraft(draftKey, restore(loadDraft(draftKey)))
          saveQuotes(draftKey, back(loadQuotes(draftKey)))
        }
      } else keep.forEach((a) => releasePreview(a.preview))
    })
    ta.current?.focus({ preventScroll: true })
  }

  // Voice message sent directly: queued like the other sends (order kept); refused = the recording comes back attached.
  const onVoiceMessage = (file: File) => {
    if (!props.onSendVoice || disabledReason) {
      addFiles([file])
      return
    }
    const sendVoice = props.onSendVoice
    inflight.current++
    setSending(true)
    chain.current = chain.current.then(async () => {
      const ok = await sendVoice(file).catch(() => false)
      if (--inflight.current === 0 && mounted.current) setSending(false)
      if (!ok && mounted.current) addFiles([file])
    })
  }

  // Voice transcript: inserted at the cursor for review, or sent right away (setting "send automatically").
  const onVoice = (heard: string, autoSend: boolean) => {
    if (autoSend && !blocked) {
      send(heard)
      return
    }
    const el = ta.current
    const start = el ? el.selectionStart : text.length
    const end = el ? el.selectionEnd : text.length
    const before = text.slice(0, start)
    const after = text.slice(end)
    const ins = (before && !/\s$/.test(before) ? ' ' : '') + heard + (after && !/^\s/.test(after) ? ' ' : '')
    setText(before + ins + after)
    requestAnimationFrame(() => {
      const caret = before.length + ins.length
      el?.focus({ preventScroll: true })
      el?.setSelectionRange(caret, caret)
    })
  }

  // Ctrl+Shift+V / ⌘⇧V just before the paste: keep it as text whatever it is.
  const plainPaste = React.useRef(0)
  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing) return
    if ((e.key === 'v' || e.key === 'V') && e.shiftKey && (e.metaKey || e.ctrlKey)) plainPaste.current = Date.now()
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey || !e.shiftKey)) {
      // On touch keyboards Enter inserts a newline (no Shift key); the send button sends.
      if (!e.metaKey && !e.ctrlKey && window.matchMedia('(pointer: coarse)').matches) return
      e.preventDefault()
      send()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      e.currentTarget.blur()
    }
  }

  const onPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(e.clipboardData?.files || [])
    if (files.length) {
      e.preventDefault()
      addFiles(files)
      return
    }
    const pasted = e.clipboardData?.getData('text/plain') || ''
    const as = Date.now() - plainPaste.current < 1000 ? null : pastedFile(pasted)
    if (!as) return
    e.preventDefault()
    const el = e.currentTarget
    const at = [el.selectionStart, el.selectionEnd]
    const name = pastedName(as.ext)
    const [lid] = addFiles([new File([pasted], name, { type: as.type })])
    void loadGroups(['paste']).then(() =>
      toast.action(t('paste.asFile'), t('paste.asFileHint'), {
        label: t('paste.asText'),
        onClick: () => {
          removeAtt(lid)
          setText((cur) => cur.slice(0, Math.min(at[0], cur.length)) + pasted + cur.slice(Math.min(at[1], cur.length)))
          ta.current?.focus()
        },
      }),
    )
  }

  const setRef = React.useCallback(
    (el: HTMLTextAreaElement | null) => {
      ta.current = el
      registerComposer(colKey, el)
    },
    [colKey],
  )
  React.useEffect(() => {
    if (autoFocus && window.matchMedia('(pointer: fine)').matches) ta.current?.focus({ preventScroll: true })
  }, [autoFocus])

  // The queue stack rises from behind the composer and sinks back when it empties: the last content stays
  // rendered during the exit (220 ms), the height animates with grid rows (no jump of the thread above).
  const [stack, setStack] = React.useState({ count: queueCount, items: queued, server: queueItems, leaving: false })
  const shownCount = taken ? 0 : queueCount
  React.useEffect(() => {
    if (shownCount > 0) {
      setStack({ count: shownCount, items: queued, server: queueItems, leaving: false })
      return
    }
    setStack((s) => (s.count > 0 ? { ...s, leaving: true } : s))
    const id = setTimeout(() => setStack((s) => (s.leaving ? { count: 0, items: [], server: NO_ITEMS, leaving: false } : s)), 220)
    return () => clearTimeout(id)
  }, [shownCount, queued, queueItems])
  const stackCount = stack.count

  // The notice (e.g. "plan ready") rises and sinks back the same way; it waits while the queue is shown.
  // (Keyed on a boolean: `notice` is a new element every render; the live one is shown, the last one while leaving.)
  const hasNotice = !!notice && stackCount === 0
  const lastNotice = React.useRef<React.ReactNode>(null)
  if (hasNotice) lastNotice.current = notice
  const [noticeState, setNoticeState] = React.useState<'hidden' | 'shown' | 'leaving'>(hasNotice ? 'shown' : 'hidden')
  React.useEffect(() => {
    if (hasNotice) {
      setNoticeState('shown')
      return
    }
    setNoticeState((s) => (s === 'shown' ? 'leaving' : s))
    const id = setTimeout(() => setNoticeState((s) => (s === 'leaving' ? 'hidden' : s)), 220)
    return () => clearTimeout(id)
  }, [hasNotice])
  const shownNotice = { node: noticeState === 'hidden' && !hasNotice ? null : hasNotice ? notice : lastNotice.current, leaving: noticeState === 'leaving' && !hasNotice }
  // The server lists every waiting message: shown as is, so a message queued before a reload (or from another
  // tab, Telegram, a cron) shows its text. Older servers send only the count: the messages typed here, then "+ n".
  // (the server sends the last 20 at most: the older ones are the "+ n")
  const fromServer = stackCount > 0 && stack.server.length >= Math.min(stackCount, 20)
  const queuedShown: { key: string; text: string; from?: string }[] = fromServer
    ? stack.server.slice(-stackCount).map((q, i) => ({
        key: `s${i}`,
        text: q.voice ? `🎤 ${[t('voice.message'), q.text].filter(Boolean).join(' · ')}` : q.text || t('sessions.queue.files', { count: q.attachments }),
        from: q.source === 'telegram' || q.source === 'cron' || q.source === 'system' ? t(`sessions.queue.from.${q.source}`) : undefined,
        // the server's own messages (summary before a compaction, handoff) are long internal prompts: their name only
        ...(q.source === 'system' && (q.kind === 'compact' || q.kind === 'handoff') ? { text: t(`sessions.queue.kind.${q.kind}`) } : {}),
      }))
    : stack.items.slice(-stackCount).map((p) => ({ key: p.lid, text: p.voice ? `🎤 ${t('voice.message')}` : p.text || p.attachments.map(baseName).join(', ') }))
  const extraQueued = Math.max(0, stackCount - queuedShown.length)

  // The quotes card sits right on top of the composer (under the queue stack and the notice), same rise and
  // sink; the last quotes stay rendered while it leaves.
  const hasQuotes = quotes.length > 0
  const lastQuotes = React.useRef(quotes)
  if (hasQuotes) lastQuotes.current = quotes
  const [quotesState, setQuotesState] = React.useState<'hidden' | 'shown' | 'leaving'>(hasQuotes ? 'shown' : 'hidden')
  React.useEffect(() => {
    if (hasQuotes) {
      setQuotesState('shown')
      return
    }
    setQuotesState((s) => (s === 'shown' ? 'leaving' : s))
    const id = setTimeout(() => setQuotesState((s) => (s === 'leaving' ? 'hidden' : s)), 220)
    return () => clearTimeout(id)
  }, [hasQuotes])
  const shownQuotes = hasQuotes ? quotes : quotesState === 'hidden' ? [] : lastQuotes.current
  const quotesLeaving = !hasQuotes && quotesState === 'leaving'
  const removeQuote = (q: string) => setQuotes((cur) => cur.filter((x) => x !== q))

  return (
    <div className="shrink-0 px-3 pt-1 pb-3 max-md:pb-[calc(0.5rem+var(--safe-bottom-ui))]">
      <div className="mx-auto w-full max-w-[860px]">
        <div className={cn('grid transition-[grid-template-rows] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none', stackCount > 0 && !stack.leaving ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')}>
        <div className="min-h-0 overflow-hidden" inert={stackCount === 0 || stack.leaving ? true : undefined}>
        {stackCount > 0 && (
          // Same surface as the composer (card, border, shadow) so it reads as part of it; the theme color is
          // only on the icon and the Steer button (like the send button). Tucks under the composer (-mb-3).
          <div
            className={cn('relative z-0 -mb-3 rounded-t-xl border border-b-0 bg-card shadow-xs', stack.leaving ? 'mx-queue-out' : 'mx-queue-in')}
            aria-live="polite"
          >
            <div className="flex items-center gap-1.5 px-3 pt-2 text-xs text-muted-foreground">
              {steerPending ? <Spinner className="size-3.5 text-primary" /> : <Clock className="size-3.5 shrink-0 text-primary" />}
              <span className="min-w-0 truncate">
                {steerPending ? t('sessions.queue.steering') : `${t('sessions.queue.count', { count: stackCount })} — ${t('sessions.queue.headline')}`}
              </span>
              {onClearQueue && !steerPending && (
                <Tooltip content={t('sessions.queue.clear')}>
                  <button
                    type="button"
                    onClick={() => {
                      // instant: the stack sinks now, comes back if the server refuses
                      setTaken(true)
                      Promise.resolve(onClearQueue()).then(
                        () => window.setTimeout(() => setTaken(false), 3000),
                        () => setTaken(false),
                      )
                    }}
                    disabled={clearingQueue}
                    aria-label={t('sessions.queue.clear')}
                    className="ml-auto -mr-1 flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  >
                    <X className="size-3.5" />
                  </button>
                </Tooltip>
              )}
            </div>
            <div className="flex items-center gap-2 px-3 pt-1 pb-5">
              <ol className="grid min-w-0 flex-1 gap-0.5 text-[14px] leading-relaxed text-foreground">
                {queuedShown.map((p) => (
                  <li key={p.key} className="line-clamp-2 break-words">
                    {p.from && <span className="mr-1.5 text-xs font-normal text-muted-foreground">{p.from} ·</span>}
                    <Sensitive length={12}>{p.text}</Sensitive>
                  </li>
                ))}
                {extraQueued > 0 && <li className="text-xs font-normal text-muted-foreground">{t('sessions.queue.other', { count: extraQueued })}</li>}
              </ol>
              <span className="flex shrink-0 items-center gap-1.5">
                {onTakeQueue && (
                  <Tooltip content={t('sessions.queue.editTip')}>
                    <Button size="sm" variant="ghost" className="h-7 px-2 text-xs max-md:h-8" onClick={() => void editQueue()} loading={taking} disabled={steerPending}>
                      <Pencil className="size-3.5" /> <span className="max-sm:sr-only">{t('sessions.queue.edit')}</span>
                    </Button>
                  </Tooltip>
                )}
                {onAsk && running && (
                  <Tooltip content={t('aside.askTip')}>
                    <Button size="sm" variant="ghost" className="h-7 px-2 text-xs max-md:h-8" onClick={onAsk} loading={asking} disabled={steerPending}>
                      <MessageCircleQuestion className="size-3.5" /> <span className="max-sm:sr-only">{t('aside.ask')}</span>
                    </Button>
                  </Tooltip>
                )}
                {onSteer && running && (
                  <Tooltip content={t('sessions.queue.steerTip')}>
                    <Button size="sm" className="h-7 px-2.5 text-xs max-md:h-8" onClick={onSteer} loading={steering || steerPending} disabled={steerPending}>
                      <CornerDownRight className="size-3.5" /> {t('sessions.queue.steerShort')}
                    </Button>
                  </Tooltip>
                )}
              </span>
            </div>
          </div>
        )}
        </div>
        </div>
        <div className={cn('grid transition-[grid-template-rows] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none', noticeState === 'shown' && hasNotice ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')}>
          <div className="min-h-0 overflow-hidden" inert={!shownNotice.node || shownNotice.leaving ? true : undefined}>
            {shownNotice.node && (
              <div className={cn('relative z-0 -mb-3 rounded-t-xl border border-b-0 bg-card shadow-xs', shownNotice.leaving ? 'mx-queue-out' : 'mx-queue-in')}>
                <div className="flex min-h-7 items-center gap-1.5 px-3 pt-1.5 pb-4.5 text-xs text-muted-foreground">{shownNotice.node}</div>
              </div>
            )}
          </div>
        </div>
        <div className={cn('grid transition-[grid-template-rows] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none', hasQuotes ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')}>
          <div className="min-h-0 overflow-hidden" inert={!hasQuotes ? true : undefined}>
            {shownQuotes.length > 0 && (
              <div className={cn('relative z-0 -mb-3 rounded-t-xl border border-b-0 bg-card shadow-xs', quotesLeaving ? 'mx-queue-out' : 'mx-queue-in')}>
                <div className="flex items-center gap-1.5 px-3 pt-2 text-xs text-muted-foreground">
                  <Quote className="size-3.5 shrink-0 text-primary" />
                  <span className="min-w-0 truncate">{t('sessions.quote.card', { count: shownQuotes.length })}</span>
                  <Tooltip content={t('sessions.quote.clear')}>
                    <button
                      type="button"
                      onClick={() => setQuotes([])}
                      aria-label={t('sessions.quote.clear')}
                      className="ml-auto -mr-1 flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                    >
                      <X className="size-3.5" />
                    </button>
                  </Tooltip>
                </div>
                <ul className="grid gap-2 px-3 pt-1.5 pb-5">
                  {shownQuotes.slice(0, 3).map((q) => (
                    <li key={q} className="group/quote flex items-start gap-1">
                      {quotedFile(q) ? (
                        <div className="min-w-0 flex-1 border-l-2 border-primary/60 pl-2">
                          <QuotedFile path={quotedFile(q)!} className="pr-2" />
                        </div>
                      ) : (
                        <blockquote className="line-clamp-3 min-w-0 flex-1 border-l-2 border-primary/60 pl-3 text-[15px] leading-relaxed break-words whitespace-pre-wrap text-foreground/85">
                          <Sensitive length={16}>{q}</Sensitive>
                        </blockquote>
                      )}
                      <Tooltip content={t('sessions.quote.remove')}>
                        <button
                          type="button"
                          onClick={() => removeQuote(q)}
                          aria-label={t('sessions.quote.remove')}
                          className="-mr-1 flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground opacity-0 group-hover/quote:opacity-100 hover:bg-accent hover:text-foreground focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none pointer-coarse:opacity-100"
                        >
                          <X className="size-3.5" />
                        </button>
                      </Tooltip>
                    </li>
                  ))}
                  {shownQuotes.length > 3 && <li className="pl-3.5 text-xs text-muted-foreground">{t('sessions.quote.other', { count: shownQuotes.length - 3 })}</li>}
                </ul>
              </div>
            )}
          </div>
        </div>
        <div
          data-tour="composer"
          className={cn(
            'relative z-10 rounded-xl border bg-card shadow-xs transition-[border-color,box-shadow] focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/20',
            disabledReason && 'opacity-80',
          )}
        >
          {atts.length > 0 && (
            // Many files: a small scrolling strip (two rows) instead of a composer that eats the conversation.
            <div ref={attBox} data-testid="composer-attachments" className="flex max-h-[6.75rem] flex-wrap gap-1.5 overflow-y-auto overscroll-contain px-2.5 pt-2.5 [scrollbar-width:thin]">
              {atts.map((a) => (
                <AttachmentChip key={a.lid} att={a} onRemove={() => removeAtt(a.lid)} />
              ))}
            </div>
          )}
          <Textarea
            ref={setRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
            minRows={1}
            maxRows={maxRows}
            placeholder={placeholder || t('sessions.composer.placeholder')}
            aria-label={t('sessions.composer.label')}
            className="border-0 bg-transparent px-3.5 pt-3 pb-1 shadow-none focus-visible:ring-0 dark:bg-transparent"
          />
          <div className="@container flex min-w-0 items-center gap-1 px-1.5 pb-1.5">
            <input
              ref={fileInput}
              type="file"
              multiple
              hidden
              onChange={(e) => {
                addFiles(Array.from(e.target.files || []))
                e.target.value = ''
              }}
            />
            <Tooltip content={t('sessions.composer.attach')}>
              <Button variant="ghost" size="icon-sm" aria-label={t('sessions.composer.attach')} onClick={() => fileInput.current?.click()}>
                <Paperclip />
              </Button>
            </Tooltip>
            {toolbar}
            <div className="ml-auto flex min-w-0 items-center gap-1.5">
              {reason && <span className="truncate text-[11px] text-muted-foreground max-sm:hidden">{reason}</span>}
              {running && onStop && (
                <Tooltip content={t('sessions.stop')}>
                  <Button variant="outline" size="icon-sm" aria-label={t('sessions.stop')} onClick={onStop} loading={stopping} className="max-md:size-11 max-md:rounded-full">
                    <Square className="fill-current" />
                  </Button>
                </Tooltip>
              )}
              <VoiceButton onTranscript={onVoice} onVoiceMessage={props.onSendVoice ? onVoiceMessage : undefined} />
              <Tooltip content={running ? t('sessions.composer.queue') : t('sessions.composer.send')}>
                <Button size="icon-sm" aria-label={running ? t('sessions.composer.queue') : t('sessions.composer.send')} disabled={!!blocked || empty} onClick={() => send()} className="rounded-lg max-md:size-11 max-md:rounded-full max-md:[&_svg]:size-5">
                  {sending ? <Spinner className="size-4" /> : <ArrowUp />}
                </Button>
              </Tooltip>
            </div>
          </div>
        </div>
        {reason && <p className="mt-1 truncate text-[11px] text-muted-foreground sm:hidden">{reason}</p>}
      </div>
    </div>
  )
})

function AttachmentChip({ att, onRemove }: { att: Att; onRemove: () => void }) {
  const t = useT()
  const done = !!att.path
  return (
    <div className={cn('group relative flex h-12 max-w-52 items-center gap-2 overflow-hidden rounded-lg border bg-background pr-7 pl-1', att.error && 'border-destructive/50')}>
      {att.preview && isImage(att.name) ? (
        <img src={att.preview} alt="" className="size-10 shrink-0 rounded-md object-cover" />
      ) : (
        <span className="flex size-10 shrink-0 items-center justify-center rounded-md bg-muted">
          <FileText className="size-4 text-muted-foreground" />
        </span>
      )}
      <span className="grid min-w-0 text-xs leading-tight">
        <span className="truncate font-medium">
          <Sensitive length={8}>{att.name}</Sensitive>
        </span>
        <span className={cn('truncate text-[11px]', att.error ? 'text-destructive' : 'text-muted-foreground')}>
          {att.error ? t('common.failed') : done ? (att.size ? fmtBytes(att.size) : '') : `${Math.round(att.progress * 100)} %`}
        </span>
      </span>
      {!done && !att.error && <span className="absolute bottom-0 left-0 h-0.5 bg-primary transition-[width]" style={{ width: `${Math.round(att.progress * 100)}%` }} />}
      <button
        type="button"
        onClick={onRemove}
        aria-label={t('common.remove')}
        className="absolute top-1 right-1 flex size-5 items-center justify-center rounded-md text-muted-foreground before:absolute before:-inset-2.5 before:content-[''] hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <X className="size-3.5" />
      </button>
    </div>
  )
}
