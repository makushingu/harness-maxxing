// <FilePreview path="/abs/path" /> — read-only preview of any file, reusable anywhere (Sessions drawer,
// dashboards…). Renders image (zoom/fit), video/audio, pdf, markdown / CSV table / HTML page (rendered,
// toggle to source), archive contents, font specimen, code/text (CodeMirror read-only), and an info card
// with a download button for other binaries / files over 2 MB. Fills its parent: give it a height.
// Presentation mode: the content and the name are masked at source.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Code2, Download, Eye, FileQuestion, FolderOpen, RefreshCw } from 'lucide-react'
import { Button, EmptyState, Segmented, Sensitive, Tooltip } from '@/components/ui'
import { useFileContent } from '@/lib/queries/files'
import { errorMessage, isApiError } from '@/lib/api'
import { fmtBytes } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { useIsMobile } from '@/stores/media'
import { basename, iconFor, isRendered, isTextual, kindOf, type FileKind } from './kinds'
import { ArchiveView, CsvView, FontView, HtmlView } from './rich'
import { CodeSkeleton, FileInfoCard, ImageView, LazyCodeEditor, MediaView, PdfView, ProseSkeleton } from './viewers'
import { MarkdownReader, TextZoomControl, ZoomBox, zoomsText } from './textZoom'
import { useTextZoom } from './readPos'
import { downloadProps } from './download'

export type FilePreviewProps = {
  /** Absolute path of the file (inside files_root). */
  path: string
  className?: string
  /** Show the compact title bar (name, size, markdown toggle, download, open in Files). Default true. */
  header?: boolean
  /** Show the "Open in Files" button in the title bar. Default true. */
  openInFiles?: boolean
}

export function FilePreview({ path, className, header = true, openInFiles = true }: FilePreviewProps) {
  const t = useT()
  const navigate = useNavigate()
  const mobile = useIsMobile()
  const name = basename(path)
  const kind = kindOf(name)
  const [mdMode, setMdMode] = React.useState<'preview' | 'source'>('preview')
  const content = useFileContent(path, isTextual(kind) && !(kind === 'html' && mdMode === 'preview'))
  const Icon = iconFor('file', name)
  return (
    <div className={cn('flex min-h-0 flex-1 flex-col overflow-hidden bg-background', className)} data-testid="file-preview">
      {header && (
        <div className="flex h-11 shrink-0 items-center gap-2 border-b px-3">
          <Icon className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate text-sm font-medium" title={undefined}>
            <Sensitive length={10}>{name}</Sensitive>
          </span>
          {content.data && <span className="text-xs text-muted-foreground tabular-nums max-sm:hidden">{fmtBytes(content.data.size)}</span>}
          {isTextual(kind) && content.data && zoomsText(kind, mdMode === 'preview') && <TextZoomControl />}
          {isRendered(kind) && (kind === 'html' || content.data) && (
            <Segmented
              size="sm"
              value={mdMode}
              onChange={setMdMode}
              aria-label={t('files.view')}
              options={[
                { value: 'preview', label: <span className="max-sm:sr-only">{t('files.preview')}</span>, icon: <Eye /> },
                { value: 'source', label: <span className="max-sm:sr-only">{t('files.source')}</span>, icon: <Code2 /> },
              ]}
            />
          )}
          <Tooltip content={t('files.download')}>
            <Button asChild variant="ghost" size="icon-sm">
              <a {...downloadProps(path, { size: content.data?.size })} aria-label={t('files.download')}>
                <Download />
              </a>
            </Button>
          </Tooltip>
          {openInFiles && (
            <Tooltip content={t('files.openInFiles')}>
              <Button asChild variant="ghost" size="icon-sm">
                <a
                  href={`/files?path=${encodeURIComponent(path)}`}
                  target={mobile ? undefined : '_blank'}
                  rel="noopener"
                  aria-label={t('files.openInFiles')}
                  onClick={(e) => {
                    if (!mobile) return
                    e.preventDefault()
                    navigate(`/files?path=${encodeURIComponent(path)}`)
                  }}
                >
                  <FolderOpen />
                </a>
              </Button>
            </Tooltip>
          )}
        </div>
      )}
      <PreviewBody path={path} kind={kind} view={mdMode} content={content} />
    </div>
  )
}

type ContentQuery = ReturnType<typeof useFileContent>

/** Body only (no title bar). Exported for the file viewer and the Files page. `view` = rendered or source. */
export function PreviewBody({ path, kind, view = 'preview', content, version }: { path: string; kind: FileKind; view?: 'preview' | 'source'; content: ContentQuery; version?: number | null }) {
  const t = useT()
  const zoom = useTextZoom((s) => s.zoom)
  switch (kind) {
    case 'image':
      return <ImageView path={path} version={version} />
    case 'video':
    case 'audio':
      return <MediaView path={path} kind={kind} version={version} />
    case 'pdf':
      return <PdfView path={path} />
    case 'archive':
      return <ArchiveView path={path} />
    case 'font':
      return <FontView path={path} version={version} />
    case 'other':
      return <FileInfoCard path={path} reason={t('files.binaryHint')} />
    case 'html':
      if (view === 'preview') return <HtmlView path={path} version={version ?? content.data?.mtime} />
  }
  if (content.isPending) return kind === 'markdown' && view === 'preview' ? <ProseSkeleton /> : <CodeSkeleton />
  if (content.isError) return <ReadError path={path} error={content.error} onRetry={() => content.refetch()} />
  const data = content.data!
  if (kind === 'csv' && view === 'preview') return <CsvView content={data.content} name={basename(path)} />
  if (kind === 'markdown' && view === 'preview')
    return (
      <Sensitive block className="m-6" length={12}>
        <MarkdownReader key={path} content={data.content} path={path} className="mx-auto w-full max-w-3xl px-5 py-6 md:px-8 md:py-8" />
      </Sensitive>
    )
  return (
    <ZoomBox className="relative min-h-0 flex-1">
      <Sensitive block className="m-4" length={12}>
        <LazyCodeEditor key={path} value={data.content} filename={basename(path)} readOnly wrap={kind !== 'code'} className="absolute inset-0" label={basename(path)} zoom={zoom} memory={path} />
      </Sensitive>
    </ZoomBox>
  )
}

/** 415 binary / 413 too large → info card with download; 404 → not found; other → retry. */
export function ReadError({ path, error, onRetry }: { path: string; error: unknown; onRetry: () => void }) {
  const t = useT()
  if (isApiError(error, 'binary')) return <FileInfoCard path={path} reason={t('files.binaryHint')} />
  if (isApiError(error, 'too_large')) return <FileInfoCard path={path} reason={t('files.tooLarge')} />
  if (isApiError(error) && error.status === 404)
    return <EmptyState icon={FileQuestion} title={t('files.notFound')} description={t('files.notFoundDesc')} className="flex-1" />
  return (
    <EmptyState
      tone="error"
      icon={FileQuestion}
      title={t('files.loadError')}
      description={errorMessage(error)}
      className="flex-1"
      action={
        <Button variant="secondary" onClick={onRetry}>
          <RefreshCw />
          {t('common.retry')}
        </Button>
      }
    />
  )
}

export default FilePreview
