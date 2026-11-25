// Rendering of one thread item. Every row is memoised on the item object (items keep their identity
// when the log grows, see log.ts), so appending events only renders the new rows.
import * as React from 'react'
import { AlertTriangle, Brain, FolderSearch, Check, ChevronRight, CircleAlert, Copy, FileText, GripVertical, History, Info, MessageSquarePlus, Mic, Paperclip, Pause, Pencil, Play, ScrollText, Trash2, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT, useLang } from '@/i18n'
import { fmtDate, fmtNumber } from '@/lib/format'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, Sensitive, Spinner, Tooltip, usePresentation } from '@/components/ui'
import { Markdown } from '@/components/ui/markdown'
import { filePreviewUrl, fileRawUrl, fileStamp, fileThumbUrl, prefetchImage, PREVIEW_W } from '@/lib/queries/files'
import { Thumb } from '@/features/files/Thumb'
import type { ChangesEvent, ClaudeModel, MessageFrom, ResultField, SentMention } from '@/lib/types'
import { MessageCard, messageFrom } from './MessageCard'
import { ChipText } from './mentions'
import { costTip, ResultLineMenu, useCostIsBilled, useResultLine } from './resultLine'
import { isShownTask, taskStatus, type Item } from './log'
import { TaskDetails, TaskElapsed, TaskStatusIcon, useOpenTaskLine } from './Tasks'
import type { Seed } from './store'
import { useOpenPreview } from './FilePreview'
import { MediaPlayer } from '@/features/files/MediaPlayer'
import { QuotedFile } from './QuotedFile'
import { ChangesChip } from './ChangesChip'
import { CutCard } from './Cut'
import { useRevert } from '@/features/code/useRevert'
import { SendToDialog, SendToSub, type SendTarget } from '@/features/team/SendTo'
import { gripRef } from './contentDrag'
import { toolKind, toolLabel } from './toolLabel'
import { authServerOf, McpAuthButton } from '@/features/mcp/AuthButton'
import { audioPaths, baseName, diffStats, FILE_HREF, fileHrefPath, fmtCost, fmtMs, fmtTokens, isAudio, isImage, isVideo, lineDiff, linkifyMarkdown, mediaPaths, modelLabel, scopeOf, quotedFile, relPath, relPaths, splitQuotes, toolIcon, type DiffLine } from './util'

export type ItemCtx = {
  filesRoot: string | null
  models: ClaudeModel[] | undefined
  running: boolean
  tz?: string
  /** Absolute topic folder of the session and workspace root: tool cards show paths relative to them. */
  topicDir?: string | null
  wsRoot?: string | null
  /** Set for the answers of agents and groups (their text may come from mail, webhooks, other agents): the only
   *  folders whose paths become links, thumbnails and players (server: GET .../media-roots), each file checked by the
   *  server through `within`. Unset (sessions): every path of filesRoot. */
  scope?: readonly string[] | null
  /** The session shown (unset outside a session column): what the Changes chip opens. */
  sid?: string
  /** Its topic (`projects/<p>/topics/<t>`): the skills a "/name" message can start. */
  path?: string
}
/** Hover / focus on a media thumbnail: start loading what the viewer will show (light preview, video poster). */
function prefetchMedia(p: string) {
  // with the file's stamp, asked when not known yet: the very URL the viewer will ask for
  if (isImage(p)) void fileStamp(p).then((v) => prefetchImage(filePreviewUrl(p, PREVIEW_W, v)))
  else if (isVideo(p)) void fileStamp(p).then((v) => prefetchImage(fileThumbUrl(p, 1280, v)))
}

export const ItemContext = React.createContext<ItemCtx>({ filesRoot: null, models: undefined, running: false })

export const ItemRow = React.memo(function ItemRow({
  item,
  live,
  last,
  onHide,
  onEdit,
  onFork,
}: {
  item: Item
  live: boolean
  /** The thread ends on this row, a failed turn: its card offers to resume. */
  last?: boolean
  /** Only for a message that got no answer: delete it, or (with onEdit) bring it back into the composer. */
  onHide?: (key: string, at: number) => void
  onEdit?: (key: string, at: number, seed: Seed) => void
  onFork?: (seed: Seed) => void
}) {
  const { sid } = React.useContext(ItemContext)
  const revert = useRevert(sid)
  switch (item.kind) {
    case 'user': {
      const { text, attachments, at, voice } = item.ev
      const heardText = item.heard?.text || ''
      const seed = () => ({ ...userSeed([text, heardText].filter(Boolean).join('\n\n')), attachments: heardText ? attachments : [...attachments, ...(voice || [])] })
      return (
        <UserMessage
          text={text}
          attachments={attachments}
          voice={voice}
          heard={item.heard}
          at={at}
          source={item.ev.source}
          from={item.ev.from}
          shown={item.ev.shown}
          mentions={item.ev.mentions}
          injected={item.ev.injected}
          onFork={onFork && (() => onFork(seed()))}
          onEdit={onHide && onEdit && (() => onEdit(item.key, at, seed()))}
          onDelete={onHide && (() => onHide(item.key, at))}
          onRevert={item.changed != null && sid ? () => void revert(item.changed!) : undefined}
        />
      )
    }
    case 'request':
      return <RequestRow text={item.ev.text} />
    case 'assistant':
      return <AssistantMessage text={item.ev.text} onFork={onFork} />
    case 'thinking':
      return <Thinking text={item.ev.text} />
    case 'tool':
      return <ToolCard item={item} live={live} />
    case 'init':
      return <InitRow model={item.ev.model} />
    case 'result':
      return item.cut ? (
        <CutCard cut={item.cut} last={!!last}>
          <ResultRow ev={item.ev} changes={item.changes} />
        </CutCard>
      ) : (
        <ResultRow ev={item.ev} changes={item.changes} />
      )
    case 'changes':
      return <LoneChanges ev={item.ev} />
    case 'note':
      return item.cut ? <CutCard cut={item.cut} last={!!last} /> : <NoteRow text={item.ev.text} level={item.ev.level} />
  }
})

