// /files?path=<absolute path> — file browser. `path` is a folder (listing, empty viewer) or a file (listing
// of its folder + viewer/editor). Desktop: listing left, viewer right. Mobile: listing page → file page.
import * as React from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ChevronRight, FileQuestion, Eye, EyeOff, FilePlus, Folder, FolderPlus, FolderX, Home, LayoutGrid, MousePointerClick, Plus, Upload } from 'lucide-react'
import type { FileEntry, FileList } from '@/lib/types'
import { api, errorMessage, isApiError } from '@/lib/api'
import { seedFileKind, useFileKind, useFileList } from '@/lib/queries/files'
import { qk } from '@/lib/queries/keys'
import { cn, copyText } from '@/lib/utils'
import { useT } from '@/i18n'
import { useIsMobile } from '@/stores/media'
import { useRegisterCommands, useRegisterProvider, type Command } from '@/commands/registry'
import { useHotkey } from '@/commands/shortcuts'
import { PageHeader } from '@/components/shell/Page'
import { PageList } from '@/components/shell/PageList'
import { keepPageListOpen, openPageList } from '@/components/shell/TouchNav'
import {
  Button,
  confirm,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  Sensitive,
  Skeleton,
  toast,
  useMask,
} from '@/components/ui'
import { basename, crumbs, dirname, iconFor, isInside, resolvePath } from '@/features/files/kinds'
import { useRemoveEntries } from '@/features/files/selection'
import { Listing, ListTools, canDropInto, droppedPaths, fileDrag, hasPathDrag, type EntryActions } from './Listing'
import { FileView, type FileViewActions } from './FileView'
import { NameDialog, type NameDialogState } from './dialogs'
import { sortEntries, useFilePrefs, useTopicFor, useUploads } from './state'

