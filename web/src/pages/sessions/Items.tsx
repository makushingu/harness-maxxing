// Rendering of one thread item. Every row is memoised on the item object (items keep their identity
// when the log grows, see log.ts), so appending events only renders the new rows.
import * as React from 'react'
import { AlertTriangle, Brain, Check, ChevronRight, CircleAlert, Copy, FileText, Info, MessageSquarePlus, Mic, Paperclip, Pause, Pencil, Play, ScrollText, Trash2, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT, useLang } from '@/i18n'
import { fmtDate, fmtNumber } from '@/lib/format'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, Sensitive, Spinner, Tooltip, usePresentation } from '@/components/ui'
import { Markdown } from '@/components/ui/markdown'
import { filePreviewUrl, fileRawUrl, fileThumbUrl, knownFileStamp, prefetchImage, PREVIEW_W } from '@/lib/queries/files'
import { Thumb } from '@/features/files/Thumb'
import type { ClaudeModel, ResultField } from '@/lib/types'
import { costTip, ResultLineMenu, useCostIsBilled, useResultLine } from './resultLine'
import { isShownTask, taskStatus, type Item } from './log'
import { TaskDetails, TaskElapsed, TaskStatusIcon, useOpenTaskLine } from './Tasks'
import type { Seed } from './store'
import { useOpenPreview } from './FilePreview'
import { MediaPlayer } from '@/features/files/MediaPlayer'
import { QuotedFile } from './QuotedFile'
import { SendToDialog, SendToSub, type SendTarget } from '@/features/team/SendTo'
import { authServerOf, McpAuthButton } from '@/features/mcp/AuthButton'
import { audioPaths, baseName, diffStats, FILE_HREF, fmtCost, fmtMs, fmtTokens, isAudio, isImage, isVideo, lineDiff, linkifyMarkdown, mediaPaths, modelLabel, quotedFile, relPath, relPaths, splitQuotes, toolIcon, type DiffLine } from './util'

export type ItemCtx = {
  filesRoot: string | null
  models: ClaudeModel[] | undefined
  running: boolean
  tz?: string
  /** Absolute topic folder of the session and workspace root: tool cards show paths relative to them. */
  topicDir?: string | null
  wsRoot?: string | null
}
/** Hover / focus on a media thumbnail: start loading what the viewer will show (light preview, video poster). */
function prefetchMedia(p: string) {
  if (isImage(p)) prefetchImage(filePreviewUrl(p, PREVIEW_W, knownFileStamp(p)))
  else if (isVideo(p)) prefetchImage(fileThumbUrl(p, 1280, knownFileStamp(p)))
}

export const ItemContext = React.createContext<ItemCtx>({ filesRoot: null, models: undefined, running: false })

export const ItemRow = React.memo(function ItemRow({
  item,
  live,
  onHide,
  onEdit,
  onFork,
}: {
  item: Item
  live: boolean
  /** Only for a message that got no answer: delete it, or (with onEdit) bring it back into the composer. */
  onHide?: (key: string, at: number) => void
  onEdit?: (key: string, at: number, seed: Seed) => void
  onFork?: (seed: Seed) => void
}) {
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
          onFork={onFork && (() => onFork(seed()))}
          onEdit={onHide && onEdit && (() => onEdit(item.key, at, seed()))}
          onDelete={onHide && (() => onHide(item.key, at))}
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
      return <ResultRow ev={item.ev} />
    case 'note':
      return <NoteRow text={item.ev.text} level={item.ev.level} />
  }
})

/** A sent message split back into what the composer holds: its leading quotes, then the typed text. */
function userSeed(text: string): Omit<Seed, 'attachments'> {
  const { quotes, rest } = splitQuotes(text)
  return { text: (quotes.length ? rest : text).trim(), quotes }
}

/* ---------------------------------------------------------------- message menu */
/** What a message offers on right click (long press on Android). */
export type MsgActions = {
  /** Copied as is. */
  text?: string
  /** "New session from this message": a new session of the same topic, its composer filled with the message. */
  onFork?: () => void
  /** The message got no answer (stopped): back into the composer, removed from the thread. */
  onEdit?: () => void
  /** The message got no answer (stopped): removed from the thread. */
  onDelete?: () => void
}

/** Right click (a long press on a phone) on a message: a menu at the pointer (placed inside the row - the thread scroller is a containing block).
 *  A selection keeps the browser's own menu (copy it, or Quote from the pill), and so does a link. With Team on, "Send to" a friend. */
