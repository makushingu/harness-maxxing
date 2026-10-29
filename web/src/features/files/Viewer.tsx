// The file viewer: one window for every file and folder, opened from a conversation, the Files page or
// anywhere (`openFileViewer`). Side panel or fullscreen, ← / → (and a swipe) between the files of the
// conversation or the folder, "up" to the parent folder, neighbours preloaded. Read-only: editing stays
// on the Files page ("Open in Files").
import * as React from 'react'
import { useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { ChevronLeft, ChevronRight, Code2, Download, Eye, FileQuestion, Folder, FolderDown, FolderOpen, FolderUp, Maximize2, Minimize2, MoreVertical, Pencil, Workflow, X } from 'lucide-react'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, EmptyState, Segmented, Sensitive, Tooltip } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { api } from '@/lib/api'
import { filePreviewUrl, fileStamp, fileThumbUrl, prefetchImage, PREVIEW_W, useFileContent, useFileKind, useFileStamp } from '@/lib/queries/files'
import { qk } from '@/lib/queries/keys'
import type { FileContent, FileEntry, FileList } from '@/lib/types'
import { fmtBytes } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { useIsMobile } from '@/stores/media'
import { basename, dirname, iconFor, isRendered, isTextual, kindOf } from './kinds'
import { PreviewBody } from './FilePreview'
import { TextZoomControl, zoomsText } from './textZoom'
import { FolderView } from './rich'
import { CodeSkeleton, DiagramView, MediaSkeleton } from './viewers'
import { videoInfoQuery } from './videoQuality'
import { CodeBlock, CopyButton } from '@/components/ui/code-block'
import { DIAGRAM_PREFIX, diagramCode } from '@/components/ui/diagram'
import { useFileViewer } from './viewerStore'
import { downloadProps, useDownloadZip } from './download'