/** A sent message split back into what the composer holds: its leading quotes, then the typed text. */
function userSeed(text: string): Omit<Seed, 'attachments'> {
  const { quotes, rest } = splitQuotes(text)
  return { text: (quotes.length ? rest : text).trim(), quotes }
}

/* ---------------------------------------------------------------- message menu */
/** What a message offers on right click (long press on Android). */
type MsgActions = {
  /** Copied as is. */
  text?: string
  /** "New session from this message": a new session of the same topic, its composer filled with the message. */
  onFork?: () => void
  /** The message got no answer (stopped): back into the composer, removed from the thread. */
  onEdit?: () => void
  /** The message got no answer (stopped): removed from the thread. */
  onDelete?: () => void
  /** Its turn changed git repositories: "Revert to before this message" (files only, Restore for 10 s). */
  onRevert?: () => void
  /** Offer the menu (Copy, Send to) even when there is nothing else in it. */
  copy?: boolean
}

/** Right click (a long press on a phone) on a message: a menu at the pointer (placed inside the row - the thread scroller is a containing block).
 *  A selection keeps the browser's own menu (copy it, or Quote from the pill), and so does a link. With Team on, "Send to" a friend. */
export function useMessageMenu({ text, onFork, onEdit, onDelete, onRevert, copy }: MsgActions) {
  const t = useT()
  const [menuAt, setMenuAt] = React.useState<{ x: number; y: number } | null>(null)
  const after = React.useRef<(() => void) | undefined>(undefined)
  const [sendTo, setSendTo] = React.useState<SendTarget | null>(null)
  const any = !!(onFork || onEdit || onDelete || onRevert || (copy && text?.trim()))
  const onContextMenu = any
    ? (e: React.MouseEvent<HTMLElement>) => {
        if ((e.target as Element).closest('a')) return
        const sel = window.getSelection()
        if (sel && !sel.isCollapsed && e.currentTarget.contains(sel.anchorNode)) return
        e.preventDefault()
        const r = e.currentTarget.getBoundingClientRect()
        setMenuAt({ x: e.clientX - r.left, y: e.clientY - r.top })
      }
    : undefined
  // iPhone Safari never fires contextmenu: a long press (still finger, no selection) opens the same menu. Android
  // fires both at about the same time, which only opens it once.
  const press = React.useRef<{ timer: number; x: number; y: number } | null>(null)
  const cancel = () => {
    if (press.current) window.clearTimeout(press.current.timer)
    press.current = null
  }
  React.useEffect(() => cancel, [])
  const touch = any
    ? {
        onTouchStart: (e: React.TouchEvent<HTMLElement>) => {
          cancel()
          const p = e.touches[0]
          if (e.touches.length !== 1 || !p || (e.target as Element).closest('a, button, input, textarea, video, audio')) return
          const el = e.currentTarget
          const at = { x: p.clientX, y: p.clientY }
          press.current = {
            ...at,
            timer: window.setTimeout(() => {
              press.current = null
              const sel = window.getSelection()
              if (sel && !sel.isCollapsed && el.contains(sel.anchorNode)) return
              const r = el.getBoundingClientRect()
              setMenuAt({ x: at.x - r.left, y: at.y - r.top })
            }, 550),
          }
        },
        onTouchMove: (e: React.TouchEvent<HTMLElement>) => {
          const p = e.touches[0]
          if (press.current && p && Math.hypot(p.clientX - press.current.x, p.clientY - press.current.y) > 8) cancel()
        },
        onTouchEnd: cancel,
        onTouchCancel: cancel,
      }
    : {}
  const menu = any ? (
    <DropdownMenu open={!!menuAt} onOpenChange={(o) => !o && setMenuAt(null)}>
      <DropdownMenuTrigger asChild>
        <span aria-hidden tabIndex={-1} className="pointer-events-none absolute size-0" style={{ left: menuAt?.x ?? 0, top: menuAt?.y ?? 0 }} />
      </DropdownMenuTrigger>
      {/* Edit / New session focus a composer: they run once the menu is gone (a closing menu takes the focus back),
          and closing never sends the focus to the invisible trigger. */}
      <DropdownMenuContent
        align="start"
        sideOffset={2}
        className="min-w-44"
        data-testid="msg-menu"
        onCloseAutoFocus={(e) => {
          e.preventDefault()
          const run = after.current
          after.current = undefined
          run?.()
        }}
      >
        {text && (
          <DropdownMenuItem onSelect={() => void navigator.clipboard?.writeText(text)}>
            <Copy /> {t('common.copy')}
          </DropdownMenuItem>
        )}
        {onFork && (
          <DropdownMenuItem onSelect={() => (after.current = onFork)} data-testid="msg-fork">
            <MessageSquarePlus /> {t('sessions.msg.newSession')}
          </DropdownMenuItem>
        )}
        {text?.trim() && <SendToSub onPick={(target) => (after.current = () => setSendTo(target))} />}
        {onEdit && (
          <DropdownMenuItem onSelect={() => (after.current = onEdit)} data-testid="msg-edit">
            <Pencil /> {t('sessions.msg.edit')}
          </DropdownMenuItem>
        )}
        {onRevert && (
          <DropdownMenuItem onSelect={onRevert} data-testid="msg-revert">
            <History /> {t('sessions.revert')}
          </DropdownMenuItem>
        )}
        {onDelete && (
          <DropdownMenuItem destructive onSelect={onDelete} data-testid="msg-delete">
            <Trash2 /> {t('sessions.msg.delete')}
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  ) : null
  return {
    onContextMenu,
    touch,
    menu: menu && (
      <>
        {menu}
        {sendTo && <SendToDialog target={sendTo} text={text || ''} onClose={() => setSendTo(null)} />}
      </>
    ),
  }
}

/** Grip of a whole message: drag it into another session to quote it there (mouse, several sessions side by side;
 *  the thread's delegated dragstart reads its text, see contentDrag.ts). */
function MessageGrip({ text, className }: { text: string; className?: string }) {
  return (
    <span
      draggable
      data-mx-drag
      ref={gripRef(text)}
      aria-hidden
      data-testid="msg-grip"
      className={cn(
        'hidden size-5 cursor-grab items-center justify-center rounded text-muted-foreground/60 opacity-0 transition-opacity group-hover/msg:opacity-100 hover:bg-accent hover:text-foreground active:cursor-grabbing group-data-multi/strip:pointer-fine:flex',
        className,
      )}
    >
      <GripVertical className="size-3.5" />
    </span>
  )
}

/* ---------------------------------------------------------------- user */
/** `onEdit` / `onDelete`: the message got no answer (stopped) - also shown as buttons on hover. */
export function UserMessage({
  text,
  attachments,
  at,
  source,
  from,
  shown,
  mentions,
  injected,
  pending,
  queued,
  voice,
  heard,
  onFork,
  onEdit,
  onDelete,
  onRevert,
}: {
  text: string
  attachments: string[]
  at?: number
  source?: string
  /** Not typed by the owner (another session, an agent, a job, Harness): a card with who sent it. */
  from?: MessageFrom
  /** The part of the text for the owner (the rest is instructions for Claude). */
  shown?: string
  /** The @ it names: drawn as chips (with the "/" command it starts with). */
  mentions?: SentMention[]
  /** Added to a running turn (Add to task). */
  injected?: boolean
  pending?: boolean
  queued?: boolean
  /** Voice message sent directly: its audio (paths; `true` for an optimistic one still uploading) and transcript. */
  voice?: string[] | true
  heard?: { text: string; error: string | null; stopped?: boolean }
} & Omit<MsgActions, 'text'>) {
  const t = useT()
  const lang = useLang()
  const { tz, path } = React.useContext(ItemContext)
  const card = messageFrom(from, source)
  // Quotes sent from the composer lead the message as Markdown blockquotes: shown as quote blocks (Copy keeps the raw text).
  const { quotes, rest } = React.useMemo(() => splitQuotes(text), [text])
  const { onContextMenu, touch, menu } = useMessageMenu({ text: [text, heard?.text].filter(Boolean).join('\n\n'), onFork, onEdit, onDelete, onRevert })
  return (
    <div className={cn('group/msg relative flex flex-col items-end gap-1.5 pl-8', pending && 'opacity-70')} onContextMenu={onContextMenu} {...touch}>
      {menu}
      {voice && <VoiceNote paths={voice === true ? [] : voice} heard={heard} pending={pending} />}
      {attachments.length > 0 && <AttachmentStrip paths={attachments} />}
      {text && card && <MessageCard from={card} text={text} shown={shown} />}
      {text && !card && (
        <div className="relative max-w-full rounded-2xl rounded-br-md bg-secondary px-3.5 py-2 text-[14px] leading-relaxed whitespace-pre-wrap text-secondary-foreground [overflow-wrap:anywhere]">
          <Sensitive block className="min-w-24 bg-transparent">
            {quotes.map((q, i) =>
              quotedFile(q) ? (
                <div key={i} className="mb-2 border-l-[3px] border-muted-foreground/30 pl-1.5 whitespace-normal last:mb-0">
                  <QuotedFile path={quotedFile(q)!} draggable className="pr-2 text-muted-foreground" />
                </div>
              ) : (
                <blockquote key={i} className="mb-2 border-l-[3px] border-muted-foreground/30 py-px pl-2.5 text-[13px] text-muted-foreground last:mb-0">
                  {q}
                </blockquote>
              ),
            )}
            <ChipText text={quotes.length ? rest : text} mentions={mentions} path={path} />
          </Sensitive>
        </div>
      )}
      <div className="flex h-4 items-center gap-1.5 text-[11px] text-muted-foreground">
        {pending ? (
          <span className="inline-flex items-center gap-1">
            <Spinner className="size-3" /> {queued ? t('sessions.queued') : t('sessions.sending')}
          </span>
        ) : (
          <>
            {(text || heard?.text) && <MessageGrip text={[text, heard?.text].filter(Boolean).join('\n\n')} />}
            {!card && source && source !== 'web' && <span className="rounded bg-muted px-1">{sourceLabel(source, t)}</span>}
            {injected && (
              <Tooltip content={t('sessions.msg.injectedTip')}>
                <span className="rounded bg-muted px-1">{t('sessions.msg.injected')}</span>
              </Tooltip>
            )}
            {at ? <time className="opacity-0 transition-opacity group-hover/msg:opacity-100 max-md:opacity-100 pointer-coarse:opacity-100">{fmtDate(at, lang, tz, { dateStyle: undefined, timeStyle: 'short' })}</time> : null}
            {onEdit && (
              <Tooltip content={t('sessions.msg.edit')}>
                <button
                  type="button"
                  onClick={onEdit}
                  aria-label={t('sessions.msg.edit')}
                  data-testid="msg-edit-button"
                  className="inline-flex size-6 items-center justify-center rounded-md opacity-0 transition-[opacity,color] group-hover/msg:opacity-100 hover:bg-accent hover:text-foreground focus-visible:opacity-100 max-md:opacity-100 pointer-coarse:opacity-100"
                >
                  <Pencil className="size-3.5" />
                </button>
              </Tooltip>
            )}
            {onDelete && (
              <Tooltip content={t('sessions.msg.delete')}>
                <button
                  type="button"
                  onClick={onDelete}
                  aria-label={t('sessions.msg.delete')}
                  className="inline-flex size-6 items-center justify-center rounded-md opacity-0 transition-[opacity,color] group-hover/msg:opacity-100 hover:bg-accent hover:text-destructive focus-visible:opacity-100 max-md:opacity-100 pointer-coarse:opacity-100"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </Tooltip>
            )}
          </>
        )}
      </div>
    </div>
  )
}

/** A voice message sent directly: the recording, then its transcript (what Claude got) - or "Transcribing…". */
export function VoiceNote({ paths, heard, pending }: { paths: string[]; heard?: { text: string; error: string | null; stopped?: boolean }; pending?: boolean }) {
  // One bubble like a typed message: a mic button (tap = listen to the recording, again = pause) and the transcript.
  const t = useT()
  const audio = React.useRef<HTMLAudioElement>(null)
  const [track, setTrack] = React.useState(0)
  const [playing, setPlaying] = React.useState(false)
  const src = paths[track] ? fileRawUrl(paths[track]) : undefined
  const toggle = () => {
    const a = audio.current
    if (!a) return
    if (a.paused) void a.play().catch(() => setPlaying(false))
    else a.pause()
  }
  return (
    <div className="flex max-w-full items-start gap-2.5 rounded-2xl rounded-br-md bg-secondary py-2 pr-3.5 pl-2 text-[14px] leading-relaxed text-secondary-foreground" data-testid="voice-note">
      <button
        type="button"
        onClick={toggle}
        disabled={!src}
        aria-label={playing ? t('voice.pause') : t('voice.listen')}
        data-mx-file={paths[0]}
        className={cn(
          'relative flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/15 max-md:size-10 pointer-coarse:size-10 text-primary transition-colors hover:bg-primary/25 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-60',
          playing && 'bg-primary text-primary-foreground hover:bg-primary/90',
        )}
      >
        {playing ? <Pause className="size-3.5 fill-current" /> : <Mic className="size-4" />}
      </button>
      {src && (
        <audio
          ref={audio}
          src={src}
          preload="none"
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => {
            setPlaying(false)
            if (track < paths.length - 1) {
              setTrack(track + 1)
              requestAnimationFrame(() => void audio.current?.play().catch(() => {}))
            } else setTrack(0)
          }}
        />
      )}
      <div className="min-w-0 self-center py-0.5">
        {pending ? (
          <span className="text-muted-foreground">{t('voice.message')}</span>
        ) : heard?.text ? (
          <Sensitive block className="min-w-0 bg-transparent">
            <span className="whitespace-pre-wrap [overflow-wrap:anywhere]">{heard.text}</span>
          </Sensitive>
        ) : heard ? (
          heard.stopped ? (
            <span className="text-muted-foreground">{t('voice.stoppedMsg')}</span>
          ) : (
            <span className="text-destructive">{heard.error ? t('voice.notTranscribed', { error: heard.error }) : t('voice.noSpeech')}</span>
          )
        ) : (
          <span className="inline-flex items-center gap-1.5 text-muted-foreground">
            <Spinner className="size-3" /> {t('voice.transcribingMsg')}
          </span>
        )}
      </div>
    </div>
  )
}

/** Label of a message that did not come from this browser (Telegram, a scheduled job). */
function sourceLabel(source: string, t: ReturnType<typeof useT>): string {
  if (source === 'telegram') return 'Telegram'
  if (source === 'cron') return t('sessions.source.cron')
  if (source === 'cli') return t('sessions.source.cli')
  if (source === 'github') return 'GitHub'
  return source
}

export function AttachmentStrip({ paths }: { paths: string[] }) {
  const open = useOpenPreview()
  const masked = usePresentation()
  return (
    <div className="flex max-w-full flex-wrap justify-end gap-1.5">
      {paths.map((p) =>
        isAudio(p) ? (
          <div key={p} data-mx-file={p} className="w-72 max-w-full">
            <MediaPlayer path={p} kind="audio" keepAlive onOpen={() => open(p)} className="gap-2 p-3" />
          </div>
        ) : isImage(p) || isVideo(p) ? (
          <button
            key={p}
            type="button"
            data-mx-file={p}
            draggable
            onClick={() => open(p)}
            onPointerEnter={() => prefetchMedia(p)}
            onFocus={() => prefetchMedia(p)}
            className="relative size-20 shrink-0 overflow-hidden rounded-lg border bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            aria-label={masked ? 'Attachment' : baseName(p)}
          >
            {masked ? null : <Thumb path={p} w={160} h={320} anim loading="lazy" className="size-full object-cover" />}
            {isGif(p) && <GifBadge />}
            {isVideo(p) && (
              <span className="absolute inset-0 flex items-center justify-center bg-black/25">
                <Play className="size-5 fill-white text-white" />
              </span>
            )}
          </button>
        ) : (
          <button
            key={p}
            type="button"
            data-mx-file={p}
            draggable
            onClick={() => open(p)}
            className="inline-flex h-8 max-w-56 items-center gap-1.5 rounded-lg border bg-card px-2 text-xs hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <Paperclip className="size-3.5 shrink-0 text-muted-foreground" />
            <span className="truncate">
              <Sensitive length={8}>{baseName(p)}</Sensitive>
            </span>
          </button>
        ),
      )}
    </div>
  )
}

function RequestRow({ text }: { text: string }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  return (
    <div className="flex flex-col items-center gap-1">
      <button type="button" onClick={() => setOpen((o) => !o)} className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] text-muted-foreground hover:bg-accent">
        <ScrollText className="size-3" /> {t('sessions.summaryRequested')}
        <ChevronRight className={cn('size-3 transition-transform', open && 'rotate-90')} />
      </button>
      {open && <p className="max-w-[90%] text-center text-xs text-muted-foreground">{text}</p>}
    </div>
  )
}

