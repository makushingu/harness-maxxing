// Message composer: autosize textarea, drafts, attachments (button / drop / paste), queue stack, quotes,
// send / stop. Enter sends, Shift+Enter = newline, Ctrl/⌘+Enter sends, Esc blurs.
import * as React from 'react'
import { Clock, CornerDownRight, ListPlus, MessageCircleQuestion, Pencil, Quote, X } from 'lucide-react'
import { loadGroups, useT } from '@/i18n'
import { Button, Sensitive, Spinner, Tooltip, toast } from '@/components/ui'
import { uploadAttachment, useMentionTargets } from '@/lib/queries'
import { errorMessage } from '@/lib/api'
import { DRAFT_EVENT, leftOutbox, loadAtts, loadDraft, loadQuotes, onSeed, outboxAdd, outboxDone, outboxMove, registerComposer, saveAtts, saveDraft, saveQuotes, takeSeed, type DraftAtt, type OutboxEntry, type Pending, type Seed } from './store'
import { busyEnd, busyStart } from '@/lib/busy'
import type { MentionTarget, QueueItem, SentMention } from '@/lib/types'
import { baseName, isImage, quotedFile, quotesMarkdown, thumbUrl } from './util'
import { QuotedFile } from './QuotedFile'
import { pastedFile, pastedName } from './pasteAsFile'
import { VoiceButton } from '@/features/voice/VoiceButton'
import { SlashMenu, slashAction, slashItems, type MenuRow, type SlashCommand } from './SlashMenu'
import { mentionAt, mentionRows, targetChip, usedMentions } from './mentions'
import { ChipBackdrop, findCommand, findNames } from '@/features/chips/Chip'
import { AttachmentChip, type Att } from '@/features/composer/AttachmentChip'
import { CloseButton, MessageBox, StopButton, TuckedCard } from '@/features/composer/MessageBox'

const NO_ITEMS: QueueItem[] = []

