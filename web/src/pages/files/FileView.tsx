// Right pane: viewer + editor of one file. Text files open in CodeMirror (raw text = source of truth),
// markdown, CSV (table) and HTML (page) have Preview / Edit / Split. Save with Ctrl/Cmd+S, 409 → conflict dialog, unsaved edits are
// never lost silently (leave guard, "changed on disk" banner instead of a reload).
import * as React from 'react'
import { useBlocker, useSearchParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { Check, ChevronLeft, ChevronRight, Code2, Columns2, Copy, Download, ExternalLink, Eye, Lock, Maximize2, MoreHorizontal, Pencil, Save, Sparkles, Trash2 } from 'lucide-react'
import type { FileContent, FileEntry, FileWriteResult } from '@/lib/types'
import { api, errorMessage, isApiError } from '@/lib/api'
import { fileRawUrl, useFileContent } from '@/lib/queries/files'
import { qk } from '@/lib/queries/keys'
import { fmtBytes, fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { useHotkey } from '@/commands/shortcuts'
import { useIsMobile } from '@/stores/media'
import {
  Badge,
  Button,
  confirm,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Kbd,
  MOD,
  Segmented,
  Sensitive,
  toast,
  Tooltip,
  usePresentation,
} from '@/components/ui'
import { basename, dirname, iconFor, isRendered, isTextual, joinPath, kindOf, uniqueName } from '@/features/files/kinds'
import { ArchiveView, CsvView, FontView, HtmlView } from '@/features/files/rich'
import { openFileViewer, useFileViewer } from '@/features/files/viewerStore'

/** From the Files page the viewer opens fullscreen (the page is the panel already). */
const viewerFullscreen = () => useFileViewer.getState().setFull(true)
import { CodeSkeleton, FileInfoCard, ImageView, LazyCodeEditor, MediaView, PdfView, ProseSkeleton } from '@/features/files/viewers'
import { ReadError } from '@/features/files/FilePreview'
import { MarkdownReader, TextZoomControl, ZoomBox, zoomsText } from '@/features/files/textZoom'
import { useTextZoom } from '@/features/files/readPos'
import { ConflictDialog, type ConflictChoice } from './dialogs'
import { downloadProps } from '@/features/files/download'

type MdMode = 'preview' | 'edit' | 'split'

export type FileViewActions = {
  open: (path: string, kind?: 'file' | 'dir') => void
  rename: (path: string) => void
  remove: (path: string) => Promise<boolean>
  copyPath: (path: string) => void
  ask: (path: string) => void
}

export function FileView({ path, siblings, actions, entry }: { path: string; siblings: FileEntry[]; actions: FileViewActions; entry?: FileEntry }) {
  const t = useT()
  const lang = useLang()
  const qc = useQueryClient()
  const mobile = useIsMobile()
  const presentation = usePresentation()
  const name = basename(path)
  const kind = kindOf(name)
  const textual = isTextual(kind)
  const rendered = isRendered(kind)
  const content = useFileContent(path, textual)
  const zoom = useTextZoom((s) => s.zoom)

  /* ---------------- editor state: `base` = last known disk version, `doc` = editor text */
  const [base, setBase] = React.useState<{ content: string; mtime: number } | null>(null)
  const [doc, setDoc] = React.useState('')
  const [diskChanged, setDiskChanged] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const [savedFlash, setSavedFlash] = React.useState(false)
  const [conflict, setConflict] = React.useState(false)
  const [conflictBusy, setConflictBusy] = React.useState<ConflictChoice | null>(null)
  // `&edit=1` (the viewer's Edit button): markdown / CSV / HTML open on their source instead of the preview.
  const [params] = useSearchParams()
  const [mode, setMode] = React.useState<MdMode>(params.get('edit') === '1' ? 'edit' : 'preview')
  const dirty = !!base && doc !== base.content
  const live = React.useRef({ doc, base, dirty, skipGuard: false })
  live.current = { ...live.current, doc, base, dirty }

  const adopt = React.useCallback((d: FileContent) => {
    setBase({ content: d.content, mtime: d.mtime })
    setDoc(d.content)
    setDiskChanged(false)
  }, [])

  // New data from the server (first load, refetch on focus): adopt it unless the user has unsaved edits.
  React.useEffect(() => {
    const d = content.data
    if (!d) return
    const { base: b, dirty: isDirty } = live.current
    if (!b) return adopt(d)
    if (Math.abs(d.mtime - b.mtime) < 1e-6) return
    if (!isDirty) adopt(d)
    else setDiskChanged(true)
  }, [content.data, adopt])

  React.useEffect(() => {
    if (!savedFlash) return
    const id = setTimeout(() => setSavedFlash(false), 1800)
    return () => clearTimeout(id)
  }, [savedFlash])

  const editable = !!content.data?.editable && !presentation

  /** PUT /api/files/write. `force` skips the mtime check; `as` writes to another path (copy). */
  const write = React.useCallback(
    async (opts: { force?: boolean; as?: string } = {}): Promise<'ok' | 'conflict' | 'error'> => {
      const b = live.current.base
      if (!b) return 'error'
      const text = live.current.doc
      const target = opts.as || path
      try {
        const r = await api.put<FileWriteResult>('/api/files/write', {
          path: target,
          content: text,
          ...(opts.force || opts.as ? {} : { expected_mtime: b.mtime }),
        })
        if (!opts.as) {
          setBase({ content: text, mtime: r.mtime })
          setDiskChanged(false)
          qc.setQueryData<FileContent>(qk.files.read(path), (old) => (old ? { ...old, content: text, mtime: r.mtime, size: new TextEncoder().encode(text).length } : old))
        }
        void qc.invalidateQueries({ queryKey: qk.files.list(dirname(target)) })
        return 'ok'
      } catch (e) {
        if (isApiError(e, 'conflict')) return 'conflict'
        toast.error(t('files.saveFailed'), errorMessage(e))
        return 'error'
      }
    },
    [path, qc, t],
  )

  const save = React.useCallback(async () => {
    if (!live.current.dirty || saving || !editable) return
    setSaving(true)
    const r = await write()
    setSaving(false)
    if (r === 'ok') setSavedFlash(true)
    if (r === 'conflict') setConflict(true)
  }, [editable, saving, write])

  useHotkey('mod+s', () => void save(), { allowInInput: true, enabled: textual })

  const onConflict = async (c: ConflictChoice) => {
    setConflictBusy(c)
    if (c === 'reload') {
      const r = await content.refetch()
      if (r.data) adopt(r.data)
      setConflict(false)
    } else if (c === 'overwrite') {
      const r = await write({ force: true })
      if (r === 'ok') {
        setConflict(false)
        setSavedFlash(true)
      }
    } else {
      const taken = new Set(siblings.map((s) => s.name))
      const copyName = uniqueName(name, (n) => taken.has(n), t('files.copySuffix'))
      const target = joinPath(dirname(path), copyName)
      const r = await write({ as: target })
      if (r === 'ok') {
        setConflict(false)
        toast.success(t('files.copySaved', { name: copyName }))
        live.current.skipGuard = true
        actions.open(target, 'file')
      }
    }
    setConflictBusy(null)
  }

  /* ---------------- leave guard (in-app navigation + tab close) */
  const blocker = useBlocker(
    React.useCallback(
      ({ currentLocation: a, nextLocation: b }: { currentLocation: { pathname: string; search: string }; nextLocation: { pathname: string; search: string } }) =>
        live.current.dirty && !live.current.skipGuard && (a.pathname !== b.pathname || a.search !== b.search),
      [],
    ),
  )
  React.useEffect(() => {
    if (blocker.state !== 'blocked') return
    let cancelled = false
    void confirm({
      title: t('files.unsavedTitle'),
      description: t('files.unsavedDesc', { name: basename(path) }),
      destructive: true,
      confirmText: t('files.discard'),
      cancelText: t('files.keepEditing'),
    }).then((ok) => {
      if (cancelled) return
      if (ok) blocker.proceed()
      else blocker.reset()
    })
    return () => {
      cancelled = true
    }
  }, [blocker, path, t])
  React.useEffect(() => {
    if (!dirty) return
    const h = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', h)
    return () => window.removeEventListener('beforeunload', h)
  }, [dirty])

  /* ---------------- prev / next between the files of the folder (← / → when not typing) */
  const files = React.useMemo(() => siblings.filter((s) => s.type === 'file'), [siblings])
  const fileIdx = files.findIndex((s) => s.path === path)
  const go = (d: number) => {
    if (fileIdx < 0 || files.length < 2) return
    const n = files[(fileIdx + d + files.length) % files.length]
    if (live.current.dirty) return void toast.info(t('files.unsavedNav'))
    actions.open(n.path, 'file')
  }
  const canGo = fileIdx >= 0 && files.length > 1
  useHotkey('arrowleft', () => go(-1), { enabled: canGo })
  useHotkey('arrowright', () => go(1), { enabled: canGo })

  const Icon = iconFor('file', name)
  const size = content.data?.size ?? entry?.size
  const mtime = content.data?.mtime ?? entry?.mtime
  const mdModes = [
    { value: 'preview' as const, label: <span className="max-lg:sr-only">{t('files.preview')}</span>, icon: <Eye /> },
    { value: 'edit' as const, label: <span className="max-lg:sr-only">{t('common.edit')}</span>, icon: <Code2 /> },
    ...(mobile ? [] : [{ value: 'split' as const, label: <span className="max-lg:sr-only">{t('files.split')}</span>, icon: <Columns2 /> }]),
  ]
  const effMode: MdMode = mobile && mode === 'split' ? 'edit' : mode

  const editor = (
    <LazyCodeEditor
      key={path}
      value={base ? doc : ''}
      filename={name}
      readOnly={!editable}
      onChange={setDoc}
      onSave={() => void save()}
      wrap={kind !== 'code'}
      className="absolute inset-0"
      label={t('files.editorLabel', { name })}
      zoom={zoom}
      memory={path}
    />
  )

  let body: React.ReactNode
  if (kind === 'image')
    body = <ImageView path={path} version={entry?.mtime} />
  else if (kind === 'video' || kind === 'audio') body = <MediaView path={path} kind={kind} version={entry?.mtime} />
  else if (kind === 'pdf') body = <PdfView path={path} />
  else if (kind === 'archive') body = <ArchiveView path={path} />
  else if (kind === 'font') body = <FontView path={path} version={entry?.mtime} />
  else if (kind === 'other') body = <FileInfoCard path={path} size={size} reason={t('files.binaryHint')} />
  else if (content.isError && !base) body = <ReadError path={path} error={content.error} onRetry={() => content.refetch()} />
  else if (kind === 'html' && effMode === 'preview' && !dirty) body = <HtmlView path={path} version={base?.mtime ?? entry?.mtime} />
  else if (!base) body = kind === 'markdown' && mode === 'preview' ? <ProseSkeleton /> : <CodeSkeleton />
  else if (presentation) body = <Sensitive block className="m-4" length={12}>{null}</Sensitive>
  else if (rendered) {
    const preview =
      kind === 'csv' ? (
        <CsvView content={doc} name={name} />
      ) : kind === 'html' ? (
        // The page is the file on disk: unsaved edits show after saving.
        <HtmlView path={path} version={base.mtime} />
      ) : (
        <MarkdownReader key={path} content={doc} path={path} testId="md-preview" className="mx-auto w-full max-w-3xl px-5 py-6 md:px-8 md:py-8" />
      )
    body =
      effMode === 'preview' ? (
        preview
      ) : effMode === 'edit' ? (
        <ZoomBox className="relative min-h-0 flex-1">{editor}</ZoomBox>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-2">
          <ZoomBox className="relative min-h-0 border-r">{editor}</ZoomBox>
          <div className="flex min-h-0 flex-col">{preview}</div>
        </div>
      )
  } else body = <ZoomBox className="relative min-h-0 flex-1">{editor}</ZoomBox>

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="file-view">
      {/* toolbar */}
      <div className="flex h-12 shrink-0 items-center gap-2 border-b px-3 md:px-4">
        <Icon className="size-4 shrink-0 text-muted-foreground max-md:hidden" />
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <span className="min-w-0 truncate text-sm font-medium max-md:hidden">
            <Sensitive length={10}>{name}</Sensitive>
          </span>
          {dirty ? (
            <span className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground" data-testid="dirty">
              <span className="size-2 rounded-full bg-warning" aria-hidden />
              {t('files.unsaved')}
            </span>
          ) : savedFlash ? (
            <span className="flex shrink-0 items-center gap-1 text-xs text-success animate-in" role="status">
              <Check className="size-3.5" />
              {t('common.saved')}
            </span>
          ) : (
            <span className="truncate text-xs text-muted-foreground tabular-nums">
              {[size != null ? fmtBytes(size) : null, mtime ? fmtRelative(mtime, lang) : null].filter(Boolean).join(' · ')}
            </span>
          )}
          {textual && content.data && !content.data.editable && (
            <Badge variant="muted" className="shrink-0 gap-1">
              <Lock className="size-3" />
              {t('files.readOnly')}
            </Badge>
          )}
        </div>
        {textual && base && !presentation && zoomsText(kind, effMode === 'preview') && <TextZoomControl inlineFrom={1536} />}
        {rendered && (base || kind === 'html') && <Segmented size="sm" value={effMode} onChange={setMode} options={mdModes} aria-label={t('files.view')} />}
        {textual && base && editable && (effMode !== 'preview' || !rendered || dirty) && (
          <Tooltip content={<span className="flex items-center gap-1.5">{t('common.save')} <Kbd>{MOD}</Kbd><Kbd>S</Kbd></span>}>
            <Button size="sm" variant={dirty ? 'default' : 'ghost'} onClick={() => void save()} loading={saving} disabled={!dirty} aria-label={t('common.save')}>
              <Save />
              <span className="max-sm:hidden">{t('common.save')}</span>
            </Button>
          </Tooltip>
        )}
        {canGo && (
          <div className="flex items-center max-sm:hidden">
            <Tooltip content={`${t('files.prev')} (←)`}>
              <Button variant="ghost" size="icon-sm" onClick={() => go(-1)} aria-label={t('files.prev')}>
                <ChevronLeft />
              </Button>
            </Tooltip>
            <span className="px-0.5 text-xs text-muted-foreground tabular-nums">
              {fileIdx + 1}/{files.length}
            </span>
            <Tooltip content={`${t('files.next')} (→)`}>
              <Button variant="ghost" size="icon-sm" onClick={() => go(1)} aria-label={t('files.next')}>
                <ChevronRight />
              </Button>
            </Tooltip>
          </div>
        )}
        <Tooltip content={t('viewer.fullscreen')}>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => {
              viewerFullscreen()
              openFileViewer(path, files.map((f) => f.path))
            }}
            aria-label={t('viewer.fullscreen')}
            disabled={dirty}
            data-testid="open-viewer"
          >
            <Maximize2 />
          </Button>
        </Tooltip>
        <Tooltip content={t('files.askClaude')}>
          <Button variant="ghost" size="icon-sm" onClick={() => actions.ask(path)} aria-label={t('files.askClaude')}>
            <Sparkles />
          </Button>
        </Tooltip>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={t('common.more')}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-52">
            <DropdownMenuItem asChild>
              <a {...downloadProps(path, entry?.mtime)}>
                <Download />
                {t('files.download')}
              </a>
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <a href={fileRawUrl(path)} target="_blank" rel="noopener noreferrer">
                <ExternalLink />
                {t('files.openRaw')}
              </a>
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => actions.copyPath(path)}>
              <Copy />
              {t('files.copyPath')}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => actions.ask(path)}>
              <Sparkles />
              {t('files.askClaude')}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => actions.rename(path)} disabled={dirty}>
              <Pencil />
              {t('files.renameMove')}
            </DropdownMenuItem>
            <DropdownMenuItem
              destructive
              onSelect={async () => {
                live.current.skipGuard = true
                const ok = await actions.remove(path)
                if (!ok) live.current.skipGuard = false
              }}
            >
              <Trash2 />
              {t('common.delete')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {diskChanged && (
        <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 border-b bg-warning/10 px-4 py-2 text-[13px]" role="alert">
          <span className="min-w-0 flex-1">{t('files.diskChanged')}</span>
          <Button
            size="sm"
            variant="secondary"
            className="h-7"
            onClick={async () => {
              if (live.current.dirty && !(await confirm({ title: t('files.reloadTitle'), description: t('files.reloadDesc'), destructive: true, confirmText: t('files.reload') }))) return
              const r = await content.refetch()
              if (r.data) adopt(r.data)
            }}
          >
            {t('files.reload')}
          </Button>
          <Button size="sm" variant="ghost" className="h-7" onClick={() => setDiskChanged(false)}>
            {t('files.keepMine')}
          </Button>
        </div>
      )}

      <div className={cn('relative flex min-h-0 flex-1 flex-col', content.isFetching && base && 'transition-opacity')}>{body}</div>

      <ConflictDialog open={conflict} busy={conflictBusy} onChoose={onConflict} onCancel={() => setConflict(false)} />
    </div>
  )
}
