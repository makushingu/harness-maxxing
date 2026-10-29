// Rendered views beyond media: CSV/TSV as a table, HTML as a sandboxed page, archive contents, font
// specimen and folder grid. Used by FilePreview / FileViewer (read-only) and by the Files page.
import * as React from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, ExternalLink, File as FileIcon, Folder, RefreshCw, Search, ShieldCheck } from 'lucide-react'
import { Button, EmptyState, Input, Sensitive, Skeleton, toast, Tooltip } from '@/components/ui'
import { api, errorMessage, isApiError } from '@/lib/api'
import { qk } from '@/lib/queries/keys'
import { fileRawUrl, fileThumbUrl, useFileList } from '@/lib/queries/files'
import type { FileEntry } from '@/lib/types'
import { fmtBytes, fmtNumber } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { dirname, extOf, hasThumb, iconFor, iconTone, isInside, resolvePath } from './kinds'
import { EntriesMenu, SelectCheck, SelectionBar, useEntrySelection, useRemoveEntries, type SelectionActions } from './selection'
import { NameDialog, type NameDialogState } from '@/pages/files/dialogs'
import { FileInfoCard } from './viewers'

/* ------------------------------------------------------------------ CSV / TSV */
/** RFC 4180 parser (quotes, doubled quotes, newlines inside quotes). */
export function parseCsv(text: string, delim: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let cell = ''
  let quoted = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          cell += '"'
          i++
        } else quoted = false
      } else cell += c
    } else if (c === '"' && cell === '') quoted = true
    else if (c === delim) {
      row.push(cell)
      cell = ''
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++
      row.push(cell)
      rows.push(row)
      row = []
      cell = ''
    } else cell += c
  }
  if (cell !== '' || row.length) {
    row.push(cell)
    rows.push(row)
  }
  return rows
}

/** `,` `;` or tab: the one found most often on the first line (outside quotes is close enough). */
export function guessDelimiter(text: string, name: string): string {
  if (extOf(name) === 'tsv') return '\t'
  const nl = text.indexOf('\n')
  const first = text.slice(0, nl < 0 ? 2000 : nl)
  const count = (d: string) => first.split(d).length - 1
  return [',', ';', '\t', '|'].reduce((best, d) => (count(d) > count(best) ? d : best), ',')
}

const ROWS_STEP = 500
const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })

