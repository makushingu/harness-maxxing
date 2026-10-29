// Left pane: directory listing (list / grid with thumbnails), filter, sort, hidden files, drag & drop upload.
import * as React from 'react'
import {
  Clock,
  ArrowUpDown,
  Check,
  CheckCircle2,
  Copy,
  Download,
  FolderDown,
  FolderOpen,
  FolderUp,
  LayoutGrid,
  List,
  MoreHorizontal,
  Pencil,
  Search,
  Trash2,
  Upload,
  X,
  XCircle,
} from 'lucide-react'
import type { FileEntry, FileList } from '@/lib/types'
import { fileThumbUrl } from '@/lib/queries/files'
import { errorMessage } from '@/lib/api'
import { fmtBytes, fmtDate, fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { useSettings } from '@/lib/queries/settings'
import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  Input,
  ProgressBar,
  Sensitive,
  Skeleton,
  Spinner,
  Tooltip,
  usePresentation,
} from '@/components/ui'
import { hasThumb, iconFor, iconTone } from '@/features/files/kinds'
import { sortEntries, useFilePrefs, type SortKey, type UploadItem } from './state'
import { downloadProps, useDownloadZip } from '@/features/files/download'

export type EntryActions = {
  open: (e: FileEntry) => void
  rename: (e: FileEntry) => void
  remove: (e: FileEntry) => void
  copyPath: (e: FileEntry) => void
  /** Drag & drop: move a file/folder into a folder (same window). */
  moveTo: (from: string, dir: string) => void
  /** Drag & drop: files from the computer dropped on a folder row. */
  uploadTo: (files: File[], dir: string) => void
}

/* ------------------------------------------------------------------ drag & drop
 * Entries are draggable (HTML5 DnD, desktop). Drop on a folder row / tile / breadcrumb = move there;
 * files from the computer dropped on a folder = uploaded into it, anywhere else = into this folder. */
export const MX_PATH_TYPE = 'application/x-maxxing-path'
/** Path being dragged in this window (dataTransfer data cannot be read during dragover). */
export const fileDrag: { path: string | null } = { path: null }
export const hasPathDrag = (dt: DataTransfer) => Array.from(dt.types).includes(MX_PATH_TYPE)
const hasFiles = (dt: DataTransfer) => Array.from(dt.types).includes('Files')
/** Rows rendered per step in a big folder (see `shown`). */
const RENDER_STEP = 200
/** Can `dir` receive the dragged entry? (not itself, not one of its sub-folders, not where it already is) */
export function canDropInto(dir: string): boolean {
  const p = fileDrag.path
  if (!p) return true
  const parent = p.slice(0, p.lastIndexOf('/')) || '/'
  return dir !== p && !dir.startsWith(p + '/') && dir !== parent
}
function dragProps(e: FileEntry) {
  return {
    draggable: true,
    onDragStart: (ev: React.DragEvent) => {
      fileDrag.path = e.path
      ev.dataTransfer.setData(MX_PATH_TYPE, e.path)
      ev.dataTransfer.setData('text/plain', e.path)
      ev.dataTransfer.effectAllowed = 'move'
    },
    onDragEnd: () => {
      fileDrag.path = null
    },
    ...(e.type === 'dir' ? { 'data-drop-dir': e.path } : {}),
  }
}

