// Office documents (Word, PowerPoint, Excel, OpenDocument) read by the server with no converter installed
// (/api/files/doc): text and slides as a page of Markdown with the document's own pictures, a spreadsheet as its
// sheets. The words and the numbers of the file, not its layout: the original is one tap away (download).
import * as React from 'react'
import { FileQuestion, Search } from 'lucide-react'
import { Button, EmptyState, Input, Sensitive } from '@/components/ui'
import { docMediaUrl, useFileDoc } from '@/lib/queries/files'
import { isApiError } from '@/lib/api'
import type { FileSheet } from '@/lib/types'
import { fmtNumber } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { isSheets } from './kinds'
import { ProseSkeleton, TableSkeleton } from './skeletons'
import { MarkdownReader } from './textZoom'
import { FileInfoCard } from './viewers'

export function DocView({ path, className }: { path: string; className?: string }) {
  const t = useT()
  const r = useFileDoc(path)
  const mtime = r.data?.mtime
  const image = React.useCallback((ref: string) => docMediaUrl(path, ref, mtime), [path, mtime])
  if (r.isPending) return isSheets(path) ? <TableSkeleton /> : <ProseSkeleton />
  if (r.isError) {
    if (isApiError(r.error) && r.error.status === 404)
      return <EmptyState icon={FileQuestion} title={t('files.notFound')} description={t('files.notFoundDesc')} className="flex-1" />
    return <FileInfoCard path={path} reason={t(isApiError(r.error, 'too_large') ? 'doc.tooLarge' : 'doc.unsupported')} className={className} />
  }
  const d = r.data
  if (d.type === 'sheets') return <SheetsView key={path} sheets={d.sheets} truncated={d.truncated} className={className} />
  return (
    <>
      {d.truncated && <p className="shrink-0 border-b bg-muted/40 px-4 py-1.5 text-xs text-muted-foreground">{t('doc.truncated')}</p>}
      <Sensitive block className="m-6" length={12}>
        <MarkdownReader key={path} content={d.markdown} path={path} image={image} testId="doc-view" className="mx-auto w-full max-w-3xl px-5 py-6 md:px-8 md:py-8" />
      </Sensitive>
    </>
  )
}

const ROWS_STEP = 500
const NUMBER = /^-?[\d\s.,]+%?$/

/** A, B … Z, AA, AB … as in a spreadsheet. */
function colName(i: number): string {
  let s = ''
  for (let n = i + 1; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s
  return s
}

/** The sheets of a workbook: one table at a time with the letters of the columns and the real numbers of the rows,
 *  the other sheets behind the tabs at the bottom. */
export function SheetsView({ sheets, truncated, className }: { sheets: FileSheet[]; truncated?: boolean; className?: string }) {
  const t = useT()
  const lang = useLang()
  const [at, setAt] = React.useState(0)
  const [q, setQ] = React.useState('')
  const [shown, setShown] = React.useState(ROWS_STEP)
  const scroller = React.useRef<HTMLDivElement>(null)
  const sheet: FileSheet | undefined = sheets[Math.min(at, sheets.length - 1)]
  const rows = React.useMemo(() => (sheet?.rows ?? []).map((cells, i) => ({ i, cells })), [sheet])
  const cols = React.useMemo(() => rows.reduce((n, r) => Math.max(n, r.cells.length), 0), [rows])
  const view = React.useMemo(() => {
    const needle = q.trim().toLowerCase()
    return needle ? rows.filter((r) => r.cells.some((c) => c.toLowerCase().includes(needle))) : rows
  }, [rows, q])
  const open = (i: number) => {
    setAt(i)
    setShown(ROWS_STEP)
    scroller.current?.scrollTo(0, 0)
  }
  if (!sheet) return <EmptyState title={t('viewer.csvEmpty')} className="flex-1" />
  return (
    <div className={cn('flex min-h-0 flex-1 flex-col', className)} data-testid="sheets-view">
      <div className="flex min-h-10 shrink-0 items-center gap-2 border-b px-3 py-1 text-xs text-muted-foreground">
        <span className="min-w-0 truncate tabular-nums">
          {t('viewer.csvSize', { rows: fmtNumber(rows.length, lang), cols })}
          {q && view.length !== rows.length && ` · ${t('viewer.csvMatches', { count: fmtNumber(view.length, lang) })}`}
          {(sheet.truncated || (truncated && sheets.length === 1)) && ` · ${t('doc.sheetTruncated')}`}
        </span>
        <div className="relative ml-auto w-48 shrink-0 max-sm:w-36">
          <Search className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('viewer.filter')} className="h-7 pl-7 text-xs pointer-coarse:h-9" aria-label={t('viewer.filter')} />
        </div>
      </div>
      {/* data-zoomed: a finger moving across a wide sheet scrolls it, it does not go to the next file */}
      <div ref={scroller} className="min-h-0 flex-1 overflow-auto overscroll-contain" data-zoomed={cols > 3 ? '' : undefined}>
        <Sensitive block className="m-4" length={12}>
          {cols === 0 ? (
            <EmptyState title={t('doc.sheetEmpty')} className="h-full" />
          ) : (
            <table className="w-max border-separate border-spacing-0 text-[13px]">
              <thead className="sticky top-0 z-10 bg-card">
                <tr>
                  <th className="sticky left-0 z-10 w-10 border-r border-b bg-card" />
                  {Array.from({ length: cols }, (_, i) => (
                    <th key={i} className="min-w-16 border-r border-b px-2.5 py-1 text-center text-[11px] font-normal text-muted-foreground">
                      {colName(i)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {view.slice(0, shown).map((r) => (
                  <tr key={r.i} className="hover:bg-accent/50">
                    <td className="sticky left-0 h-7 border-r border-b bg-card px-2 py-1 text-right text-[11px] text-muted-foreground tabular-nums">{r.i + 1}</td>
                    {Array.from({ length: cols }, (_, ci) => {
                      const c = r.cells[ci] ?? ''
                      return (
                        <td key={ci} className={cn('max-w-[28rem] truncate border-r border-b px-2.5 py-1', NUMBER.test(c) && 'text-right tabular-nums')} title={c.length > 40 ? c : undefined}>
                          {c}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {view.length > shown && (
            <div className="flex justify-center p-3">
              <Button size="sm" variant="secondary" onClick={() => setShown((n) => n + ROWS_STEP * 4)}>
                {t('viewer.moreRows', { count: fmtNumber(view.length - shown, lang) })}
              </Button>
            </div>
          )}
        </Sensitive>
      </div>
      {sheets.length > 1 && (
        <div className="flex shrink-0 items-center gap-1 overflow-x-auto border-t bg-muted/30 px-2 py-1" role="tablist" aria-label={t('doc.sheets')}>
          {sheets.map((s, i) => (
            <button
              key={i}
              type="button"
              role="tab"
              aria-selected={s === sheet}
              onClick={() => open(i)}
              className={cn(
                'h-7 max-w-48 shrink-0 truncate rounded-md px-2.5 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:h-9',
                s === sheet ? 'bg-background font-medium text-foreground shadow-sm ring-1 ring-border' : 'text-muted-foreground hover:bg-accent hover:text-foreground',
              )}
            >
              <Sensitive length={6}>{s.name}</Sensitive>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