export default function FilesPage() {
  const t = useT()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const mobile = useIsMobile()
  const mask = useMask()
  const [params] = useSearchParams()
  const path = (params.get('path') || '').replace(/(.)\/+$/, '$1')
  const kindQ = useFileKind(path)
  const isFile = kindQ.data === 'file' || kindQ.data === 'missing'
  const file = isFile ? path : null
  const dir = kindQ.data ? (isFile ? dirname(path) : path) : null
  const listQ = useFileList(dir ?? '')
  const list: FileList | undefined = dir !== null ? listQ.data : undefined
  const root = list?.root ?? null
  const cwd = list?.path ?? (dir || null)
  const prefs = useFilePrefs()
  const uploads = useUploads()
  const fileInput = React.useRef<HTMLInputElement>(null)
  const [nameDialog, setNameDialog] = React.useState<NameDialogState>(null)
  const topic = useTopicFor(file || cwd)

  const go = React.useCallback(
    (p: string, kind?: 'file' | 'dir', replace = false) => {
      if (kind) seedFileKind(qc, p, kind)
      // touch: a folder opened from the list drawer keeps it open (a file closes it)
      if (kind === 'dir') keepPageListOpen()
      navigate(`/files?path=${encodeURIComponent(p)}`, { replace })
    },
    [navigate, qc],
  )

  const visible = React.useMemo(() => (list ? sortEntries(list.entries, { ...prefs, filter: '' }) : []), [list, prefs])
  const entry = file ? list?.entries.find((e) => e.path === file) : undefined
  const exists = (name: string) => !!list?.entries.some((e) => e.name === name)

  /* ---------------- actions */
  const copyPath = React.useCallback(
    async (p: string) => {
      if (await copyText(p)) toast.success(t('files.pathCopied'))
    },
    [t],
  )
  // The topic is computed for the file being viewed / the current folder (the only paths `ask` receives).
  const ask = React.useCallback(() => navigate(`/sessions?path=${encodeURIComponent(topic)}&new=1`), [navigate, topic])

  const remove = React.useCallback(
    async (p: string): Promise<boolean> => {
      const name = basename(p)
      const ok = await confirm({
        title: t('files.deleteTitle', { name: mask(name, 8) }),
        description: t('files.deleteDesc'),
        destructive: true,
        confirmText: t('files.moveToTrash'),
      })
      if (!ok) return false
      try {
        await api.post('/api/files/delete', { path: p })
      } catch (e) {
        toast.error(t('files.deleteFailed'), errorMessage(e))
        return false
      }
      toast.success(t('files.movedToTrash', { name: mask(name, 8) }))
      qc.removeQueries({ queryKey: qk.files.read(p) })
      qc.removeQueries({ queryKey: ['files', 'kind', p] })
      await qc.invalidateQueries({ queryKey: qk.files.list(dirname(p)) })
      // Viewing it (or something inside it)? → go to its folder.
      if (path === p || path.startsWith(p + '/')) go(dirname(p), 'dir', true)
      return true
    },
    [go, mask, path, qc, t],
  )

  const removeEntries = useRemoveEntries()
  const removeMany = React.useCallback(
    async (paths: string[]) => {
      const done = await removeEntries(paths)
      const gone = done.find((p) => path === p || path.startsWith(p + '/'))
      if (gone) go(dirname(gone), 'dir', true)
    },
    [go, path, removeEntries],
  )

  const rename = React.useCallback(
    (p: string) => {
      const parent = dirname(p)
      setNameDialog({
        title: t('files.renameTitle'),
        description: t('files.renameDesc'),
        label: t('files.newNameOrPath'),
        initial: basename(p),
        confirmText: t('files.rename'),
        submit: async (v) => {
          const to = resolvePath(parent, v)
          if (to === p) return null
          if (root && !isInside(to, root)) return t('files.outsideRoot')
          try {
            await api.post('/api/files/move', { from: p, to })
          } catch (e) {
            return isApiError(e, 'exists') ? t('files.exists') : errorMessage(e)
          }
          qc.removeQueries({ queryKey: qk.files.read(p) })
          qc.removeQueries({ queryKey: ['files', 'kind', p] })
          await Promise.all([qc.invalidateQueries({ queryKey: qk.files.list(parent) }), qc.invalidateQueries({ queryKey: qk.files.list(dirname(to)) })])
          toast.success(t('files.renamed'))
          if (path === p) go(to, kindQ.data === 'dir' ? 'dir' : 'file', true)
          else if (path.startsWith(p + '/')) go(to + path.slice(p.length), undefined, true)
          return null
        },
      })
    },
    [go, kindQ.data, path, qc, root, t],
  )

  const newFile = React.useCallback(() => {
    if (!cwd) return
    setNameDialog({
      title: t('files.newFile'),
      label: t('files.fileName'),
      initial: 'untitled.md',
      confirmText: t('files.create'),
      submit: async (v) => {
        const target = resolvePath(cwd, v)
        if (root && !isInside(target, root)) return t('files.outsideRoot')
        if (dirname(target) === cwd && exists(basename(target))) return t('files.exists')
        // The write endpoint has no "create only" flag: check the parent listing first (no overwrite).
        try {
          const parent = await api.get<FileList>('/api/files/list', { path: dirname(target) })
          if (parent.entries.some((x) => x.name === basename(target))) return t('files.exists')
        } catch (e) {
          return errorMessage(e)
        }
        try {
          await api.put('/api/files/write', { path: target, content: '' })
        } catch (e) {
          return errorMessage(e)
        }
        await qc.invalidateQueries({ queryKey: qk.files.list(dirname(target)) })
        go(target, 'file')
        return null
      },
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cwd, go, list, qc, root, t])

  const newFolder = React.useCallback(() => {
    if (!cwd) return
    setNameDialog({
      title: t('files.newFolder'),
      label: t('files.folderName'),
      initial: '',
      confirmText: t('files.create'),
      submit: async (v) => {
        const target = resolvePath(cwd, v)
        if (root && !isInside(target, root)) return t('files.outsideRoot')
        try {
          await api.post('/api/files/mkdir', { path: target })
        } catch (e) {
          return isApiError(e, 'exists') ? t('files.exists') : errorMessage(e)
        }
        await qc.invalidateQueries({ queryKey: qk.files.list(dirname(target)) })
        go(target, 'dir')
        return null
      },
    })
  }, [cwd, go, qc, root, t])

  const pickFiles = React.useCallback(() => fileInput.current?.click(), [])
  const upload = React.useCallback((files: File[]) => cwd && uploads.add(cwd, files), [cwd, uploads])
  const moveOne = React.useCallback(
    async (from: string, dir: string, quiet: boolean): Promise<boolean> => {
      const parent = dirname(from)
      if (dir === from || dir.startsWith(from + '/') || dir === parent) return false
      const to = `${dir.replace(/\/$/, '')}/${basename(from)}`
      if (root && !isInside(to, root)) {
        toast.error(t('files.outsideRoot'))
        return false
      }
      try {
        await api.post('/api/files/move', { from, to })
      } catch (e) {
        toast.error(isApiError(e, 'exists') ? `${mask(basename(from), 8)}: ${t('files.exists')}` : errorMessage(e))
        return false
      }
      qc.removeQueries({ queryKey: qk.files.read(from) })
      qc.removeQueries({ queryKey: ['files', 'kind', from] })
      await Promise.all([qc.invalidateQueries({ queryKey: qk.files.list(parent) }), qc.invalidateQueries({ queryKey: qk.files.list(dir) })])
      if (!quiet) toast.success(t('files.movedTo', { name: mask(basename(from), 8), dir: mask(basename(dir) || dir, 8) }))
      if (path === from || path.startsWith(from + '/')) go(to + path.slice(from.length), undefined, true)
      return true
    },
    [go, mask, path, qc, root, t],
  )
  /** A dragged selection moves as a whole (one after the other, one toast). */
  const moveTo = React.useCallback(
    async (froms: string[], dir: string) => {
      if (froms.length === 1) return void (await moveOne(froms[0], dir, false))
      let n = 0
      for (const from of froms) if (await moveOne(from, dir, true)) n++
      if (n) toast.success(t('files.movedManyTo', { count: n, dir: mask(basename(dir) || dir, 8) }))
    },
    [mask, moveOne, t],
  )

  const addUploads = uploads.add
  const entryActions: EntryActions = React.useMemo(
    () => ({
      open: (e) => go(e.path, e.type),
      rename: (e) => rename(e.path),
      remove: (e) => void remove(e.path),
      copyPath: (e) => void copyPath(e.path),
      removeMany: (paths) => void removeMany(paths),
      moveTo: (from, dir) => void moveTo(from, dir),
      uploadTo: (files, dir) => addUploads(dir, files),
    }),
    // stable pieces only (not `uploads`, a new object each render): the rows are memoized on these actions
    [addUploads, copyPath, go, moveTo, remove, removeMany, rename],
  )
  const viewActions: FileViewActions = React.useMemo(
    () => ({ open: (p, k) => go(p, k), rename, remove, copyPath: (p) => void copyPath(p), ask }),
    [ask, copyPath, go, remove, rename],
  )

  /* ---------------- palette + shortcuts */
  const filesGroup = t('files.actions')
  useRegisterCommands(
    'files',
    cwd
      ? [
          { id: 'files:new-file', title: t('files.newFile'), group: filesGroup, icon: FilePlus, perform: newFile },
          { id: 'files:new-folder', title: t('files.newFolder'), group: filesGroup, icon: FolderPlus, perform: newFolder },
          { id: 'files:upload', title: t('files.uploadFiles'), group: filesGroup, icon: Upload, perform: pickFiles },
          { id: 'files:grid', title: prefs.view === 'list' ? t('files.gridView') : t('files.listView'), group: filesGroup, icon: LayoutGrid, perform: () => prefs.set({ view: prefs.view === 'list' ? 'grid' : 'list' }) },
          { id: 'files:hidden', title: prefs.hidden ? t('files.hideHidden') : t('files.showHidden'), group: filesGroup, icon: prefs.hidden ? EyeOff : Eye, perform: () => prefs.set({ hidden: !prefs.hidden }) },
        ]
      : [],
    [cwd, t, newFile, newFolder, pickFiles, prefs.view, prefs.hidden],
  )
  const entriesRef = React.useRef<FileEntry[]>([])
  entriesRef.current = list?.entries || []
  useRegisterProvider(
    {
      id: 'files:folder',
      group: t('files.inThisFolder'),
      minQuery: 1,
      search: (q) => {
        const s = q.toLowerCase()
        return entriesRef.current
          .filter((e) => e.name.toLowerCase().includes(s))
          .slice(0, 8)
          .map<Command>((e) => ({
            id: `files:folder:${e.path}`,
            title: e.name,
            hint: e.type === 'dir' ? t('files.folder') : undefined,
            group: t('files.inThisFolder'),
            icon: iconFor(e.type, e.name),
            sensitive: true,
            perform: () => go(e.path, e.type),
          }))
      },
    },
    [t, go],
  )
  useHotkey('backspace', () => {
    if (cwd && root && cwd !== root) go(dirname(cwd), 'dir')
  }, { enabled: !mobile })

  /* ---------------- render */
  const segs = cwd && root ? crumbs(file || cwd, root) : []
  const upTarget = mobile ? (file ? dirname(file) : cwd && root && cwd !== root ? dirname(cwd) : null) : null

  // the file or folder open is the page's title, its path (clickable, a drop target) under it on a computer
  let title: React.ReactNode
  if (!root) title = <Skeleton className="h-4 w-48" />
  else title = segs.length > 1 ? <Sensitive length={10}>{segs[segs.length - 1].name}</Sensitive> : <RootLabel name={basename(root) || '/'} />
  const trail = root && !mobile && segs.length > 1 ? <Breadcrumb trail segs={segs.slice(0, -1)} onGo={(p) => go(p, 'dir')} onDropPath={(from, dir) => void moveTo(from, dir)} /> : undefined
  const [filter, setFilter] = React.useState('')
  React.useEffect(() => setFilter(''), [cwd])

  const kindError = kindQ.isError ? kindQ.error : null
  // the folder's list in the second-level sidebar (PageList; touch: the left drawer), the file in the page
  const listing = (
    <Listing
      className="flex-1"
      list={list}
      loading={!kindQ.data || listQ.isPending}
      error={listQ.error}
      onRetry={() => listQ.refetch()}
      selected={file}
      actions={entryActions}
      onUpload={upload}
      onPickFiles={pickFiles}
      uploads={uploads.items}
      onClearUploads={uploads.clear}
      onCancelUploads={uploads.cancelAll}
      onUp={cwd && root && cwd !== root ? () => go(dirname(cwd), 'dir') : undefined}
      filter={filter}
    />
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="files-page">
      <PageHeader
        title={title}
        description={trail}
        sensitiveTitle={t('nav.files')}
        leading={
          upTarget ? (
            <Button variant="ghost" size="icon" onClick={() => go(upTarget, 'dir')} aria-label={t('common.back')} className="-ml-2">
              <ArrowLeft />
            </Button>
          ) : undefined
        }
        actions={
          <>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size={mobile ? 'icon' : 'sm'} variant={mobile ? 'ghost' : 'default'} disabled={!cwd} aria-label={t('files.new')}>
                  <Plus />
                  <span className="max-md:hidden">{t('files.new')}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <DropdownMenuItem onSelect={newFile}>
                  <FilePlus />
                  {t('files.newFile')}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={newFolder}>
                  <FolderPlus />
                  {t('files.newFolder')}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={pickFiles}>
                  <Upload />
                  {t('files.uploadFiles')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        }
      />
      <input
        ref={fileInput}
        type="file"
        multiple
        hidden
        data-testid="upload-input"
        onChange={(e) => {
          const files = Array.from(e.target.files || [])
          e.target.value = ''
          if (files.length) upload(files)
        }}
      />

      {kindError ? (
        <EmptyState
          className="flex-1"
          tone="error"
          icon={FolderX}
          title={isApiError(kindError, 'forbidden') ? t('files.forbidden') : t('files.listError')}
          description={errorMessage(kindError)}
          action={<Button onClick={() => go('', undefined, true)}>{t('files.goRoot')}</Button>}
        />
      ) : (
        <div className="flex min-h-0 flex-1">
          <PageList id="files" label={t('nav.files')} search={{ value: filter, onChange: setFilter, placeholder: t('files.filter') }} actions={<ListTools />}>
            {listing}
          </PageList>
          <section className="flex min-w-0 flex-1 flex-col" aria-label={t('files.viewer')}>
            {file ? (
              kindQ.data === 'missing' ? (
                <EmptyState
                  className="flex-1"
                  icon={FileQuestion}
                  title={t('files.notFound')}
                  description={t('files.notFoundDesc')}
                  action={
                    <Button variant="secondary" onClick={() => go(dirname(file), 'dir')}>
                      {t('files.openFolder')}
                    </Button>
                  }
                />
              ) : (
                <FileView key={file} path={file} siblings={visible} entry={entry} actions={viewActions} />
              )
            ) : kindQ.data ? (
              <EmptyState
                className="flex-1"
                icon={MousePointerClick}
                title={t('files.selectFile')}
                description={t('files.selectFileDesc')}
                action={
                  <>
                    {mobile && (
                      <Button onClick={openPageList}>
                        <Folder />
                        {t('files.openFolder')}
                      </Button>
                    )}
                    <Button variant="secondary" onClick={pickFiles}>
                      <Upload />
                      {t('files.upload')}
                    </Button>
                  </>
                }
              />
            ) : (
              <div className="flex-1" />
            )}
          </section>
        </div>
      )}
      <NameDialog state={nameDialog} onClose={() => setNameDialog(null)} />
    </div>
  )
}

/* ------------------------------------------------------------------ breadcrumb */
function Breadcrumb({ segs, onGo, onDropPath, trail }: { segs: { name: string; path: string }[]; onGo: (p: string) => void; onDropPath: (from: string[], dir: string) => void; /** under the title: small, every folder a link */ trail?: boolean }) {
  const t = useT()
  const [over, setOver] = React.useState<string | null>(null)
  const drop = (dir: string) => ({
    onDragOver: (e: React.DragEvent) => {
      if (!hasPathDrag(e.dataTransfer) || !canDropInto(dir)) return
      e.preventDefault()
      e.dataTransfer.dropEffect = 'move'
      if (over !== dir) setOver(dir)
    },
    onDragLeave: () => setOver((o) => (o === dir ? null : o)),
    onDrop: (e: React.DragEvent) => {
      setOver(null)
      const from = droppedPaths(e.dataTransfer)
      if (!from.length) return
      e.preventDefault()
      fileDrag.paths = []
      onDropPath(from, dir)
    },
  })
  // Long paths: root › … › last three.
  const collapsed = segs.length > 5 ? [segs[0], null, ...segs.slice(-3)] : segs
  const hidden = segs.length > 5 ? segs.slice(1, -3) : []
  return (
    <nav aria-label={t('files.breadcrumb')} className="min-w-0">
      <ol className={cn('flex min-w-0 items-center gap-0.5', trail ? '-ml-1.5 text-[13px]' : 'text-[15px] md:text-base')}>
        {collapsed.map((s, i) => {
          const last = !trail && i === collapsed.length - 1
          return (
            <li key={s ? s.path : 'more'} className={cn('flex min-w-0 items-center gap-0.5', last ? 'shrink' : 'shrink-0')}>
              {i > 0 && <ChevronRight className="size-3.5 shrink-0 text-muted-foreground/60" aria-hidden />}
              {s === null ? (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button type="button" className="rounded-md px-1.5 py-0.5 text-muted-foreground pointer-coarse:py-2 outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring" aria-label={t('files.morePath')}>
                      …
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start">
                    {hidden.map((h) => (
                      <DropdownMenuItem key={h.path} onSelect={() => onGo(h.path)}>
                        <Folder />
                        <Sensitive length={8}>{h.name}</Sensitive>
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : last ? (
                <span aria-current="page" className="min-w-0 truncate rounded-md px-1.5 py-0.5 font-semibold tracking-tight">
                  {i === 0 ? <RootLabel name={s.name} /> : <Sensitive length={8}>{s.name}</Sensitive>}
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => onGo(s.path)}
                  {...drop(s.path)}
                  className={cn(
                    'max-w-48 truncate rounded-md px-1.5 py-0 font-medium text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
                    over === s.path && 'bg-primary/15 text-foreground ring-2 ring-primary',
                  )}
                >
                  {i === 0 ? <RootLabel name={s.name} /> : <Sensitive length={8}>{s.name}</Sensitive>}
                </button>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

function RootLabel({ name }: { name: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <Home className="size-4 shrink-0" />
      <Sensitive length={5}>{name}</Sensitive>
    </span>
  )
}