export default function FileViewerHost() {
  const t = useT()
  const { open, list, index, full, close, go, setFull } = useFileViewer()
  const mobile = useIsMobile()
  const path = list[index] ?? null
  const fullscreen = full || mobile
  const multi = list.length > 1

  // ← / → before anything else on the page (an image of the Files page behind, the composer…).
  React.useEffect(() => {
    if (!open || !multi) return
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey || e.metaKey || e.ctrlKey || (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight')) return
      const el = e.target as HTMLElement | null
      if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.closest('.cm-editor, [data-media-player]'))) return
      e.preventDefault()
      go(e.key === 'ArrowLeft' ? -1 : 1)
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [open, multi, go])

  usePrefetchNeighbours(open ? list : [], index)

  return (
    <DialogPrimitive.Root open={open} onOpenChange={(o) => !o && close()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className={cn('fixed inset-0 z-50 data-[state=open]:animate-overlay-in', fullscreen ? 'bg-background' : 'bg-overlay')} />
        <DialogPrimitive.Content
          onOpenAutoFocus={(e) => e.preventDefault()}
          aria-describedby={undefined}
          data-testid="file-viewer"
          className={cn(
            'fixed z-50 flex flex-col bg-popover text-popover-foreground outline-none',
            fullscreen
              ? 'inset-0 pt-[var(--safe-top)] pb-[var(--safe-bottom)]'
              : 'inset-y-0 right-0 w-[min(860px,94vw)] border-l shadow-pop data-[state=open]:animate-sheet-right',
          )}
        >
          <DialogPrimitive.Title className="sr-only">{path ? (isDiagram(path) ? t('diagram.title') : basename(path)) : t('viewer.title')}</DialogPrimitive.Title>
          {path &&
            (isDiagram(path) ? (
              <DiagramPane key={path} id={path} index={index} count={list.length} fullscreen={fullscreen} canFull={!mobile} onFull={() => setFull(!full)} />
            ) : (
              <ViewerPane key={path} path={path} index={index} count={list.length} fullscreen={fullscreen} canFull={!mobile} onFull={() => setFull(!full)} />
            ))}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

function ViewerPane({ path, index, count, fullscreen, canFull, onFull }: { path: string; index: number; count: number; fullscreen: boolean; canFull: boolean; onFull: () => void }) {
  const t = useT()
  const navigate = useNavigate()
  const { go, close, setList } = useFileViewer()
  const probe = useFileKind(path)
  const isDir = probe.data === 'dir'
  const name = basename(path) || '/'
  const kind = kindOf(name)
  const [view, setView] = React.useState<'preview' | 'source'>('preview')
  const content = useFileContent(path, probe.data === 'file' && isTextual(kind) && !(kind === 'html' && view === 'preview'))
  // Media: the file's current mtime goes in the URLs (a file rewritten under the same name shows its new version).
  const stamp = useFileStamp(probe.data === 'file' && STAMPED.has(kind) ? path : null)
  const Icon = isDir ? Folder : iconFor('file', name)
  const multi = count > 1
  const parent = dirname(path)
  const swipe = useSwipe((d) => go(d), multi)

  const qc = useQueryClient()
  /** A file of a folder shown here: browse that folder's files with ← / →. */
  const openEntry = (e: FileEntry) => {
    if (e.type === 'dir') return setList([e.path], 0)
    const files = qc.getQueryData<FileList>(qk.files.list(path))?.entries.filter((x) => x.type === 'file').map((x) => x.path) ?? [e.path]
    setList(files, Math.max(0, files.indexOf(e.path)))
  }
  const up = () => setList([parent], 0)
  /** Text files: "Edit" opens the Files page in edit mode - a new tab on desktop, in place on a phone (PWA). */
  const editable = !isDir && probe.data === 'file' && isTextual(kind) && kind !== 'binary' && content.data?.editable !== false
  const editUrl = `/files?path=${encodeURIComponent(path)}&edit=1`
  const root = qc.getQueryData<FileList>(qk.files.list(''))?.root
  /** The file in its folder's listing, when the page has it: size and version for the download. */
  const listed = qc.getQueryData<FileList>(qk.files.list(parent))?.entries.find((x) => x.path === path)
  const downloadZip = useDownloadZip()
  const download = downloadProps(path, { version: stamp.version ?? listed?.mtime, size: listed?.size ?? content.data?.size })
  const openInFiles = () => {
    close()
    navigate(`/files?path=${encodeURIComponent(path)}`)
  }
  const canUp = path !== '/' && (!root || (parent + '/').startsWith(root.replace(/\/+$/, '') + '/') || parent === root)

  return (
    <>
      <div className="flex h-12 shrink-0 items-center gap-1 border-b px-2 md:px-3">
        <Icon className="ml-1 size-4 shrink-0 text-muted-foreground" />
        <div className="mr-1 ml-1 grid min-w-0 flex-1 leading-tight">
          <span className="truncate text-sm font-medium" data-testid="viewer-name">
            <Sensitive length={10}>{name}</Sensitive>
          </span>
          <span className="truncate text-[11px] text-muted-foreground tabular-nums">
            {[multi ? `${index + 1} / ${count}` : null, content.data ? fmtBytes(content.data.size) : null].filter(Boolean).join(' · ') || <Sensitive length={14}>{parent}</Sensitive>}
          </span>
        </div>
        {!isDir && isTextual(kind) && content.data && zoomsText(kind, view === 'preview') && <TextZoomControl />}
        {!isDir && isRendered(kind) && (
          <Segmented
            size="sm"
            value={view}
            onChange={setView}
            aria-label={t('files.view')}
            options={[
              { value: 'preview', label: <span className="max-md:sr-only">{t('files.preview')}</span>, icon: <Eye /> },
              { value: 'source', label: <span className="max-md:sr-only">{t('files.source')}</span>, icon: <Code2 /> },
            ]}
          />
        )}
        {editable && (
          <Tooltip content={canFull ? t('viewer.editNewTab') : null}>
            <Button asChild variant="secondary" size="sm" className="mx-1 h-8" data-testid="viewer-edit">
              <a
                href={editUrl}
                target={canFull ? '_blank' : undefined}
                rel="noopener"
                onClick={(e) => {
                  if (canFull) return
                  e.preventDefault()
                  close()
                  navigate(editUrl)
                }}
              >
                <Pencil />
                <span className="max-sm:sr-only">{t('common.edit')}</span>
              </a>
            </Button>
          </Tooltip>
        )}
        {multi && (
          <>
            <Tooltip content={`${t('files.prev')} (←)`}>
              <Button variant="ghost" size="icon-sm" onClick={() => go(-1)} aria-label={t('files.prev')}>
                <ChevronLeft />
              </Button>
            </Tooltip>
            <Tooltip content={`${t('files.next')} (→)`}>
              <Button variant="ghost" size="icon-sm" onClick={() => go(1)} aria-label={t('files.next')}>
                <ChevronRight />
              </Button>
            </Tooltip>
          </>
        )}
        {canUp && (
          <Tooltip content={t('viewer.up')}>
            <Button variant="ghost" size="icon-sm" onClick={up} aria-label={t('viewer.up')} className="max-sm:hidden">
              <FolderUp />
            </Button>
          </Tooltip>
        )}
        {isDir ? (
          <Tooltip content={t('files.downloadZip')}>
            <Button variant="ghost" size="icon-sm" onClick={() => downloadZip(path)} aria-label={t('files.downloadZip')} className="max-sm:hidden" data-testid="viewer-zip">
              <FolderDown />
            </Button>
          </Tooltip>
        ) : (
          <Tooltip content={t('files.download')}>
            <Button asChild variant="ghost" size="icon-sm" className="max-sm:hidden" data-testid="viewer-download">
              <a {...download} aria-label={t('files.download')}>
                <Download />
              </a>
            </Button>
          </Tooltip>
        )}
        <Tooltip content={t('files.openInFiles')}>
          {/* A new tab on desktop (the viewer stays open); in place on a phone (PWA). */}
          <Button asChild variant="ghost" size="icon-sm" className="max-sm:hidden" data-testid="viewer-open-files">
            <a
              href={`/files?path=${encodeURIComponent(path)}`}
              target={canFull ? '_blank' : undefined}
              rel="noopener"
              aria-label={t('files.openInFiles')}
              onClick={(e) => {
                if (canFull) return
                e.preventDefault()
                openInFiles()
              }}
            >
              <FolderOpen />
            </a>
          </Button>
        </Tooltip>
        {/* Phone: the header has no room for every button; download, Files and the parent folder go in a menu. */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={t('common.more')} className="sm:hidden" data-testid="viewer-more">
              <MoreVertical />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-52">
            {isDir ? (
              <DropdownMenuItem onSelect={() => downloadZip(path)}>
                <FolderDown />
                {t('files.downloadZip')}
              </DropdownMenuItem>
            ) : (
              <DropdownMenuItem asChild>
                <a {...download} data-testid="viewer-more-download">
                  <Download />
                  {t('files.download')}
                </a>
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onSelect={openInFiles}>
              <FolderOpen />
              {t('files.openInFiles')}
            </DropdownMenuItem>
            {canUp && (
              <DropdownMenuItem onSelect={up}>
                <FolderUp />
                {t('viewer.up')}
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
        {canFull && (
          <Tooltip content={fullscreen ? t('viewer.panel') : t('viewer.fullscreen')}>
            <Button variant="ghost" size="icon-sm" onClick={onFull} aria-label={fullscreen ? t('viewer.panel') : t('viewer.fullscreen')} data-testid="viewer-full">
              {fullscreen ? <Minimize2 /> : <Maximize2 />}
            </Button>
          </Tooltip>
        )}
        <DialogPrimitive.Close asChild>
          <Button variant="ghost" size="icon-sm" aria-label={t('common.close')}>
            <X />
          </Button>
        </DialogPrimitive.Close>
      </div>
      <div className="relative flex min-h-0 flex-1 flex-col" {...swipe}>
        {probe.isPending ? (
          <CodeSkeleton />
        ) : probe.isError || probe.data === 'missing' ? (
          // Never a skeleton forever: a path that does not exist (or is outside the files root) says so.
          <EmptyState
            icon={FileQuestion}
            title={isApiError(probe.error) && probe.error.status === 403 ? t('viewer.outside') : t('files.notFound')}
            description={isApiError(probe.error) && probe.error.status === 403 ? t('viewer.outsideDesc') : t('files.notFoundDesc')}
            className="flex-1"
          />
        ) : isDir ? (
          <FolderView path={path} onOpen={openEntry} />
        ) : !stamp.ready ? (
          kind === 'video' || kind === 'audio' ? <MediaSkeleton kind={kind} /> : <CodeSkeleton />
        ) : (
          <PreviewBody path={path} kind={kind} view={view} content={content} version={stamp.version} />
        )}
      </div>
    </>
  )
}

const STAMPED = new Set(['image', 'video', 'audio', 'font'])

const isDiagram = (p: string) => p.startsWith(DIAGRAM_PREFIX)

/** A diagram of a conversation (```mermaid): drawn and zoomable like an image, or its code. */
function DiagramPane({ id, index, count, fullscreen, canFull, onFull }: { id: string; index: number; count: number; fullscreen: boolean; canFull: boolean; onFull: () => void }) {
  const t = useT()
  const { go } = useFileViewer()
  const code = diagramCode(id)
  const [view, setView] = React.useState<'preview' | 'source'>('preview')
  const multi = count > 1
  const swipe = useSwipe((d) => go(d), multi)
  return (
    <>
      <div className="flex h-12 shrink-0 items-center gap-1 border-b px-2 md:px-3">
        <Workflow className="ml-1 size-4 shrink-0 text-muted-foreground" />
        <div className="mr-1 ml-1 grid min-w-0 flex-1 leading-tight">
          <span className="truncate text-sm font-medium" data-testid="viewer-name">
            {t('diagram.title')}
          </span>
          {multi && <span className="truncate text-[11px] text-muted-foreground tabular-nums">{`${index + 1} / ${count}`}</span>}
        </div>
        {code && (
          <>
            <Segmented
              size="sm"
              value={view}
              onChange={setView}
              aria-label={t('files.view')}
              options={[
                { value: 'preview', label: <span className="max-md:sr-only">{t('files.preview')}</span>, icon: <Eye /> },
                { value: 'source', label: <span className="max-md:sr-only">{t('files.source')}</span>, icon: <Code2 /> },
              ]}
            />
            <CopyButton text={code} className="size-8" />
          </>
        )}
        {canFull && (
          <Tooltip content={fullscreen ? t('viewer.panel') : t('viewer.fullscreen')}>
            <Button variant="ghost" size="icon-sm" onClick={onFull} aria-label={fullscreen ? t('viewer.panel') : t('viewer.fullscreen')} data-testid="viewer-full">
              {fullscreen ? <Minimize2 /> : <Maximize2 />}
            </Button>
          </Tooltip>
        )}
        <DialogPrimitive.Close asChild>
          <Button variant="ghost" size="icon-sm" aria-label={t('common.close')}>
            <X />
          </Button>
        </DialogPrimitive.Close>
      </div>
      <div className="relative flex min-h-0 flex-1 flex-col" {...swipe}>
        {!code ? (
          <EmptyState icon={FileQuestion} title={t('diagram.gone')} className="flex-1" />
        ) : view === 'source' ? (
          <div className="min-h-0 flex-1 overflow-auto p-4">
            <CodeBlock code={code} language="mermaid" />
          </div>
        ) : (
          <DiagramView key={id} code={code} />
        )}
      </div>
    </>
  )
}

/** Horizontal swipe with a finger (not a mouse, not while zoomed / scrolling sideways). */
function useSwipe(onSwipe: (dir: 1 | -1) => void, enabled: boolean) {
  const start = React.useRef<{ x: number; y: number; t: number } | null>(null)
  if (!enabled) return {}
  return {
    onTouchStart: (e: React.TouchEvent) => {
      // A finger moving a zoomed image or diagram pans it, it does not change file.
      // Nor does a finger on a control: scrubbing a video's progress bar, the volume, a button.
      const held = e.target instanceof Element && e.target.closest('[data-zoomed], [role=slider], button, select, input')
      start.current = e.touches.length === 1 && !held ? { x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now() } : null
    },
    onTouchEnd: (e: React.TouchEvent) => {
      const s = start.current
      start.current = null
      if (!s || (window.visualViewport?.scale ?? 1) > 1.01) return
      const dx = e.changedTouches[0].clientX - s.x
      const dy = e.changedTouches[0].clientY - s.y
      if (Math.abs(dx) > 70 && Math.abs(dy) < 50 && Date.now() - s.t < 600) onSwipe(dx < 0 ? 1 : -1)
    },
  }
}

/** Load what the previous / next item will show, so ← / → feel instant. */
function usePrefetchNeighbours(list: string[], index: number) {
  const qc = useQueryClient()
  React.useEffect(() => {
    if (list.length < 2) return
    const id = setTimeout(() => {
      for (const d of [1, -1]) {
        const p = list[(index + d + list.length) % list.length]
        if (isDiagram(p)) continue
        const k = kindOf(basename(p))
        if (k === 'image') void fileStamp(p).then((v) => prefetchImage(filePreviewUrl(p, PREVIEW_W, v)))
        else if (k === 'video') {
          void fileStamp(p).then((v) => prefetchImage(fileThumbUrl(p, 1280, v)))
          void qc.prefetchQuery(videoInfoQuery(p)) // the player's box gets the video's shape at once
        }
        else if (k === 'pdf') prefetchImage(fileThumbUrl(p, 240, null))
        else if (k === 'markdown' || k === 'csv' || k === 'code' || k === 'text')
          void qc.prefetchQuery({ queryKey: qk.files.read(p), queryFn: () => api.get<FileContent>('/api/files/read', { path: p }), staleTime: 30_000 })
      }
    }, 250)
    return () => clearTimeout(id)
  }, [list, index, qc])
}