export function Listing({
  list,
  loading,
  error,
  onRetry,
  selected,
  actions,
  onUpload,
  onPickFiles,
  uploads,
  onClearUploads,
  onCancelUploads,
  onUp,
  className,
}: {
  list: FileList | undefined
  loading: boolean
  error: unknown
  onRetry: () => void
  selected: string | null
  actions: EntryActions
  onUpload: (files: File[]) => void
  onPickFiles: () => void
  uploads: UploadItem[]
  onClearUploads: () => void
  onCancelUploads: () => void
  onUp?: () => void
  className?: string
}) {
  const t = useT()
  const prefs = useFilePrefs()
  const [filter, setFilter] = React.useState('')
  const [drag, setDrag] = React.useState(false)
  const [dropDir, setDropDir] = React.useState<string | null>(null)
  const dragDepth = React.useRef(0)
  const scroller = React.useRef<HTMLDivElement>(null)

  // Reset the filter and scroll when the folder changes.
  const dirPath = list?.path
  React.useEffect(() => {
    setFilter('')
    scroller.current?.scrollTo({ top: 0 })
  }, [dirPath])

  const entries = React.useMemo(() => (list ? sortEntries(list.entries, { ...prefs, filter }) : []), [list, prefs, filter])
  // Big folders render progressively: the first rows at once, the next ones as the end of the list comes
  // near (1 500 rows with their menus took seconds to mount). The selected entry is always rendered.
  const [shown, setShown] = React.useState(RENDER_STEP)
  const [shownFor, setShownFor] = React.useState({ dirPath, filter })
  if (shownFor.dirPath !== dirPath || shownFor.filter !== filter) {
    setShownFor({ dirPath, filter })
    setShown(RENDER_STEP)
  }
  const selectedIdx = selected ? entries.findIndex((e) => e.path === selected) : -1
  const limit = Math.max(shown, selectedIdx + RENDER_STEP / 4)
  const rendered = entries.length > limit ? entries.slice(0, limit) : entries
  const more = rendered.length < entries.length
  const sentinel = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    const el = sentinel.current
    if (!more || !el) return
    const io = new IntersectionObserver((xs) => xs.some((x) => x.isIntersecting) && setShown((n) => n + RENDER_STEP), {
      root: scroller.current,
      rootMargin: '800px 0px',
    })
    io.observe(el)
    return () => io.disconnect()
  }, [more, rendered.length])
  const hiddenCount = list ? list.entries.filter((e) => e.name.startsWith('.')).length : 0

  // Keep the selected file visible (deep link, prev/next in the image viewer).
  React.useEffect(() => {
    if (!selected) return
    const el = scroller.current?.querySelector<HTMLElement>(`[data-path="${CSS.escape(selected)}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  }, [selected, entries])

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    const rows = Array.from(scroller.current?.querySelectorAll<HTMLElement>('[data-row]') || [])
    const i = rows.indexOf(document.activeElement as HTMLElement)
    if (i < 0) return
    const grid = prefs.view === 'grid'
    if (!grid && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
      if (e.key === 'ArrowLeft' && onUp) {
        e.preventDefault()
        onUp()
      }
      return
    }
    const cols = grid ? Math.max(1, Math.round((scroller.current!.clientWidth - 16) / (rows[0].offsetWidth + 8))) : 1
    const d = e.key === 'ArrowDown' ? cols : e.key === 'ArrowUp' ? -cols : e.key === 'ArrowRight' ? 1 : -1
    const n = rows[Math.max(0, Math.min(rows.length - 1, i + d))]
    if (n) {
      e.preventDefault()
      n.focus()
    }
  }

  const sortLabel: Record<SortKey, string> = { name: t('files.sortName'), mtime: t('files.sortDate'), size: t('files.sortSize') }

  return (
    <div
      className={cn('relative flex min-h-0 flex-col', className)}
      onDragEnter={(e) => {
        if (!hasFiles(e.dataTransfer) && !hasPathDrag(e.dataTransfer)) return
        e.preventDefault()
        dragDepth.current++
        if (hasFiles(e.dataTransfer)) setDrag(true)
      }}
      onDragOver={(e) => {
        const files = hasFiles(e.dataTransfer)
        if (!files && !hasPathDrag(e.dataTransfer)) return
        const dir = (e.target as HTMLElement).closest<HTMLElement>('[data-drop-dir]')?.dataset.dropDir ?? null
        const target = dir && (files || canDropInto(dir)) ? dir : null
        if (target !== dropDir) setDropDir(target)
        if (!files && !target) return // an entry over a plain file: no drop here
        e.preventDefault()
        e.dataTransfer.dropEffect = files ? 'copy' : 'move'
      }}
      onDragLeave={() => {
        dragDepth.current = Math.max(0, dragDepth.current - 1)
        if (!dragDepth.current) {
          setDrag(false)
          setDropDir(null)
        }
      }}
      onDrop={(e) => {
        const target = dropDir
        dragDepth.current = 0
        setDrag(false)
        setDropDir(null)
        if (hasPathDrag(e.dataTransfer)) {
          const from = e.dataTransfer.getData(MX_PATH_TYPE)
          fileDrag.path = null
          if (!target || !from) return
          e.preventDefault()
          actions.moveTo(from, target)
          return
        }
        if (!hasFiles(e.dataTransfer)) return
        e.preventDefault()
        // Folders dropped show up as 0-byte entries without a type: skip them.
        const files = Array.from(e.dataTransfer.files).filter((f) => f.type || f.size > 0)
        if (!files.length) return
        if (target) actions.uploadTo(files, target)
        else onUpload(files)
      }}
      data-testid="files-listing"
    >
      {/* toolbar */}
      <div className="flex shrink-0 items-center gap-1.5 border-b px-3 py-2">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setFilter('')
              if (e.key === 'ArrowDown') {
                e.preventDefault()
                scroller.current?.querySelector<HTMLElement>('[data-row]')?.focus()
              }
            }}
            placeholder={t('files.filter')}
            aria-label={t('files.filter')}
            className="h-8 pl-8 max-md:h-10"
            type="search"
          />
        </div>
        <Tooltip content={prefs.view === 'list' ? t('files.gridView') : t('files.listView')}>
          <Button variant="ghost" size="icon-sm" onClick={() => prefs.set({ view: prefs.view === 'list' ? 'grid' : 'list' })} aria-label={prefs.view === 'list' ? t('files.gridView') : t('files.listView')}>
            {prefs.view === 'list' ? <LayoutGrid /> : <List />}
          </Button>
        </Tooltip>
        <DropdownMenu>
          <Tooltip content={t('files.sortAndView')}>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label={t('files.sortAndView')}>
                <ArrowUpDown />
              </Button>
            </DropdownMenuTrigger>
          </Tooltip>
          <DropdownMenuContent align="end" className="w-52">
            <DropdownMenuLabel>{t('files.sortBy')}</DropdownMenuLabel>
            <DropdownMenuRadioGroup value={prefs.sort} onValueChange={(v) => prefs.set({ sort: v as SortKey })}>
              {(['name', 'mtime', 'size'] as const).map((k) => (
                <DropdownMenuRadioItem key={k} value={k} onSelect={(e) => e.preventDefault()}>
                  {sortLabel[k]}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
            <DropdownMenuSeparator />
            <DropdownMenuCheckboxItem checked={prefs.desc} onCheckedChange={(v) => prefs.set({ desc: !!v })} onSelect={(e) => e.preventDefault()}>
              {t('files.descending')}
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={prefs.hidden} onCheckedChange={(v) => prefs.set({ hidden: !!v })} onSelect={(e) => e.preventDefault()}>
              {t('files.showHidden')}
            </DropdownMenuCheckboxItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* body */}
      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto overscroll-contain" onKeyDown={onKeyDown}>
        {loading && !list ? (
          <ListingSkeleton grid={prefs.view === 'grid'} />
        ) : error && !list ? (
          <EmptyState
            compact
            tone="error"
            icon={XCircle}
            title={t('files.listError')}
            description={errorMessage(error)}
            action={
              <Button variant="secondary" size="sm" onClick={onRetry}>
                {t('common.retry')}
              </Button>
            }
          />
        ) : list && !entries.length ? (
          filter ? (
            <EmptyState compact icon={Search} title={t('common.noResults')} description={t('files.noMatch')} />
          ) : (
            <EmptyState
              compact
              icon={FolderOpen}
              title={t('files.emptyFolder')}
              description={hiddenCount && !prefs.hidden ? t('files.hiddenOnly', { count: hiddenCount }) : t('files.emptyFolderDesc')}
              action={
                <Button variant="secondary" size="sm" onClick={onPickFiles}>
                  <Upload />
                  {t('files.upload')}
                </Button>
              }
            />
          )
        ) : prefs.view === 'grid' ? (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(108px,1fr))] gap-2 p-2" role="list" aria-label={t('files.contents')}>
            {rendered.map((e) => (
              <GridItem key={e.path} entry={e} selected={selected === e.path} dropTarget={dropDir === e.path} actions={actions} />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-[minmax(0,1fr)] p-1.5" role="list" aria-label={t('files.contents')}>
            {rendered.map((e) => (
              <Row key={e.path} entry={e} selected={selected === e.path} dropTarget={dropDir === e.path} actions={actions} />
            ))}
          </div>
        )}
        {more && <div ref={sentinel} aria-hidden className="h-px" />}
      </div>

      {/* footer: count */}
      {list && (
        <div className="flex h-8 shrink-0 items-center justify-between gap-2 border-t px-3 text-xs text-muted-foreground tabular-nums">
          <span>{t('common.items', { count: entries.length })}</span>
          {hiddenCount > 0 && !prefs.hidden && (
            <button type="button" className="rounded hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none" onClick={() => prefs.set({ hidden: true })}>
              {t('files.hiddenCount', { count: hiddenCount })}
            </button>
          )}
        </div>
      )}

      {uploads.length > 0 && <UploadPanel items={uploads} onClear={onClearUploads} onCancel={onCancelUploads} />}

      {drag && !dropDir && (
        <div className="pointer-events-none absolute inset-1.5 z-10 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-primary bg-background/95 text-center animate-in">
          <FolderUp className="size-7 text-primary" />
          <p className="text-sm font-medium">{t('files.dropHere')}</p>
          <p className="max-w-60 truncate px-4 text-[13px] text-muted-foreground">
            <Sensitive length={10}>{list?.path}</Sensitive>
          </p>
        </div>
      )}
    </div>
  )
}

function ListingSkeleton({ grid }: { grid: boolean }) {
  if (grid)
    return (
      <div className="grid grid-cols-[repeat(auto-fill,minmax(108px,1fr))] gap-2 p-2" aria-hidden>
        {Array.from({ length: 12 }, (_, i) => (
          <div key={i} className="grid gap-2 rounded-lg p-1.5">
            <Skeleton className="aspect-square w-full rounded-md" />
            <Skeleton className="mx-auto h-3 w-3/4" />
          </div>
        ))}
      </div>
    )
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] p-1.5" aria-hidden>
      {Array.from({ length: 12 }, (_, i) => (
        <div key={i} className="flex h-[var(--row-h,40px)] items-center gap-3 px-2.5">
          <Skeleton className="size-4 rounded" />
          <Skeleton className="h-3" style={{ width: `${40 + ((i * 37) % 45)}%` }} />
          <Skeleton className="ml-auto h-3 w-10" />
        </div>
      ))}
    </div>
  )
}

function EntryMenu({ entry, actions, className }: { entry: FileEntry; actions: EntryActions; className?: string }) {
  const t = useT()
  const downloadZip = useDownloadZip()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={t('common.more')}
          className={cn(
            'inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-background hover:text-foreground focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:opacity-100 max-md:size-10 max-md:opacity-100 pointer-coarse:size-10 pointer-coarse:opacity-100',
            className,
          )}
          onClick={(e) => e.stopPropagation()}
        >
          <MoreHorizontal className="size-4" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
        <DropdownMenuItem onSelect={() => actions.open(entry)}>
          <FolderOpen />
          {t('files.open')}
        </DropdownMenuItem>
        {entry.type === 'file' ? (
          <DropdownMenuItem asChild>
            <a {...downloadProps(entry.path, { version: entry.mtime, size: entry.size })}>
              <Download />
              {t('files.download')}
            </a>
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem onSelect={() => downloadZip(entry.path)} data-testid="entry-zip">
            <FolderDown />
            {t('files.downloadZip')}
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={() => actions.copyPath(entry)}>
          <Copy />
          {t('files.copyPath')}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => actions.rename(entry)}>
          <Pencil />
          {t('files.renameMove')}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem destructive onSelect={() => actions.remove(entry)}>
          <Trash2 />
          {t('common.delete')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function useEntryMeta(e: FileEntry) {
  const lang = useLang()
  const { data: settings } = useSettings()
  return {
    size: e.type === 'dir' ? '' : fmtBytes(e.size),
    rel: fmtRelative(e.mtime, lang),
    full: fmtDate(e.mtime, lang, settings?.timezone),
  }
}

function Row({ entry: e, selected, dropTarget, actions }: { entry: FileEntry; selected: boolean; dropTarget: boolean; actions: EntryActions }) {
  const Icon = iconFor(e.type, e.name)
  const meta = useEntryMeta(e)
  return (
    <div
      role="listitem"
      {...dragProps(e)}
      className={cn(
        'mx-cv group relative flex h-[var(--row-h,40px)] items-center rounded-md transition-colors max-md:h-12',
        selected ? 'bg-accent text-accent-foreground' : 'hover:bg-accent/60',
        dropTarget && 'bg-primary/10 ring-2 ring-primary ring-inset',
      )}
    >
      <button
        type="button"
        data-row
        data-path={e.path}
        aria-current={selected ? 'true' : undefined}
        onClick={() => actions.open(e)}
        className="flex h-full min-w-0 flex-1 items-center gap-2.5 rounded-md pr-1 pl-2.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
      >
        <Icon className={cn('size-4 shrink-0', iconTone(e.type))} />
        <span className={cn('min-w-0 flex-1 truncate text-sm', e.name.startsWith('.') && 'text-muted-foreground')}>
          <Sensitive length={Math.min(14, Math.max(4, e.name.length))}>{e.name}</Sensitive>
        </span>
        <span className="shrink-0 text-xs text-muted-foreground tabular-nums group-hover:hidden group-focus-within:hidden max-md:hidden" title={meta.full}>
          {meta.size || meta.rel}
        </span>
        <span className="hidden shrink-0 text-xs text-muted-foreground tabular-nums max-md:inline">{meta.size || meta.rel}</span>
      </button>
      <EntryMenu entry={e} actions={actions} className="mr-1 hidden group-focus-within:inline-flex group-hover:inline-flex data-[state=open]:inline-flex max-md:inline-flex" />
    </div>
  )
}

function GridItem({ entry: e, selected, dropTarget, actions }: { entry: FileEntry; selected: boolean; dropTarget: boolean; actions: EntryActions }) {
  const Icon = iconFor(e.type, e.name)
  const presentation = usePresentation()
  const [thumbOk, setThumbOk] = React.useState(true)
  const thumb = e.type === 'file' && hasThumb(e.name) && thumbOk && !presentation
  return (
    <div role="listitem" {...dragProps(e)} className={cn('group relative rounded-lg', dropTarget && 'bg-primary/10 ring-2 ring-primary')}>
      <button
        type="button"
        data-row
        data-path={e.path}
        aria-current={selected ? 'true' : undefined}
        onClick={() => actions.open(e)}
        className={cn(
          'grid w-full gap-1.5 rounded-lg p-1.5 text-center outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring',
          selected ? 'bg-accent' : 'hover:bg-accent/60',
        )}
      >
        <div className="relative flex aspect-square w-full items-center justify-center overflow-hidden rounded-md border bg-muted/40">
          {thumb ? (
            <img src={fileThumbUrl(e.path, 240, e.mtime)} alt="" loading="lazy" decoding="async" onError={() => setThumbOk(false)} className="size-full object-cover" />
          ) : (
            <Icon className={cn('size-8', iconTone(e.type))} strokeWidth={1.4} />
          )}
        </div>
        <span className="line-clamp-2 min-h-[2lh] text-xs leading-snug break-all">
          <Sensitive length={8}>{e.name}</Sensitive>
        </span>
      </button>
      <EntryMenu entry={e} actions={actions} className="absolute top-2.5 right-2.5 hidden bg-popover shadow-xs group-focus-within:inline-flex group-hover:inline-flex data-[state=open]:inline-flex max-md:inline-flex" />
    </div>
  )
}

function UploadPanel({ items, onClear, onCancel }: { items: UploadItem[]; onClear: () => void; onCancel: () => void }) {
  const t = useT()
  const active = items.some((i) => i.status === 'queued' || i.status === 'uploading')
  const done = items.filter((i) => i.status === 'done').length
  const total = items.reduce((s, i) => s + i.size, 0)
  const loaded = items.reduce((s, i) => s + (i.status === 'done' ? i.size : i.loaded), 0)
  return (
    <div className="shrink-0 border-t bg-card" aria-live="polite" data-testid="upload-panel">
      <div className="flex items-center gap-2 px-3 pt-2.5 pb-1.5">
        {active ? <Spinner className="size-3.5 text-muted-foreground" /> : <CheckCircle2 className="size-3.5 text-success" />}
        <span className="flex-1 text-[13px] font-medium">{active ? t('files.uploading', { done, count: items.length }) : t('files.uploaded', { count: done })}</span>
        {active ? (
          <Button variant="ghost" size="sm" className="h-7" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
        ) : (
          <Button variant="ghost" size="icon-sm" className="size-7" onClick={onClear} aria-label={t('files.dismiss')}>
            <X />
          </Button>
        )}
      </div>
      {active && <ProgressBar value={loaded} max={total || 1} className="mx-3 mb-2 w-auto" label={t('files.uploadProgress')} />}
      <ul className="max-h-36 overflow-y-auto px-3 pb-2.5">
        {items.map((i) => (
          <li key={i.id} className="flex items-center gap-2 py-0.5 text-xs">
            {i.status === 'done' ? (
              <Check className="size-3.5 shrink-0 text-success" />
            ) : i.status === 'error' ? (
              <XCircle className="size-3.5 shrink-0 text-destructive" />
            ) : i.status === 'uploading' ? (
              <Spinner className="size-3.5 shrink-0 text-muted-foreground" />
            ) : (
              <Clock className="size-3.5 shrink-0 text-muted-foreground/50" />
            )}
            <span className="min-w-0 flex-1 truncate">
              <Sensitive length={10}>{i.savedAs || i.name}</Sensitive>
            </span>
            <span className={cn('shrink-0 tabular-nums', i.status === 'error' ? 'text-destructive' : 'text-muted-foreground')}>
              {i.status === 'error'
                ? i.error === 'cancelled'
                  ? t('files.cancelled')
                  : t('common.failed')
                : i.status === 'uploading'
                  ? `${Math.round((i.loaded / (i.size || 1)) * 100)}%`
                  : fmtBytes(i.size)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