/* ---------------------------------------------------------------- assistant */
/** Links of a message: a path of the files root opens the in-app viewer (pass it to Markdown's `onLink`). */
export function useFileLink() {
  const open = useOpenPreview()
  const { scope } = React.useContext(ItemContext)
  return React.useCallback(
    (href: string) => {
      const p = href.startsWith(FILE_HREF) ? fileHrefPath(href) : null
      if (p === null || (scope && !scopeOf(p, scope))) return null
      return () => open(p)
    },
    [open, scope],
  )
}

/** The pictures, videos and sounds a message names (paths of the files root, see ItemContext): thumbnails that open
 *  the viewer and audio players, under the text. A file written after the message shows up once it exists (Thumb). */
export function MessageMedia({ text }: { text: string }) {
  const { filesRoot, scope } = React.useContext(ItemContext)
  const open = useOpenPreview()
  const roots = scope ?? filesRoot
  const media = React.useMemo(() => mediaPaths(text, roots), [text, roots])
  const audio = React.useMemo(() => audioPaths(text, roots), [text, roots])
  // a scope: each file is asked with the folder that holds it (the server refuses a link that leads out of it), and
  // nothing is prefetched on hover (the viewer's own URLs carry no `within`)
  const within = (p: string) => (scope ? scopeOf(p, scope) : null)
  const prefetch = (p: string) => !scope && prefetchMedia(p)
  return (
    <>
      {media.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {media.map((p) => (
            // a box of fixed shape: nothing in the thread moves when the picture arrives
            <button key={p} type="button" data-mx-file={p} draggable onClick={() => open(p)} onPointerEnter={() => prefetch(p)} onFocus={() => prefetch(p)} className="relative aspect-[4/3] h-28 overflow-hidden rounded-lg border bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
              <Thumb path={p} w={320} h={320} anim within={within(p)} alt={baseName(p)} loading="lazy" className="size-full object-cover" />
              {isGif(p) && <GifBadge />}
              {isVideo(p) && (
                <span className="absolute inset-0 flex items-center justify-center bg-black/25">
                  <Play className="size-6 fill-white text-white" />
                </span>
              )}
            </button>
          ))}
        </div>
      )}
      {audio.length > 0 && (
        <div className="mt-2 grid gap-2">
          {audio.map((p) => (
            <div key={p} data-mx-file={p} className="max-w-md">
              <MediaPlayer path={p} kind="audio" keepAlive within={within(p)} onOpen={() => open(p)} className="gap-2 p-3" />
            </div>
          ))}
        </div>
      )}
    </>
  )
}