function useMessageMenu({ text, onFork, onEdit, onDelete }: MsgActions) {
  const t = useT()
  const [menuAt, setMenuAt] = React.useState<{ x: number; y: number } | null>(null)
  const after = React.useRef<(() => void) | undefined>(undefined)
  const [sendTo, setSendTo] = React.useState<SendTarget | null>(null)
  const any = !!(onFork || onEdit || onDelete)
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

/* ---------------------------------------------------------------- user */
/** `onEdit` / `onDelete`: the message got no answer (stopped) - also shown as buttons on hover. */
export function UserMessage({
  text,
  attachments,
  at,
  source,
  pending,
  queued,
  voice,
  heard,
  onFork,
  onEdit,
  onDelete,
}: {
  text: string
  attachments: string[]
  at?: number
  source?: string
  pending?: boolean
  queued?: boolean
  /** Voice message sent directly: its audio (paths; `true` for an optimistic one still uploading) and transcript. */
  voice?: string[] | true
  heard?: { text: string; error: string | null; stopped?: boolean }
} & Omit<MsgActions, 'text'>) {
  const t = useT()
  const lang = useLang()
  const { tz } = React.useContext(ItemContext)
  // Quotes sent from the composer lead the message as Markdown blockquotes: shown as quote blocks (Copy keeps the raw text).
  const { quotes, rest } = React.useMemo(() => splitQuotes(text), [text])
  const { onContextMenu, touch, menu } = useMessageMenu({ text: [text, heard?.text].filter(Boolean).join('\n\n'), onFork, onEdit, onDelete })
  return (
    <div className={cn('group/msg relative flex flex-col items-end gap-1.5 pl-8', pending && 'opacity-70')} onContextMenu={onContextMenu} {...touch}>
      {menu}
      {voice && <VoiceNote paths={voice === true ? [] : voice} heard={heard} pending={pending} />}
      {attachments.length > 0 && <AttachmentStrip paths={attachments} />}
      {text && (
        <div className="relative max-w-full rounded-2xl rounded-br-md bg-secondary px-3.5 py-2 text-[14px] leading-relaxed whitespace-pre-wrap text-secondary-foreground [overflow-wrap:anywhere]">
          <Sensitive block className="min-w-24 bg-transparent">
            {quotes.map((q, i) =>
              quotedFile(q) ? (
                <div key={i} className="mb-2 border-l-[3px] border-muted-foreground/30 pl-1.5 whitespace-normal last:mb-0">
                  <QuotedFile path={quotedFile(q)!} className="pr-2 text-muted-foreground" />
                </div>
              ) : (
                <blockquote key={i} className="mb-2 border-l-[3px] border-muted-foreground/30 py-px pl-2.5 text-[13px] text-muted-foreground last:mb-0">
                  {q}
                </blockquote>
              ),
            )}
            {quotes.length ? rest : text}
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
            {source && source !== 'web' && <span className="rounded bg-muted px-1">{sourceLabel(source, t)}</span>}
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
function VoiceNote({ paths, heard, pending }: { paths: string[]; heard?: { text: string; error: string | null; stopped?: boolean }; pending?: boolean }) {
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
            onClick={() => open(p)}
            onPointerEnter={() => prefetchMedia(p)}
            onFocus={() => prefetchMedia(p)}
            className="relative size-20 shrink-0 overflow-hidden rounded-lg border bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            aria-label={masked ? 'Attachment' : baseName(p)}
          >
            {masked ? null : <Thumb path={p} w={160} anim loading="lazy" className="size-full object-cover" />}
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
export const AssistantMessage = React.memo(function AssistantMessage({ text, onFork }: { text: string; onFork?: (seed: Seed) => void }) {
  const { filesRoot } = React.useContext(ItemContext)
  // "New session from this message": the reply goes along as a quote.
  const { onContextMenu, touch, menu } = useMessageMenu({ text, onFork: onFork && (() => onFork({ text: '', quotes: [text.trim()], attachments: [] })) })
  const open = useOpenPreview()
  const md = React.useMemo(() => linkifyMarkdown(text, filesRoot), [text, filesRoot])
  const media = React.useMemo(() => mediaPaths(text, filesRoot), [text, filesRoot])
  const audio = React.useMemo(() => audioPaths(text, filesRoot), [text, filesRoot])
  const onLink = React.useCallback((href: string) => (href.startsWith(FILE_HREF) ? () => open(decodeURIComponent(href.slice(FILE_HREF.length))) : null), [open])
  return (
    <div className="group/msg relative min-w-0" onContextMenu={onContextMenu} {...touch}>
      {menu}
      <Sensitive block placeholder={<MaskedLines />}>
        <Markdown onLink={onLink} className="mx-assistant">
          {md}
        </Markdown>
        {media.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {media.map((p) => (
              // a box of fixed shape: nothing in the thread moves when the picture arrives
              <button key={p} type="button" data-mx-file={p} onClick={() => open(p)} onPointerEnter={() => prefetchMedia(p)} onFocus={() => prefetchMedia(p)} className="relative aspect-[4/3] h-28 overflow-hidden rounded-lg border bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
                <Thumb path={p} w={320} anim alt={baseName(p)} loading="lazy" className="size-full object-cover" />
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
                <MediaPlayer path={p} kind="audio" keepAlive onOpen={() => open(p)} className="gap-2 p-3" />
              </div>
            ))}
          </div>
        )}
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
  return (
    <div className="grid gap-1.5" aria-label="Hidden (presentation mode)">
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

function ToolCard({ item, live }: { item: Extract<Item, { kind: 'tool' }>; live: boolean }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const { use, result } = item
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
  const diff = React.useMemo(() => (open || ['Edit', 'MultiEdit', 'Write'].includes(use.name) ? toolDiff(use.name, input) : null), [open, use.name, input])
  const stats = diff ? diffStats(diff) : null
  const authServer = authServerOf(use.name)
  const name = use.name.startsWith('mcp__') ? use.name.split('__').slice(2).join('__') || use.name : use.name
  const { topicDir = null, wsRoot = null } = React.useContext(ItemContext)
  const bases = { topicDir, wsRoot }
  const file = typeof input.file_path === 'string' ? input.file_path : typeof input.notebook_path === 'string' ? input.notebook_path : null
  // Full one-line description (server summaries are cut at 120 chars: rebuild file ones from the input).
  const full = file && FILE_TOOLS.has(use.name) ? file : use.summary.startsWith(use.name) ? use.summary.slice(use.name.length).replace(/^[:\s]+/, '') : use.summary
  const summary = file && FILE_TOOLS.has(use.name) ? relPath(file, bases) : relPaths(full, bases)
  return (
    <div ref={root} className={cn('min-w-0 overflow-hidden rounded-lg border bg-card/60 text-[13px]', err && 'border-destructive/40')}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex h-8 w-full min-w-0 items-center gap-2 px-2.5 text-left hover:bg-accent/60 focus-visible:bg-accent focus-visible:outline-none max-md:h-10"
      >
        <Icon className={cn('size-3.5 shrink-0', err ? 'text-destructive' : 'text-muted-foreground')} />
        <span className="shrink-0 font-medium">{name}</span>
        <Tooltip content={summary !== full ? <Sensitive length={20}><span className="max-w-[min(80vw,640px)] font-mono break-all">{full}</span></Sensitive> : null}>
          <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-muted-foreground">
            <Sensitive length={14}>{summary}</Sensitive>
          </span>
        </Tooltip>
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
        <div className="grid gap-2 border-t bg-background/40 p-2.5">
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

function toolDiff(name: string, input: Record<string, unknown>): DiffLine[] | null {
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
    if (lines.length > 200) shown.push({ t: ' ', s: `⋯ ${lines.length - 200}` })
    return shown
  }
  return null
}

function ToolInput({ name, input, diff, display }: { name: string; input: Record<string, unknown>; diff: DiffLine[] | null; display: string | null }) {
  const open = useOpenPreview()
  const file = typeof input.file_path === 'string' ? input.file_path : typeof input.notebook_path === 'string' ? input.notebook_path : null
  return (
    <div className="grid min-w-0 gap-2">
      {file && (
        <Tooltip content={display && display !== file ? <span className="max-w-[min(80vw,640px)] font-mono break-all">{file}</span> : null}>
          <button type="button" data-mx-file={file} onClick={() => open(file)} className="inline-flex min-w-0 items-center gap-1.5 justify-self-start font-mono text-xs text-primary hover:underline">
            <FileText className="size-3.5 shrink-0" />
            <span className="truncate">{display || file}</span>
          </button>
        </Tooltip>
      )}
      {diff ? (
        <DiffView lines={diff} />
      ) : name === 'Bash' && typeof input.command === 'string' ? (
        <pre className="overflow-x-auto rounded-md bg-muted/60 px-2.5 py-2 font-mono text-[12px] leading-relaxed whitespace-pre-wrap">
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
        <pre className="max-h-64 overflow-auto rounded-md bg-muted/60 px-2.5 py-2 font-mono text-[12px] leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]">{JSON.stringify(input, null, 2)}</pre>
      ) : null}
    </div>
  )
}

/** Rows of a diff drawn at first: an edit of a file of thousands of lines would add as many rows to the page. */
const DIFF_ROWS = 400

export function DiffView({ lines }: { lines: DiffLine[] }) {
  const t = useT()
  const [all, setAll] = React.useState(false)
  const shown = all || lines.length <= DIFF_ROWS ? lines : lines.slice(0, DIFF_ROWS)
  return (
    <div className="max-h-96 overflow-auto rounded-md border bg-muted/30 font-mono text-[12px] leading-[1.55]">
      {shown.map((l, i) => (
        <div
          key={i}
          className={cn(
            'flex min-w-max px-2',
            l.t === '+' && 'bg-success/12 text-foreground',
            l.t === '-' && 'bg-destructive/12 text-foreground',
            l.t === ' ' && l.s.startsWith('⋯') && 'text-muted-foreground',
          )}
        >
          <span className={cn('w-4 shrink-0 select-none', l.t === '+' ? 'text-success' : l.t === '-' ? 'text-destructive' : 'text-muted-foreground')}>{l.t === ' ' ? '' : l.t}</span>
          <span className="whitespace-pre">{l.s || ' '}</span>
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
    <div className="grid gap-1">
      <pre className={cn('max-h-80 overflow-auto rounded-md px-2.5 py-2 font-mono text-[12px] leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]', error ? 'bg-destructive/10 text-destructive' : 'bg-muted/60')}>
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

function ResultRow({ ev }: { ev: Extract<Item, { kind: 'result' }>['ev'] }) {
  const t = useT()
  const lang = useLang()
  const { models } = React.useContext(ItemContext)
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
