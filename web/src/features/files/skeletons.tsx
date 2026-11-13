// What the file viewer shows while a file loads: the shape of what is coming (lines of code, a page of text, a table,
// a picture, a PDF page, a file card), not the same grey bars for everything. Shown after 120 ms, so a file that comes
// at once never flashes; one light band sweeps over the whole shape (.mx-file-wait in globals.css).
import * as React from 'react'
import { FileText, Image as ImageIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { isSheets, type FileKind } from './kinds'

function Bone({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={cn('rounded-[4px] bg-muted-foreground/15', className)} style={style} />
}

function Wait({ className, children, label = 'loading' }: { className?: string; children: React.ReactNode; label?: string }) {
  return (
    <div className={cn('mx-file-wait min-h-0 flex-1', className)} aria-hidden data-testid={`file-skeleton-${label}`}>
      {children}
    </div>
  )
}

// indent (in steps), then the segments of the line (% of the width); the first segment of some lines is a keyword
const CODE: [number, number[], boolean?][] = [
  [0, [10, 26], true], [0, [14, 20, 12], true], [0, []], [0, [12, 30], true], [1, [18, 34]], [1, [10, 16, 22], true],
  [2, [40]], [2, [22, 18]], [1, [6]], [1, [28, 14]], [0, [4]], [0, []], [0, [16, 24], true], [1, [36]],
]

export function CodeSkeleton({ className }: { className?: string }) {
  return (
    <Wait className={cn('overflow-hidden py-3 font-mono', className)} label="code">
      {CODE.map(([indent, parts, keyword], i) => (
        <div key={i} className="flex h-[1.4rem] items-center gap-3 pr-4">
          <span className="w-9 shrink-0 pr-2 text-right text-[11px] text-muted-foreground/35 tabular-nums">{i + 1}</span>
          <div className="flex min-w-0 flex-1 items-center gap-1.5" style={{ paddingLeft: `${indent * 1.25}rem` }}>
            {parts.map((w, j) => (
              <Bone key={j} className={cn('h-2.5', j === 0 && keyword && 'bg-primary/20')} style={{ width: `${w}%` }} />
            ))}
          </div>
        </div>
      ))}
    </Wait>
  )
}

export function ProseSkeleton({ className }: { className?: string }) {
  return (
    <Wait className={cn('overflow-hidden', className)} label="prose">
      <div className="mx-auto grid w-full max-w-3xl content-start gap-3 p-6">
        <Bone className="h-6 w-1/2" />
        <Bone className="mb-2 h-2.5 w-1/4 opacity-70" />
        {[96, 91, 84, 62].map((w, i) => (
          <Bone key={i} className="h-3" style={{ width: `${w}%` }} />
        ))}
        <Bone className="mt-4 h-4 w-1/3" />
        {[70, 58, 64].map((w, i) => (
          <div key={i} className="flex items-center gap-2.5 pl-1">
            <Bone className="size-1.5 shrink-0 rounded-full" />
            <Bone className="h-3" style={{ width: `${w}%` }} />
          </div>
        ))}
        <Bone className="mt-2 h-20 w-full rounded-lg opacity-80" />
        {[93, 77].map((w, i) => (
          <Bone key={i} className="h-3" style={{ width: `${w}%` }} />
        ))}
      </div>
    </Wait>
  )
}

export function TableSkeleton() {
  const cols = [22, 34, 18, 26]
  return (
    <Wait className="overflow-hidden p-4" label="table">
      <div className="overflow-hidden rounded-lg border">
        <div className="flex gap-4 border-b bg-muted px-3 py-2.5">
          {cols.map((w, i) => (
            <Bone key={i} className="h-3 bg-muted-foreground/20" style={{ width: `${w}%` }} />
          ))}
        </div>
        {Array.from({ length: 9 }, (_, r) => (
          <div key={r} className="flex gap-4 border-b px-3 py-2.5 last:border-b-0">
            {cols.map((w, i) => (
              <Bone key={i} className="h-2.5" style={{ width: `${w - ((r * 7 + i * 5) % 12)}%` }} />
            ))}
          </div>
        ))}
      </div>
    </Wait>
  )
}

function PictureSkeleton() {
  return (
    <Wait className="flex items-center justify-center p-4 [container-type:size] md:p-6" label="image">
      <div
        className="flex items-center justify-center rounded-xl bg-muted-foreground/12"
        style={{ width: 'min(40rem, 100cqw, calc(100cqh * 4 / 3))', aspectRatio: '4 / 3' }}
      >
        <ImageIcon className="size-10 text-muted-foreground/25" strokeWidth={1.5} />
      </div>
    </Wait>
  )
}

export function PageSkeleton() {
  return (
    <Wait className="flex items-start justify-center overflow-hidden bg-muted p-4 [container-type:size] md:p-6" label="pdf">
      <div
        className="grid content-start gap-2.5 rounded-sm border bg-card p-[7%] shadow-pop"
        style={{ width: 'min(34rem, 100cqw, calc((100cqh - 1rem) / 1.414))', aspectRatio: '1 / 1.414' }}
      >
        <Bone className="mb-3 h-4 w-3/5" />
        {[100, 96, 98, 72, 0, 100, 94, 97, 88, 60, 0, 99, 92, 81].map((w, i) =>
          w ? <Bone key={i} className="h-2" style={{ width: `${w}%` }} /> : <div key={i} className="h-2" />,
        )}
      </div>
    </Wait>
  )
}

function CardSkeleton() {
  return (
    <Wait className="flex items-center justify-center p-6" label="card">
      <div className="flex w-72 max-w-full flex-col items-center gap-3 rounded-xl border bg-card p-6">
        <div className="flex size-14 items-center justify-center rounded-xl bg-muted-foreground/15">
          <FileText className="size-6 text-muted-foreground/30" strokeWidth={1.5} />
        </div>
        <Bone className="h-3.5 w-2/3" />
        <Bone className="h-2.5 w-1/3 opacity-70" />
        <Bone className="mt-2 h-8 w-28 rounded-md" />
      </div>
    </Wait>
  )
}


/** While the file's version is asked (a moment): the black box of a video, the card of an audio file - not lines of
 *  text that turn into a picture. */
export function MediaSkeleton({ kind }: { kind: 'video' | 'audio' }) {
  return (
    <div className="mx-file-wait flex min-h-40 flex-1 items-center justify-center p-4 [container-type:size] md:p-6" aria-hidden data-testid="media-skeleton">
      {kind === 'video' ? (
        <div className="rounded-xl bg-black shadow-pop" style={{ width: 'min(48rem, 100cqw, calc(100cqh * 16 / 9))', aspectRatio: '16 / 9' }} />
      ) : (
        <div className="flex h-28 w-full max-w-lg items-center gap-4 rounded-xl border bg-card px-5">
          <Bone className="size-12 shrink-0 rounded-full" />
          <div className="flex h-10 flex-1 items-center gap-[3px]">
            {Array.from({ length: 40 }, (_, i) => (
              <Bone key={i} className="w-full rounded-full" style={{ height: `${25 + ((i * 37) % 70)}%` }} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/** The loader of a file of this kind (`preview` = its rendered view: a page of Markdown, a table of a CSV). */
export function FileSkeleton({ kind, preview = true, name = '' }: { kind: FileKind; preview?: boolean; name?: string }) {
  switch (kind) {
    case 'image':
      return <PictureSkeleton />
    case 'video':
    case 'audio':
      return <MediaSkeleton kind={kind} />
    case 'pdf':
      return <PageSkeleton />
    case 'markdown':
    case 'html':
      return preview ? <ProseSkeleton /> : <CodeSkeleton />
    case 'csv':
      return preview ? <TableSkeleton /> : <CodeSkeleton />
    case 'code':
    case 'text':
      return <CodeSkeleton />
    case 'document':
      return isSheets(name) ? <TableSkeleton /> : <ProseSkeleton />
    default:
      return <CardSkeleton />
  }
}