export { AttachmentChip, type Att }
export const fromDraftAtt = (a: DraftAtt): Att => ({ lid: Math.random().toString(36).slice(2), name: a.name, size: a.size, path: a.path, progress: 1, error: null, preview: isImage(a.path) ? thumbUrl(a.path, 160, 160) : null })
export const toDraftAtts = (atts: Att[]): DraftAtt[] => atts.filter((a) => a.path && !a.error).map((a) => ({ path: a.path!, name: a.name, size: a.size }))

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
  /** Add to task: the queued messages go into the running turn without interrupting it (read at Claude's next step). */
  onInject?: () => void
  injecting?: boolean
  /** Edit: takes the queued messages back (server queue emptied) - they are put in the composer. */
  onTakeQueue?: () => Promise<{ text: string; attachments: string[] }[]>
  /** Side question: the waiting messages become a question Claude answers apart, without interrupting the turn. */
  onAsk?: () => void
  asking?: boolean
  clearingQueue?: boolean
  /** `clientId`: the outbox id, sent with the message so that a reload mid-send can tell whether it arrived. */
  onSend: (text: string, attachments: string[], clientId?: string, mentions?: SentMention[]) => Promise<boolean>
  /** Messages a previous page load was sending when it went away: resolves to those the server never got. */
  checkSent?: (left: OutboxEntry[]) => Promise<OutboxEntry[] | null>
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
  /** The "/" menu: the session's commands and the topic's skills (none: "/" is plain text). */
  commands?: SlashCommand[]
  /** The "@" menu (mentions.tsx): the id of the session it writes to (none: "@" is plain text). */
  mentionsFor?: string
}>(function Composer(props, ref) {
  const { colKey, draftKey, topicPath, running, disabledReason, queueCount = 0, queued = [], queueItems = NO_ITEMS, onClearQueue, clearingQueue, onSteer, steering, steerPending, onInject, injecting, onTakeQueue, onAsk, asking, onSend, onStop, stopping, toolbar, notice, placeholder, autoFocus, maxRows = 12 } = props
  const t = useT()
  const [text, setText] = React.useState(() => loadDraft(draftKey))
  const [quotes, setQuotes] = React.useState<string[]>(() => loadQuotes(draftKey))
  const [atts, setAtts] = React.useState<Att[]>(() => loadAtts(draftKey).map(fromDraftAtt))
  const [sending, setSending] = React.useState(false)
  const ta = React.useRef<HTMLTextAreaElement | null>(null)
  const ctrls = React.useRef(new Map<string, AbortController>())
  const previews = React.useRef(new Set<string>())
  const live = React.useRef({ text, quotes, atts, draftKey })
  live.current = { text, quotes, atts, draftKey }
  const mounted = React.useRef(true)

  const releasePreview = (preview: string | null) => {
    if (!preview) return
    URL.revokeObjectURL(preview)
    previews.current.delete(preview)
  }

  // A link typed a request in this draft (prefillDraft) while the composer was already open: show it.
  React.useEffect(() => {
    const onDraft = (e: Event) => {
      if ((e as CustomEvent<string>).detail !== draftKey) return
      setText(loadDraft(draftKey))
      // a link started a request here: ready to finish the sentence (computer only, as autoFocus below)
      if (window.matchMedia('(pointer: fine)').matches) requestAnimationFrame(() => focusAtEnd(ta.current))
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
      saveAtts(prevKey.current, [])
      outboxMove(prevKey.current, draftKey)
      prevKey.current = draftKey
    }
  }, [draftKey])
  const unsaved = React.useRef(false)
  const loaded = React.useRef<string | null>(draftKey) // the text was just read from this draft: nothing to store yet
  React.useEffect(() => {
    if (loaded.current === draftKey) {
      loaded.current = null
      return
    }
    loaded.current = null
    unsaved.current = true
    const id = setTimeout(() => {
      saveDraft(draftKey, text)
      unsaved.current = false
    }, 250)
    return () => clearTimeout(id)
  }, [text, draftKey])
  React.useEffect(() => saveQuotes(draftKey, quotes), [quotes, draftKey])
  React.useEffect(() => saveAtts(draftKey, toDraftAtts(atts)), [atts, draftKey])
  // The page goes away (reload, update, closed tab): the text typed in the last 250 ms is kept too (quotes and
  // files are stored at once).
  React.useEffect(() => {
    const flush = () => {
      if (!unsaved.current) return // already stored (and another tab may have written it since)
      saveDraft(live.current.draftKey, live.current.text)
      unsaved.current = false
    }
    const onHidden = () => document.visibilityState === 'hidden' && flush()
    window.addEventListener('pagehide', flush)
    document.addEventListener('visibilitychange', onHidden)
    return () => {
      window.removeEventListener('pagehide', flush)
      document.removeEventListener('visibilitychange', onHidden)
    }
  }, [])

  React.useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      // Only what this box has not stored yet (quotes and files are stored at once): another tab on the same
      // session may have written the draft since.
      if (unsaved.current) saveDraft(live.current.draftKey, live.current.text)
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
        busyStart()
        uploadAttachment(topicPath, f, (l, tot) => setAtts((a) => a.map((x) => (x.lid === lid ? { ...x, progress: tot ? l / tot : 0 } : x))), ctrl.signal)
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
        ...s.attachments.filter((p) => !a.some((x) => x.path === p)).map((p) => fromDraftAtt({ path: p, name: p.split('/').pop() || p, size: 0 })),
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
  // Messages that were being sent when the page went away: back in the box unless the server got them.
  const checkSent = props.checkSent
  React.useEffect(() => {
    let off = false
    let left: OutboxEntry[] = []
    void leftOutbox(draftKey)
      .then((l) => {
        left = l
        if (off || !l.length) return null
        return checkSent ? checkSent(l) : l
      })
      .then((lost) => {
        if (off || !lost) return // null: could not tell, they stay stored
        // already back in the draft (refused, then the page went away before its entry was removed)
        const back = lost.filter((e) => !(e.body && live.current.text.includes(e.body)))
        try {
          for (const e of [...back].reverse()) bringBack({ text: e.body, quotes: e.quotes, attachments: e.attachments })
        } finally {
          left.forEach((e) => outboxDone(draftKey, e.id)) // removed even if bringing one back failed: never again each load
        }
        if (back.length) toast.info(t('sessions.composer.sendInterrupted', { count: back.length }))
      })
    return () => {
      off = true
    }
  }, [draftKey]) // eslint-disable-line react-hooks/exhaustive-deps

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
    // Taken out of the server's queue: the messages must land somewhere - the box, or its draft when the box went
    // away during the request (another page).
    const keep = (sd: Seed) => {
      if (mounted.current) return bringBack(sd)
      if (sd.text) saveDraft(draftKey, [sd.text, loadDraft(draftKey).trim()].filter(Boolean).join('\n\n'))
      const had = loadAtts(draftKey)
      const add = sd.attachments.filter((p) => !had.some((x) => x.path === p)).map((p) => ({ path: p, name: p.split('/').pop() || p, size: 0 }))
      if (add.length) saveAtts(draftKey, [...had, ...add])
      window.dispatchEvent(new CustomEvent(DRAFT_EVENT, { detail: draftKey }))
    }
    try {
      const msgs = await onTakeQueue()
      if (!local) {
        if (!msgs.length) toast.info(t('sessions.queue.editNothing'))
        else keep(toSeed(msgs))
        return
      }
      const got = toSeed(msgs)
      if (got.text !== local.text) swapText(local.text, got.text)
      const gone = local.attachments.filter((p) => !got.attachments.includes(p))
      if (gone.length) setAtts((a) => a.filter((x) => !x.path || !gone.includes(x.path)))
      const extra = got.attachments.filter((p) => !local.attachments.includes(p))
      if (extra.length) keep({ text: '', quotes: [], attachments: extra })
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
    const act = !voiceText && props.commands ? slashAction(text, props.commands) : null
    if (act && !(atts.length || quotes.length)) {
      if ((act.cmd.args?.length || act.cmd.freeArg) && !act.arg) setText(`/${act.cmd.name} `) // asks for its value
      else {
        setText('')
        act.cmd.run!(act.arg)
      }
      return
    }
    const typed = text.trim()
    const body = voiceText ? (typed ? `${typed}\n\n${voiceText}` : voiceText) : typed
    if (blocked || (!body && ready.length === 0 && quotes.length === 0)) return
    const paths = ready.map((a) => a.path!) as string[]
    const sent = [quotesMarkdown(quotes), body].filter(Boolean).join('\n\n')
    const named = usedMentions(body, picked)
    const keptPicked = picked
    setPicked([])
    setText('')
    const keep = atts
    setAtts([])
    const kept = quotes
    setQuotes([])
    inflight.current++
    setSending(true)
    // Kept until the server answers: a reload in between brings it back (Composer mount, checkSent).
    const k0 = draftKey
    const outId = outboxAdd(k0, { text: sent, body, quotes: kept, attachments: paths })
    busyStart()
    chain.current = chain.current.then(async () => {
      const ok = await onSend(sent, paths, outId, named.length ? named : undefined).catch(() => false)
      if (--inflight.current === 0 && mounted.current) setSending(false)
      // Refused: it comes back in the box below. A failure can also be the page going away (its request is cut):
      // the entry is removed only if the page is still here a moment later, else the next load brings it back.
      const done = () => {
        outboxDone(k0, outId)
        if (live.current.draftKey !== k0) outboxDone(live.current.draftKey, outId)
      }
      if (ok) done()
      else window.setTimeout(done, 1500)
      busyEnd()
      if (!ok) {
        // Preserve the refused message AND anything typed/attached while it was in flight.
        // If the column was closed meanwhile, keep the text in its persisted draft.
        const restore = (cur: string) => [body, cur].filter(Boolean).join('\n\n')
        const back = (cur: string[]) => [...kept, ...cur.filter((q) => !kept.includes(q))]
        if (mounted.current) {
          setText(restore)
          setPicked((cur) => [...keptPicked, ...cur])
          setAtts((cur) => [...keep, ...cur])
          setQuotes(back)
        } else {
          const files = toDraftAtts(keep)
          saveDraft(draftKey, restore(loadDraft(draftKey)))
          saveQuotes(draftKey, back(loadQuotes(draftKey)))
          saveAtts(draftKey, [...files, ...loadAtts(draftKey).filter((a) => !files.some((f) => f.path === a.path))])
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
  // The "/" menu: open while the text is "/name" (or "/name value" for a command with values), closed by Esc
  // until the text changes.
  const [slashOff, setSlashOff] = React.useState<string | null>(null)
  const [expanded, setExpanded] = React.useState<string[]>([])
  const menu = props.commands && slashOff !== text ? slashItems(text, props.commands, expanded) : null
  // The "@" menu (when no "/" menu): open while an "@name" is typed just before the caret.
  const [caret, setCaret] = React.useState(0)
  const [picked, setPicked] = React.useState<MentionTarget[]>([])
  const at = !menu && props.mentionsFor && slashOff !== text ? mentionAt(text, caret) : null
  const { data: targets } = useMentionTargets(props.mentionsFor || '', !!props.mentionsFor && text.includes('@'))
  const atRows = at && targets ? mentionRows(at.q, targets, t, expanded) : []
  // What the text names, drawn as chips behind it: the "/" command it starts with, the @ picked from the menu.
  const commands = props.commands
  const chipSpans = React.useMemo(() => {
    const cmd = commands ? findCommand(text, (n) => commands.some((c) => c.name === n)) : null
    const names = findNames(text, picked.map((x) => ({ raw: `@${x.label}`, chip: targetChip(x) })))
    return cmd ? [cmd, ...names.filter((n) => n.start >= cmd.end)] : names
  }, [text, picked, commands])
  const rows: MenuRow[] = menu ? menu.items : atRows
  const [slashAt, setSlashAt] = React.useState(0)
  const menuKey = menu ? `${menu.stage}:${menu.items.map((i) => i.key).join('|')}` : atRows.length ? `@${atRows.map((i) => i.key).join('|')}` : ''
  React.useEffect(() => {
    if (!menu && !at && expanded.length) setExpanded([]) // folded again the next time a menu opens
  }, [!!menu, !!at]) // eslint-disable-line react-hooks/exhaustive-deps
  const keepAt = React.useRef<number | null>(null)
  React.useEffect(() => {
    setSlashAt(keepAt.current ?? 0)
    keepAt.current = null
  }, [menuKey])
  const active = rows.length ? Math.min(slashAt, rows.length - 1) : 0
  const pickMention = (i: number) => {
    const row = atRows[i]
    if (!row || !at) return
    if (row.expand) {
      const g = row.expand
      keepAt.current = i
      setExpanded((cur) => [...cur, g])
      return
    }
    const target = row.target
    if (!target) return
    const name = `@${target.label} `
    const next = text.slice(0, at.start) + name + text.slice(caret).replace(/^\S* ?/, '')
    const pos = at.start + name.length
    setText(next)
    setCaret(pos)
    setPicked((cur) => [...cur.filter((x) => x.kind !== target.kind || x.ref !== target.ref), target])
    requestAnimationFrame(() => {
      ta.current?.focus({ preventScroll: true })
      ta.current?.setSelectionRange(pos, pos)
    })
  }
  const pickSlash = (i: number, complete = false) => {
    const it = menu?.items[i]
    if (!it) return
    const c = it.cmd
    if (it.expand) {
      const g = it.expand
      keepAt.current = i
      setExpanded((cur) => [...cur, g]) // "+ N more": the group unfolds, the selection stays on the same place
      return
    }
    if (menu!.stage === 'arg') {
      setText('')
      c.run?.(it.arg ?? '')
    } else if (!complete && c.kind === 'action' && c.run && !c.args?.length && !c.freeArg) {
      setText('')
      c.run('')
    } else setText(`/${c.name} `)
    requestAnimationFrame(() => focusAtEnd(ta.current))
  }
  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing) return
    if (atRows.length) {
      const n = atRows.length
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        setSlashAt((active + (e.key === 'ArrowDown' ? 1 : n - 1)) % n)
        return
      }
      if ((e.key === 'Tab' && !e.shiftKey) || (e.key === 'Enter' && !e.shiftKey && !e.metaKey && !e.ctrlKey)) {
        e.preventDefault()
        pickMention(active)
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setSlashOff(text)
        return
      }
    }
    if (menu) {
      const n = menu.items.length
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        setSlashAt((active + (e.key === 'ArrowDown' ? 1 : n - 1)) % n)
        return
      }
      if (e.key === 'Tab' && !e.shiftKey) {
        e.preventDefault()
        pickSlash(active, true)
        return
      }
      if (e.key === 'Enter' && !e.shiftKey && !e.metaKey && !e.ctrlKey) {
        // the name typed in full with nothing to choose: Enter sends it as usual ("/skill" goes to Claude)
        const exact = menu.stage === 'name' && menu.items[active].label === text.trim() && menu.items[active].cmd.kind === 'skill'
        if (!exact) {
          e.preventDefault()
          pickSlash(active)
          return
        }
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setSlashOff(text)
        return
      }
    }
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

  const [taEl, setTaEl] = React.useState<HTMLTextAreaElement | null>(null)
  const setRef = React.useCallback(
    (el: HTMLTextAreaElement | null) => {
      ta.current = el
      setTaEl(el)
      registerComposer(colKey, el)
    },
    [colKey],
  )
  React.useEffect(() => {
    if (autoFocus && window.matchMedia('(pointer: fine)').matches) focusAtEnd(ta.current) // after a pre-filled draft
  }, [autoFocus])

  // The queue card rises from behind the box and sinks back when it empties (TuckedCard keeps its last content
  // while it leaves). The server lists every waiting message: shown as is, so a message queued before a reload (or
  // from another tab, Telegram, a cron) shows its text. Older servers send only the count: the messages typed here,
  // then "+ n". (the server sends the last 20 at most: the older ones are the "+ n")
  const stackCount = taken ? 0 : queueCount
  const fromServer = stackCount > 0 && queueItems.length >= Math.min(stackCount, 20)
  const queuedShown: { key: string; text: string; from?: string }[] = fromServer
    ? queueItems.slice(-stackCount).map((q, i) => ({
        key: `s${i}`,
        text: q.voice ? `🎤 ${[t('voice.message'), q.text].filter(Boolean).join(' · ')}` : q.text || t('sessions.queue.files', { count: q.attachments }),
        from: q.source === 'telegram' || q.source === 'cron' || q.source === 'system' ? t(`sessions.queue.from.${q.source}`) : undefined,
        // the server's own messages (summary before a compaction, handoff) are long internal prompts: their name only
        ...(q.source === 'system' && (q.kind === 'compact' || q.kind === 'handoff') ? { text: t(`sessions.queue.kind.${q.kind}`) } : {}),
      }))
    : queued.slice(-stackCount).map((p) => ({ key: p.lid, text: p.voice ? `🎤 ${t('voice.message')}` : p.text || p.attachments.map(baseName).join(', ') }))
  const extraQueued = Math.max(0, stackCount - queuedShown.length)
  // The notice (e.g. "plan ready") waits while the queue is shown; the quotes card sits right on top of the box.
  const hasNotice = !!notice && stackCount === 0
  const removeQuote = (q: string) => setQuotes((cur) => cur.filter((x) => x !== q))
  const small = 'h-7 px-2 text-xs max-md:h-8 pointer-coarse:h-10 max-md:pointer-coarse:h-10 pointer-coarse:min-w-10'

  const above = (
    <>
      {/* Same surface as the box (card, border, shadow) so it reads as part of it; the theme color is only on the
          icon and the Steer button (like the send button). */}
      <TuckedCard open={stackCount > 0} aria-live="polite">
        <div className="flex items-center gap-1.5 px-3 pt-2 text-xs text-muted-foreground">
          {steerPending ? <Spinner className="size-3.5 text-primary" /> : <Clock className="size-3.5 shrink-0 text-primary" />}
          <span className="min-w-0 truncate">
            {steerPending ? t('sessions.queue.steering') : `${t('sessions.queue.count', { count: stackCount })} — ${t('sessions.queue.headline')}`}
          </span>
          {onClearQueue && !steerPending && (
            <CloseButton
              label={t('sessions.queue.clear')}
              disabled={clearingQueue}
              onClick={() => {
                // instant: the stack sinks now, comes back if the server refuses
                setTaken(true)
                Promise.resolve(onClearQueue()).then(
                  () => window.setTimeout(() => setTaken(false), 3000),
                  () => setTaken(false),
                )
              }}
            />
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
                <Button size="sm" variant="ghost" className={small} onClick={() => void editQueue()} loading={taking} disabled={steerPending}>
                  <Pencil className="size-3.5" /> <span className="max-sm:sr-only">{t('sessions.queue.edit')}</span>
                </Button>
              </Tooltip>
            )}
            {onAsk && running && (
              <Tooltip content={t('aside.askTip')}>
                <Button size="sm" variant="ghost" className={small} onClick={onAsk} loading={asking} disabled={steerPending}>
                  <MessageCircleQuestion className="size-3.5" /> <span className="max-sm:sr-only">{t('aside.ask')}</span>
                </Button>
              </Tooltip>
            )}
            {onInject && running && (
              <Tooltip content={t('sessions.queue.injectTip')}>
                <Button size="sm" variant="ghost" className={small} onClick={onInject} loading={injecting} disabled={steerPending}>
                  <ListPlus className="size-3.5" /> <span className="max-sm:sr-only">{t('sessions.queue.inject')}</span>
                </Button>
              </Tooltip>
            )}
            {onSteer && running && (
              <Tooltip content={t('sessions.queue.steerTip')}>
                <Button size="sm" className="h-7 px-2.5 text-xs max-md:h-8 pointer-coarse:h-10 max-md:pointer-coarse:h-10" onClick={onSteer} loading={steering || steerPending} disabled={steerPending}>
                  <CornerDownRight className="size-3.5" /> {t('sessions.queue.steerShort')}
                </Button>
              </Tooltip>
            )}
          </span>
        </div>
      </TuckedCard>
      <TuckedCard open={hasNotice}>
        <div className="flex min-h-7 items-center gap-1.5 px-3 pt-1.5 pb-4.5 text-xs text-muted-foreground">{notice}</div>
      </TuckedCard>
      <TuckedCard open={quotes.length > 0}>
        <div className="flex items-center gap-1.5 px-3 pt-2 text-xs text-muted-foreground">
          <Quote className="size-3.5 shrink-0 text-primary" />
          <span className="min-w-0 truncate">{t('sessions.quote.card', { count: quotes.length })}</span>
          <CloseButton label={t('sessions.quote.clear')} onClick={() => setQuotes([])} />
        </div>
        <ul className="grid gap-2 px-3 pt-1.5 pb-5">
          {quotes.slice(0, 3).map((q) => (
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
                  className="relative -mr-1 flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground opacity-0 group-hover/quote:opacity-100 hover:bg-accent hover:text-foreground focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none pointer-coarse:opacity-100 pointer-coarse:before:absolute pointer-coarse:before:-inset-2 pointer-coarse:before:content-['']"
                >
                  <X className="size-3.5" />
                </button>
              </Tooltip>
            </li>
          ))}
          {quotes.length > 3 && <li className="pl-3.5 text-xs text-muted-foreground">{t('sessions.quote.other', { count: quotes.length - 3 })}</li>}
        </ul>
      </TuckedCard>
    </>
  )

  return (
    <MessageBox
      above={above}
      menu={
        menu ? (
          <SlashMenu items={menu.items} active={active} stage={menu.stage} onPick={(i) => pickSlash(i)} onHover={setSlashAt} />
        ) : atRows.length > 0 ? (
          <SlashMenu items={atRows} active={active} stage="arg" label={t('mention.label')} keys={t('mention.keys')} onPick={pickMention} onHover={setSlashAt} />
        ) : null
      }
      atts={atts}
      onRemoveAtt={removeAtt}
      backdrop={<ChipBackdrop text={text} spans={chipSpans} target={taEl} />}
      textareaRef={setRef}
      textarea={{
        value: text,
        onChange: (e) => {
          setText(e.target.value)
          setCaret(e.target.selectionStart)
        },
        onSelect: (e) => setCaret(e.currentTarget.selectionStart),
        onKeyDown,
        onPaste,
        maxRows,
        placeholder: placeholder || t('sessions.composer.placeholder'),
        'aria-label': t('sessions.composer.label'),
        'data-kbd-cap': '',
      }}
      onFiles={addFiles}
      toolbar={toolbar}
      actions={running && onStop ? <StopButton onClick={onStop} busy={stopping} label={t('sessions.stop')} /> : null}
      voice={<VoiceButton draftKey={draftKey} onTranscript={onVoice} onVoiceMessage={props.onSendVoice ? onVoiceMessage : undefined} />}
      send={{ onClick: () => send(), disabled: !!blocked || empty, busy: sending, label: running ? t('sessions.composer.queue') : t('sessions.composer.send') }}
      reason={reason}
      dimmed={!!disabledReason}
      boxProps={{ 'data-tour': 'composer', 'data-kbd-box': '' }}
    />
  )
})

/** Focus with the cursor after the text (a draft pre-filled by a link ends where the user goes on typing). */
function focusAtEnd(el: HTMLTextAreaElement | null) {
  if (!el) return
  el.focus({ preventScroll: true })
  el.setSelectionRange(el.value.length, el.value.length)
}