export function CsvView({ content, name, className }: { content: string; name: string; className?: string }) {
  const t = useT()
  const lang = useLang()
  const [shown, setShown] = React.useState(ROWS_STEP)
  const [sort, setSort] = React.useState<{ col: number; dir: 1 | -1 } | null>(null)
  const [q, setQ] = React.useState('')
  const { header, rows } = React.useMemo(() => {
    const all = parseCsv(content, guessDelimiter(content, name)).filter((r) => r.length > 1 || r[0] !== '')
    return { header: all[0] ?? [], rows: all.slice(1) }
  }, [content, name])
  const cols = Math.max(header.length, ...rows.slice(0, 200).map((r) => r.length))
  const view = React.useMemo(() => {
    const needle = q.trim().toLowerCase()
    let out = needle ? rows.filter((r) => r.some((c) => c.toLowerCase().includes(needle))) : rows
    if (sort) out = [...out].sort((a, b) => sort.dir * collator.compare(a[sort.col] ?? '', b[sort.col] ?? ''))
    return out
  }, [rows, sort, q])
  const numeric = React.useMemo(
    () => Array.from({ length: cols }, (_, i) => rows.slice(0, 50).every((r) => !r[i] || /^-?[\d\s.,]+%?$/.test(r[i]))),
    [rows, cols],
  )
  if (!header.length) return <EmptyState title={t('viewer.csvEmpty')} className="flex-1" />
  return (
    <div className={cn('flex min-h-0 flex-1 flex-col', className)} data-testid="csv-view">
      <div className="flex min-h-10 shrink-0 items-center gap-2 border-b px-3 py-1 text-xs text-muted-foreground">
        <span className="tabular-nums">{t('viewer.csvSize', { rows: fmtNumber(rows.length, lang), cols })}</span>
        {q && view.length !== rows.length && <span className="tabular-nums">· {t('viewer.csvMatches', { count: fmtNumber(view.length, lang) })}</span>}
        <div className="relative ml-auto w-48 max-sm:w-36">
          <Search className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('viewer.filter')} className="h-7 pl-7 text-xs pointer-coarse:h-9" aria-label={t('viewer.filter')} />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto overscroll-contain">
        <Sensitive block className="m-4" length={12}>
          <table className="w-max min-w-full border-separate border-spacing-0 text-[13px]">
            <thead className="sticky top-0 z-10 bg-card">
              <tr>
                <th className="sticky left-0 z-10 w-10 border-r border-b bg-card px-2 py-1.5 text-right text-[11px] font-normal text-muted-foreground">#</th>
                {Array.from({ length: cols }, (_, i) => (
                  <th key={i} className="border-r border-b p-0 text-left font-medium last:border-r-0">
                    <button
                      type="button"
                      onClick={() => setSort((s) => (s?.col !== i ? { col: i, dir: 1 } : s.dir === 1 ? { col: i, dir: -1 } : null))}
                      className={cn('flex w-full items-center gap-1 px-2.5 py-1.5 whitespace-nowrap hover:bg-accent', numeric[i] && 'justify-end')}
                    >
                      {header[i] ?? ''}
                      {sort?.col === i && (sort.dir === 1 ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {view.slice(0, shown).map((r, ri) => (
                <tr key={ri} className="hover:bg-accent/50">
                  <td className="sticky left-0 border-r border-b bg-background px-2 py-1 text-right text-[11px] text-muted-foreground tabular-nums">{ri + 1}</td>
                  {Array.from({ length: cols }, (_, ci) => (
                    <td key={ci} className={cn('max-w-[28rem] truncate border-r border-b px-2.5 py-1 last:border-r-0', numeric[ci] && 'text-right tabular-nums')} title={r[ci] && r[ci].length > 40 ? r[ci] : undefined}>
                      {r[ci] ?? ''}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {view.length > shown && (
            <div className="flex justify-center p-3">
              <Button size="sm" variant="secondary" onClick={() => setShown((n) => n + ROWS_STEP * 4)}>
                {t('viewer.moreRows', { count: fmtNumber(view.length - shown, lang) })}
              </Button>
            </div>
          )}
        </Sensitive>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ HTML page */
const SANDBOX = 'allow-scripts allow-popups allow-forms allow-modals allow-downloads'

/** The page with its relative assets, through a short-lived URL; it runs in an opaque origin (no session). */
export function HtmlView({ path, version, className }: { path: string; version?: number | null; className?: string }) {
  const t = useT()
  const [reload, setReload] = React.useState(0)
  const q = useQuery({
    queryKey: ['files', 'site', path, version ?? 0],
    queryFn: () => api.get<{ url: string }>('/api/files/site-url', { path }),
    staleTime: 60 * 60_000,
  })
  return (
    <div className={cn('flex min-h-0 flex-1 flex-col', className)} data-testid="html-view">
      <div className="relative min-h-0 flex-1 bg-white">
        <Sensitive placeholder={<div className="absolute inset-0 bg-muted/60" aria-label="Hidden (presentation mode)" />}>
          {q.data ? (
            <iframe key={`${q.data.url}|${reload}`} src={q.data.url} sandbox={SANDBOX} title={path} className="absolute inset-0 size-full border-0" referrerPolicy="no-referrer" />
          ) : q.isError ? (
            <FileInfoCard path={path} reason={t('viewer.htmlError')} />
          ) : (
            <Skeleton className="absolute inset-4" />
          )}
        </Sensitive>
      </div>
      <div className="flex shrink-0 items-center justify-end gap-1 border-t px-3 py-1.5">
        <span className="mr-auto inline-flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground max-sm:hidden">
          <ShieldCheck className="size-3.5 shrink-0" />
          <span className="truncate">{t('viewer.htmlSandbox')}</span>
        </span>
        <Button variant="ghost" size="sm" className="h-7 pointer-coarse:h-9" onClick={() => setReload((n) => n + 1)}>
          <RefreshCw />
          {t('viewer.reload')}
        </Button>
        {q.data && (
          <Button asChild variant="ghost" size="sm" className="h-7 pointer-coarse:h-9">
            <a href={q.data.url} target="_blank" rel="noopener noreferrer">
              <ExternalLink />
              {t('viewer.newTab')}
            </a>
          </Button>
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ archive */
type ArchiveEntry = { name: string; size: number; dir: boolean; mtime: number | null }
type ArchiveListing = { format: string; entries: ArchiveEntry[]; count: number; total_size: number; truncated: boolean; size: number }

export function ArchiveView({ path, className }: { path: string; className?: string }) {
  const t = useT()
  const lang = useLang()
  const [q, setQ] = React.useState('')
  const r = useQuery({ queryKey: ['files', 'archive', path], queryFn: () => api.get<ArchiveListing>('/api/files/archive', { path }), retry: false })
  if (r.isPending)
    return (
      <div className="grid gap-2 p-4">
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={i} className="h-5" style={{ width: `${40 + ((i * 23) % 50)}%` }} />
        ))}
      </div>
    )
  if (r.isError) return <FileInfoCard path={path} reason={isApiError(r.error, 'unsupported') ? t('viewer.archiveUnsupported') : t('files.binaryHint')} className={className} />
  const d = r.data
  const needle = q.trim().toLowerCase()
  const list = needle ? d.entries.filter((e) => e.name.toLowerCase().includes(needle)) : d.entries
  return (
    <div className={cn('flex min-h-0 flex-1 flex-col', className)} data-testid="archive-view">
      <div className="flex min-h-10 shrink-0 items-center gap-2 border-b px-3 py-1 text-xs text-muted-foreground">
        <span className="truncate tabular-nums">
          {[d.format.toUpperCase(), t('viewer.archiveItems', { count: fmtNumber(d.count, lang) }), t('viewer.archiveUnpacked', { size: fmtBytes(d.total_size) })].join(' · ')}
        </span>
        <div className="relative ml-auto w-48 shrink-0 max-sm:w-32">
          <Search className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('viewer.filter')} className="h-7 pl-7 text-xs pointer-coarse:h-9" aria-label={t('viewer.filter')} />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain py-1">
        <Sensitive block className="m-4" length={12}>
          {list.slice(0, 2000).map((e) => {
            const parts = e.name.replace(/\/$/, '').split('/')
            const depth = needle ? 0 : parts.length - 1
            const Icon = e.dir ? Folder : iconFor('file', e.name)
            return (
              <div key={e.name} className="flex h-7 items-center gap-2 px-3 text-[13px] hover:bg-accent/50" style={{ paddingLeft: 12 + depth * 16 }}>
                <Icon className={cn('size-3.5 shrink-0', iconTone(e.dir ? 'dir' : 'file'))} />
                <span className="min-w-0 flex-1 truncate">{needle ? e.name : parts[parts.length - 1]}</span>
                {!e.dir && <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{fmtBytes(e.size)}</span>}
              </div>
            )
          })}
          {(d.truncated || list.length > 2000) && <p className="px-3 py-2 text-xs text-muted-foreground">{t('viewer.archiveTruncated')}</p>}
        </Sensitive>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ font */
const SIZES = [56, 36, 24, 16, 12]

export function FontView({ path, version, className }: { path: string; version?: number | null; className?: string }) {
  const t = useT()
  const family = React.useMemo(() => `mx-font-${Math.abs([...path].reduce((h, c) => (h * 31 + c.charCodeAt(0)) | 0, 7))}`, [path])
  const [state, setState] = React.useState<'loading' | 'ready' | 'error'>('loading')
  const [sample, setSample] = React.useState(t('viewer.fontSample'))
  React.useEffect(() => {
    let alive = true
    setState('loading')
    const face = new FontFace(family, `url(${JSON.stringify(fileRawUrl(path, false, version))})`)
    face
      .load()
      .then((f) => {
        if (!alive) return
        document.fonts.add(f)
        setState('ready')
      })
      .catch(() => alive && setState('error'))
    return () => {
      alive = false
    }
  }, [family, path, version])
  if (state === 'error') return <FileInfoCard path={path} reason={t('viewer.fontError')} className={className} />
  return (
    <div className={cn('min-h-0 flex-1 overflow-y-auto overscroll-contain', className)} data-testid="font-view">
      <div className={cn('mx-auto grid w-full max-w-3xl gap-6 px-5 py-6 transition-opacity md:px-8', state === 'loading' && 'opacity-0')} style={{ fontFamily: `'${family}', system-ui` }}>
        <Input value={sample} onChange={(e) => setSample(e.target.value)} aria-label={t('viewer.fontSampleLabel')} className="font-sans" />
        {SIZES.map((s) => (
          <div key={s} className="grid gap-1">
            <span className="font-sans text-[11px] text-muted-foreground tabular-nums">{s} px</span>
            <p className="leading-tight break-words" style={{ fontSize: s }}>
              {sample || ' '}
            </p>
          </div>
        ))}
        <div className="grid gap-1 border-t pt-5 text-xl leading-relaxed break-all">
          <p>ABCDEFGHIJKLMNOPQRSTUVWXYZ</p>
          <p>abcdefghijklmnopqrstuvwxyz</p>
          <p>0123456789 &amp;@#%?!€$ (é à ç ñ ü ß)</p>
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ folder */
/** A folder as a grid of tiles. Several at once (selection.tsx): long press, Shift / Ctrl+click, right click;
 *  rename and delete here too, so the viewer does not have to send the user to the Files page for that. */
export function FolderView({ path, onOpen, onOpenInFiles, className }: { path: string; onOpen: (e: FileEntry) => void; onOpenInFiles?: (e: FileEntry) => void; className?: string }) {
  const t = useT()
  const list = useFileList(path)
  const entries = list.data?.entries ?? NO_ENTRIES
  const root = React.useRef<HTMLDivElement>(null)
  const sel = useEntrySelection({ entries, onOpen, root })
  const removeEntries = useRemoveEntries()
  const [nameDialog, setNameDialog] = React.useState<NameDialogState>(null)
  const qc = useQueryClient()
  const actions: SelectionActions = {
    open: onOpen,
    openInFiles: onOpenInFiles,
    rename: (e) =>
      setNameDialog({
        title: t('files.renameTitle'),
        description: t('files.renameDesc'),
        label: t('files.newNameOrPath'),
        initial: e.name,
        confirmText: t('files.rename'),
        submit: async (v) => {
          const to = resolvePath(path, v)
          if (to === e.path) return null
          if (list.data?.root && !isInside(to, list.data.root)) return t('files.outsideRoot')
          try {
            await api.post('/api/files/move', { from: e.path, to })
          } catch (x) {
            return isApiError(x, 'exists') ? t('files.exists') : errorMessage(x)
          }
          qc.removeQueries({ queryKey: qk.files.read(e.path) })
          qc.removeQueries({ queryKey: ['files', 'kind', e.path] })
          await Promise.all([qc.invalidateQueries({ queryKey: qk.files.list(path) }), qc.invalidateQueries({ queryKey: qk.files.list(dirname(to)) })])
          toast.success(t('files.renamed'))
          return null
        },
      }),
    remove: (es) => void removeEntries(es.map((e) => e.path)),
  }
  if (list.isPending)
    return (
      <div className="grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] gap-3 p-4">
        {Array.from({ length: 12 }, (_, i) => (
          <Skeleton key={i} className="aspect-square" />
        ))}
      </div>
    )
  if (list.isError) return <EmptyState tone="error" icon={Folder} title={t('files.loadError')} className={cn('flex-1', className)} />
  if (!entries.length) return <EmptyState icon={Folder} title={t('viewer.folderEmpty')} className={cn('flex-1', className)} />
  // A big folder: off-screen tiles are not laid out nor painted.
  const cv = entries.length > 300
  const picked = sel.selecting ? entries.filter((e) => sel.selected.has(e.path)) : NO_ENTRIES
  return (
    <div ref={root} className={cn('flex min-h-0 flex-1 flex-col', className)}>
      <SelectionBar entries={picked} actions={actions} total={entries.length} onSelectAll={sel.selectAll} onClear={sel.clear} />
      <div className="group/sel min-h-0 flex-1 overflow-y-auto overscroll-contain" data-testid="folder-view" {...sel.bind}>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] gap-2 p-3" role="list" aria-label={t('files.contents')}>
          {entries.map((e) => (
            <FolderTile key={e.path} entry={e} checked={sel.selected.has(e.path)} cv={cv} />
          ))}
        </div>
      </div>
      <EntriesMenu at={sel.menu} actions={actions} onClose={sel.closeMenu} />
      <NameDialog state={nameDialog} onClose={() => setNameDialog(null)} />
    </div>
  )
}

const NO_ENTRIES: FileEntry[] = []

const FolderTile = React.memo(function FolderTile({ entry: e, checked, cv }: { entry: FileEntry; checked: boolean; cv: boolean }) {
  const [thumbOk, setThumbOk] = React.useState(true)
  const Icon = e.type === 'dir' ? Folder : iconFor('file', e.name) || FileIcon
  const thumb = e.type === 'file' && hasThumb(e.name) && thumbOk
  return (
    <Tooltip content={e.name.length > 24 ? e.name : null}>
      <button
        type="button"
        role="listitem"
        data-row
        data-path={e.path}
        aria-pressed={checked || undefined}
        className={cn(
          'mx-tile grid gap-1.5 rounded-lg p-1.5 text-center outline-none focus-visible:ring-2 focus-visible:ring-ring',
          checked ? 'bg-primary/10 ring-2 ring-primary' : 'hover:bg-accent/60',
          cv && 'mx-cv-tile',
        )}
      >
        <div className="relative flex aspect-square w-full items-center justify-center overflow-hidden rounded-md border bg-muted/40">
          <Sensitive placeholder={<Icon className={cn('size-8', iconTone(e.type))} strokeWidth={1.4} />}>
            {thumb ? (
              <img src={fileThumbUrl(e.path, 240, e.mtime)} alt="" loading="lazy" decoding="async" draggable={false} onError={() => setThumbOk(false)} className={cn('size-full object-cover', extOf(e.name) === 'pdf' && 'object-top')} />
            ) : (
              <Icon className={cn('size-8', iconTone(e.type))} strokeWidth={1.4} />
            )}
          </Sensitive>
          <SelectCheck checked={checked} className="absolute top-1.5 left-1.5 size-5" />
        </div>
        <span className="line-clamp-2 min-h-[2lh] text-xs leading-snug break-all">
          <Sensitive length={8}>{e.name}</Sensitive>
        </span>
      </button>
    </Tooltip>
  )
})