const AssistantMessage = React.memo(function AssistantMessage({ text, onFork }: { text: string; onFork?: (seed: Seed) => void }) {
  const { filesRoot } = React.useContext(ItemContext)
  // "New session from this message": the reply goes along as a quote.
  const { onContextMenu, touch, menu } = useMessageMenu({ text, onFork: onFork && (() => onFork({ text: '', quotes: [text.trim()], attachments: [] })) })
  const md = React.useMemo(() => linkifyMarkdown(text, filesRoot), [text, filesRoot])
  const onLink = useFileLink()
  return (
    <div className="group/msg relative min-w-0" onContextMenu={onContextMenu} {...touch}>
      {menu}
      {/* in the thread's right padding, at the first line (the left one is under the resize handle of the column on the left) */}
      <MessageGrip text={text.trim()} className="absolute top-0.5 -right-4 w-4 max-md:hidden" />
      <Sensitive block placeholder={<MaskedLines />}>
        <Markdown onLink={onLink} className="mx-assistant">
          {md}
        </Markdown>
        <MessageMedia text={text} />
      </Sensitive>
    </div>
  )
})

/** On a GIF in the thread: it moves (up to 8 MB), or it is the still of a bigger one. */
function GifBadge() {
  const t = useT()
  return <span className="pointer-events-none absolute bottom-1 left-1 rounded bg-black/60 px-1 text-[10px] leading-4 font-semibold text-white">{t('media.gif')}</span>
}

