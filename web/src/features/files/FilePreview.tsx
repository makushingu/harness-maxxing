// File preview body shared by the file viewer and the Files page. Renders image (zoom/fit), video/audio, pdf,
// markdown / CSV table / HTML page (rendered, or source), office documents (text, slides, sheets), archive contents,
// font specimen, code/text (CodeMirror read-only), and an info card with a download button for other binaries / files
// over 2 MB. Presentation mode: the content is masked at source.
import { FileQuestion, RefreshCw } from 'lucide-react'
import { Button, EmptyState, Sensitive } from '@/components/ui'
import type { useFileContent } from '@/lib/queries/files'
import { errorMessage, isApiError } from '@/lib/api'
import { useT } from '@/i18n'
import { basename, type FileKind } from './kinds'
import { DocView } from './docs'
import { ArchiveView, CsvView, FontView, HtmlView } from './rich'
import { FileInfoCard, ImageView, LazyCodeEditor, MediaView, PdfView } from './viewers'
import { FileSkeleton } from './skeletons'
import { MarkdownReader, ZoomBox } from './textZoom'
import { useTextZoom } from './readPos'

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
    case 'document':
      return <DocView path={path} />
    case 'other':
      return <FileInfoCard path={path} reason={t('files.binaryHint')} />
    case 'html':
      if (view === 'preview') return <HtmlView path={path} version={version ?? content.data?.mtime} />
  }
  if (content.isPending) return <FileSkeleton kind={kind} preview={view === 'preview'} />
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