const isGif = (p: string) => /\.gif$/i.test(p)

function MaskedLines() {
  const t = useT()
  return (
    <div className="grid gap-1.5" aria-label={t('presentation.hidden')}>
      <div className="h-3 w-11/12 rounded bg-muted" />
      <div className="h-3 w-9/12 rounded bg-muted" />
      <div className="h-3 w-10/12 rounded bg-muted" />
    </div>
  )
}

function Thinking({ text }: { text: string }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  return (
    <div className="min-w-0">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="relative inline-flex items-center gap-1.5 rounded-md py-0.5 pr-1.5 text-xs text-muted-foreground hover:text-foreground pointer-coarse:before:absolute pointer-coarse:before:inset-x-0 pointer-coarse:before:-inset-y-2.5 pointer-coarse:before:content-['']">
        <Brain className="size-3.5" /> {t('sessions.thinking')}
        <ChevronRight className={cn('size-3 transition-transform', open && 'rotate-90')} />
      </button>
      {open && (
        <div className="mt-1 border-l-2 pl-3 text-[13px] leading-relaxed whitespace-pre-wrap text-muted-foreground italic">
          <Sensitive block>{text}</Sensitive>
        </div>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- tools */
const OUT_PREVIEW = 1600
const FILE_TOOLS = new Set(['Read', 'Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'NotebookRead'])

/** Tool cards the user opened (by call id), outside the card: a 3rd read in a row turns the row into a ToolGroup and
 *  mounts its cards again - the open one, and the group around it, open again. */
const openCards = new Set<string>()
const OPEN_CARDS_MAX = 200

function useCardOpen(id: string): [boolean, React.Dispatch<React.SetStateAction<boolean>>] {
  const [open, setOpenState] = React.useState(() => openCards.has(id))
  const setOpen = React.useCallback((v: React.SetStateAction<boolean>) => setOpenState((o) => {
    const next = typeof v === 'function' ? v(o) : v
    openCards.delete(id)
    if (next) openCards.add(id)
    if (openCards.size > OPEN_CARDS_MAX) openCards.delete(openCards.values().next().value!)
    return next
  }), [id])
  return [open, setOpen]
}

function ToolCard({ item, live }: { item: Extract<Item, { kind: 'tool' }>; live: boolean }) {
  const t = useT()
  const { use, result } = item
  const [open, setOpen] = useCardOpen(use.id)
  const Icon = toolIcon(use.name)
  const { running } = React.useContext(ItemContext)
  // A sub-agent or a background command: its own state, not its tool result ("launched" comes back at once).
  const task = isShownTask(item.task) ? item.task : undefined
  const status = task ? taskStatus(task, running) : null
  const pendingNow = status ? status === 'running' : !result && live
  const err = status ? status === 'failed' : result?.is_error
  const root = React.useRef<HTMLDivElement>(null)
  useOpenTaskLine(task ? use.id : undefined, React.useCallback(() => setOpen(true), []), root)
  const input = (use.input && typeof use.input === 'object' ? use.input : {}) as Record<string, unknown>
  // A long Write comes clipped: the server sends the file's real line count.
  const writeLines = use.name === 'Write' ? (use.input_lines?.content ?? (typeof input.content === 'string' ? input.content.split('\n').length : 0)) : 0
  const diff = React.useMemo(() => (open || ['Edit', 'MultiEdit', 'Write'].includes(use.name) ? toolDiff(use.name, input, writeLines) : null), [open, use.name, input, writeLines])
  const stats = diff ? (use.name === 'Write' ? { add: writeLines, del: 0 } : diffStats(diff)) : null
  const authServer = authServerOf(use.name)
  const name = use.name.startsWith('mcp__') ? use.name.split('__').slice(2).join('__') || use.name : use.name
  const { topicDir = null, wsRoot = null } = React.useContext(ItemContext)
  const bases = { topicDir, wsRoot }
  const file = typeof input.file_path === 'string' ? input.file_path : typeof input.notebook_path === 'string' ? input.notebook_path : null
  // Full one-line description (server summaries are cut at 120 chars: rebuild file ones from the input).
  const full = file && FILE_TOOLS.has(use.name) ? file : use.summary.startsWith(use.name) ? use.summary.slice(use.name.length).replace(/^[:\s]+/, '') : use.summary
  const summary = file && FILE_TOOLS.has(use.name) ? relPath(file, bases) : relPaths(full, bases)
  // A plain-language title ("Runs the tests") and what it runs after it; '' = a tool it does not know (name + summary).
  const label = toolLabel(use.name, input, t, (p) => relPath(p, bases))
  const detail = label.title && label.detail ? (file && FILE_TOOLS.has(use.name) ? label.detail : relPaths(label.detail, bases)) : ''
  return (
    <div ref={root} className={cn('min-w-0 overflow-hidden rounded-lg border bg-card text-[13px]', err && 'border-destructive/40')}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex h-8 w-full min-w-0 items-center gap-2 px-2.5 text-left hover:bg-muted focus-visible:bg-accent focus-visible:outline-none max-md:h-10"
      >
        <Icon className={cn('size-3.5 shrink-0', err ? 'text-destructive' : 'text-muted-foreground')} />
        {label.title ? (
          <>
            <span className="max-w-[75%] shrink-0 truncate font-medium">
              <Sensitive length={14}>{label.title}</Sensitive>
            </span>
            {label.danger && (
              <span className="inline-flex shrink-0 items-center gap-1 rounded bg-primary/10 px-1.5 text-[11px] font-medium text-primary">
                <AlertTriangle className="size-3" /> {t('tl.danger')}
              </span>
            )}
            <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-muted-foreground/80">
              <Sensitive length={14}>{detail}</Sensitive>
            </span>
          </>
        ) : (
          <>
            <span className="shrink-0 font-medium">{name}</span>
            <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-muted-foreground">
              <Sensitive length={14}>{summary}</Sensitive>
            </span>
          </>
        )}
        {stats && (stats.add > 0 || stats.del > 0) && (
          <span className="shrink-0 font-mono text-[11px] tabular-nums">
            <span className="text-success">+{stats.add}</span> <span className="text-destructive">−{stats.del}</span>
          </span>
        )}
        {task && status && <TaskElapsed task={task} status={status} />}
        <span className="flex size-4 shrink-0 items-center justify-center">
          {status ? <TaskStatusIcon status={status} /> : pendingNow ? <Spinner className="size-3.5" /> : err ? <CircleAlert className="size-3.5 text-destructive" /> : result ? <Check className="size-3.5 text-success" /> : <X className="size-3.5 text-muted-foreground" />}
        </span>
        <ChevronRight className={cn('size-3.5 shrink-0 text-muted-foreground transition-transform', open && 'rotate-90')} />
      </button>
      {authServer && <McpAuthButton server={authServer} />}
      {open && (
        <div className="grid gap-2 border-t bg-sunken p-2.5">
          <Sensitive block>
            {task && status && <TaskDetails task={task} status={status} />}
            <ToolInput name={use.name} input={input} diff={diff} display={file ? relPath(file, bases) : null} />
            {task && (task.background || task.summary) ? null : result ? (
              <ToolOutput text={result.text} error={result.is_error} />
            ) : (
              <p className="text-xs text-muted-foreground">{pendingNow ? t('sessions.tool.running') : t('sessions.tool.noResult')}</p>
            )}
          </Sensitive>
        </div>
      )}
    </div>
  )
}

/** Read-only calls in a row (reads, searches, listings) worth one line: at least GROUP_MIN of them, none running a
 *  sub-agent or a background command. */
export const GROUP_MIN = 3
export function groupable(it: Item): boolean {
  if (it.kind !== 'tool' || isShownTask(it.task)) return false
  const input = (it.use.input && typeof it.use.input === 'object' ? it.use.input : {}) as Record<string, unknown>
  return toolKind(it.use.name, input) !== 'other'
}

/** "Explored 4 files · 2 searches": the read-only calls of a row as one line, their cards inside. */
export function ToolGroup({ items, live }: { items: Extract<Item, { kind: 'tool' }>[]; live: boolean[] }) {
  const t = useT()
  const [open, setOpen] = React.useState(() => items.some((it) => openCards.has(it.use.id)))
  const n = { read: 0, search: 0, list: 0, look: 0 }
  let pending = false
  let failed = false
  items.forEach((it, i) => {
    const input = (it.use.input && typeof it.use.input === 'object' ? it.use.input : {}) as Record<string, unknown>
    const k = toolKind(it.use.name, input)
    if (k !== 'other') n[k]++
    if (live[i]) pending = true
    if (it.result?.is_error) failed = true
  })
  const parts = [n.read && t('tl.group.files', { count: n.read }), n.search && t('tl.group.searches', { count: n.search }), n.list && t('tl.group.lists', { count: n.list }), n.look && t('tl.group.looks', { count: n.look })].filter(Boolean)
  return (
    <div className="min-w-0 overflow-hidden rounded-lg border bg-card text-[13px]">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex h-8 w-full min-w-0 items-center gap-2 px-2.5 text-left hover:bg-muted focus-visible:bg-accent focus-visible:outline-none max-md:h-10"
      >
        <FolderSearch className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="shrink-0 font-medium">{pending ? t('tl.group.exploring') : t('tl.group.explored')}</span>
        <span className="min-w-0 flex-1 truncate text-[12px] text-muted-foreground">{parts.join(' · ')}</span>
        <span className="flex size-4 shrink-0 items-center justify-center">
          {pending ? <Spinner className="size-3.5" /> : failed ? <CircleAlert className="size-3.5 text-muted-foreground" /> : <Check className="size-3.5 text-success" />}
        </span>
        <ChevronRight className={cn('size-3.5 shrink-0 text-muted-foreground transition-transform', open && 'rotate-90')} />
      </button>
      {open && (
        <div className="grid gap-1.5 border-t bg-sunken p-1.5">
          {items.map((it, i) => (
            <ToolCard key={it.key} item={it} live={live[i]} />
          ))}
        </div>
      )}
    </div>
  )
}

export function toolDiff(name: string, input: Record<string, unknown>, writeLines = 0): DiffLine[] | null {
  const s = (v: unknown) => (typeof v === 'string' ? v : '')
  if (name === 'Edit') return lineDiff(s(input.old_string), s(input.new_string))
  if (name === 'MultiEdit' && Array.isArray(input.edits)) {
    const out: DiffLine[] = []
    input.edits.forEach((e: { old_string?: string; new_string?: string }, i: number) => {
      if (i) out.push({ t: ' ', s: '⋯' })
      out.push(...lineDiff(s(e?.old_string), s(e?.new_string)))
    })
    return out
  }
  if (name === 'Write') {
    const lines = s(input.content).split('\n')
    const shown: DiffLine[] = lines.slice(0, 200).map((l) => ({ t: '+' as const, s: l }))
    const rest = Math.max(writeLines, lines.length) - shown.length
    if (rest > 0) shown.push({ t: ' ', s: `⋯ ${rest}` })
    return shown
  }
  return null
}

export function ToolInput({ name, input, diff, display }: { name: string; input: Record<string, unknown>; diff: DiffLine[] | null; display: string | null }) {
  const open = useOpenPreview()
  const file = typeof input.file_path === 'string' ? input.file_path : typeof input.notebook_path === 'string' ? input.notebook_path : null
  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2">
      {file && (
        <Tooltip content={<span className="max-w-[min(80vw,640px)] font-mono break-all">{file}</span>}>
          {/* A long path loses its folders first: the file name is what the user reads (and approves). */}
          <button type="button" data-mx-file={file} draggable onClick={() => open(file)} className="inline-flex max-w-full min-w-0 items-center justify-self-start font-mono text-xs text-primary hover:underline pointer-coarse:min-h-8">
            <FileText className="mr-1.5 size-3.5 shrink-0" />
            <PathText path={display || file} />
          </button>
        </Tooltip>
      )}
      {diff ? (
        <DiffView lines={diff} />
      ) : name === 'Bash' && typeof input.command === 'string' ? (
        <pre className="overflow-x-auto rounded-md bg-muted px-2.5 py-2 font-mono text-[12px] leading-relaxed whitespace-pre-wrap">
          <span className="text-muted-foreground select-none">$ </span>
          {input.command}
        </pre>
      ) : name === 'TodoWrite' && Array.isArray(input.todos) ? (
        <ul className="grid gap-1 text-[13px]">
          {(input.todos as { content?: string; status?: string }[]).map((td, i) => (
            <li key={i} className="flex items-start gap-2">
              <span className={cn('mt-1 size-3 shrink-0 rounded-sm border', td.status === 'completed' && 'border-success bg-success', td.status === 'in_progress' && 'border-primary bg-primary/30')} />
              <span className={cn(td.status === 'completed' && 'text-muted-foreground line-through')}>{td.content}</span>
            </li>
          ))}
        </ul>
      ) : !file || Object.keys(input).length > 1 ? (
        <pre className="max-h-64 overflow-auto rounded-md bg-muted px-2.5 py-2 font-mono text-[12px] leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]">{JSON.stringify(input, null, 2)}</pre>
      ) : null}
    </div>
  )
}

/** A path on one line that shrinks its folders first (down to "…"), then the middle of the file name: its end
 *  (extension included) always shows. */
function PathText({ path }: { path: string }) {
  const cut = path.lastIndexOf('/', path.length - 2) + 1
  const base = Array.from(path.slice(cut))
  const tail = base.length > 24 ? base.slice(-12).join('') : ''
  return (
    <>
      {cut > 0 && <span className="min-w-[2ch] shrink-[1000] truncate">{path.slice(0, cut)}</span>}
      <span className="min-w-0 truncate">{tail ? base.slice(0, -12).join('') : base.join('')}</span>
      {tail && <span className="shrink-0 whitespace-pre">{tail}</span>}
    </>
  )
}

/** Rows of a diff drawn at first: an edit of a file of thousands of lines would add as many rows to the page. */
const DIFF_ROWS = 400

export function DiffView({ lines }: { lines: DiffLine[] }) {
  const t = useT()
  const [all, setAll] = React.useState(false)
  const shown = all || lines.length <= DIFF_ROWS ? lines : lines.slice(0, DIFF_ROWS)
  return (
    <div className="max-h-96 overflow-auto rounded-md border bg-fill-1 font-mono text-[12px] leading-[1.55]">
      {shown.map((l, i) => (
        <div
          key={i}
          className={cn(
            // on a phone a line wraps in its column (about 34 characters fit at 360 px): no sideways scroll per line
            'flex min-w-max px-2 max-md:min-w-0',
            l.t === '+' && 'bg-success/12 text-foreground',
            l.t === '-' && 'bg-destructive/12 text-foreground',
            l.t === ' ' && l.s.startsWith('⋯') && 'text-muted-foreground',
          )}
        >
          <span className={cn('w-4 shrink-0 select-none', l.t === '+' ? 'text-success' : l.t === '-' ? 'text-destructive' : 'text-muted-foreground')}>{l.t === ' ' ? '' : l.t}</span>
          <span className="whitespace-pre max-md:min-w-0 max-md:whitespace-pre-wrap max-md:[overflow-wrap:anywhere]">{l.s || ' '}</span>
        </div>
      ))}
      {shown.length < lines.length && (
        <button type="button" onClick={() => setAll(true)} className="sticky left-0 px-2 py-1 font-sans text-xs text-primary hover:underline">
          {t('sessions.diff.more', { count: lines.length - shown.length })}
        </button>
      )}
    </div>
  )
}

function ToolOutput({ text, error }: { text: string; error: boolean }) {
  const t = useT()
  const [all, setAll] = React.useState(false)
  const long = text.length > OUT_PREVIEW
  const shown = all || !long ? text : text.slice(0, OUT_PREVIEW)
  if (!text.trim()) return <p className="text-xs text-muted-foreground">{t('sessions.tool.empty')}</p>
  return (
    <div className="group/msg relative grid gap-1">
      <MessageGrip text={text} className="absolute top-1 right-1 bg-muted" />
      <pre className={cn('max-h-80 overflow-auto rounded-md px-2.5 py-2 font-mono text-[12px] leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]', error ? 'bg-destructive/10 text-destructive' : 'bg-muted')}>
        {shown}
        {long && !all && '…'}
      </pre>
      {long && (
        <button type="button" onClick={() => setAll((a) => !a)} className="justify-self-start text-xs text-primary hover:underline">
          {all ? t('sessions.tool.showLess') : t('sessions.tool.showMore', { size: fmtTokens(text.length) })}
        </button>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- meta rows */
function InitRow({ model }: { model: string }) {
  const { models } = React.useContext(ItemContext)
  return (
    <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
      <span className="h-px flex-1 bg-border" />
      <span className="font-medium">{modelLabel(model, models)}</span>
      <span className="h-px flex-1 bg-border" />
    </div>
  )
}

function LoneChanges({ ev }: { ev: ChangesEvent }) {
  const { sid } = React.useContext(ItemContext)
  return sid ? (
    <div className="flex">
      <ChangesChip sid={sid} ev={ev} />
    </div>
  ) : null
}

function ResultRow({ ev, changes }: { ev: Extract<Item, { kind: 'result' }>['ev']; changes?: ChangesEvent }) {
  const t = useT()
  const lang = useLang()
  const { models, sid } = React.useContext(ItemContext)
  const { hidden } = useResultLine()
  const billed = useCostIsBilled()
  const show = (f: ResultField) => !hidden.includes(f)
  const u = ev.usage
  const ctx = (u?.input || 0) + (u?.cache_read || 0) + (u?.cache_write || 0)
  const share = fmtNumber(ctx > 0 ? (u?.cache_read || 0) / ctx : 0, lang, { style: 'percent', maximumFractionDigits: 1 })
  const tokensTip = t('sessions.tokensTip', { input: fmtNumber(u?.input || 0, lang), cacheRead: fmtNumber(u?.cache_read || 0, lang), cacheWrite: fmtNumber(u?.cache_write || 0, lang), output: fmtNumber(u?.output || 0, lang), share })
  const hasTokens = ctx > 0 || (u?.output || 0) > 0
  const part = (key: string, tip: React.ReactNode, body: React.ReactNode) => (
    <Tooltip key={key} content={<span className="block max-w-72 whitespace-normal">{tip}</span>}>
      <span tabIndex={0} className="rounded outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {body}
      </span>
    </Tooltip>
  )
  return (
    <div className="group/result flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground tabular-nums" data-testid="result-line">
      {ev.ok ? <Check className="size-3 text-success" /> : <AlertTriangle className="size-3 text-destructive" />}
      {[
        ev.model && show('model') ? part('m', t('sessions.result.modelTip'), modelLabel(ev.model, models)) : null,
        ev.duration_ms > 0 && show('duration') ? part('d', t('sessions.result.durationTip'), fmtMs(ev.duration_ms)) : null,
        ev.cost_usd > 0 && show('cost') ? part('c', costTip(t, billed), <Sensitive length={4}>{fmtCost(ev.cost_usd)}</Sensitive>) : null,
        hasTokens && show('tokens') ? part('t', tokensTip, `${fmtTokens(ctx)} → ${fmtTokens(u?.output || 0)}`) : null,
        hasTokens && show('cache') ? part('k', t('sessions.result.cacheTip', { share }), t('sessions.cacheShare', { share })) : null,
      ]
        .filter(Boolean)
        .flatMap((el, i) => (i ? [<span key={`s${i}`} aria-hidden>·</span>, el] : [el]))}
      {changes && sid && <ChangesChip sid={sid} ev={changes} />}
      <ResultLineMenu />
    </div>
  )
}

function NoteRow({ text, level }: { text: string; level: 'info' | 'warn' | 'error' }) {
  const Icon = level === 'error' ? CircleAlert : level === 'warn' ? AlertTriangle : Info
  return (
    <div
      role={level === 'error' ? 'alert' : undefined}
      className={cn(
        'flex items-start gap-2 rounded-md px-2.5 py-1.5 text-xs',
        level === 'error' ? 'bg-destructive/10 text-destructive' : level === 'warn' ? 'bg-warning/12 text-warning' : 'text-muted-foreground',
      )}
    >
      <Icon className="mt-0.5 size-3.5 shrink-0" />
      <span className="min-w-0 [overflow-wrap:anywhere] whitespace-pre-wrap">
        <Sensitive>{text}</Sensitive>
      </span>
    </div>
  )
}
