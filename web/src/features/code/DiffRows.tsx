// One file's diff, the same in the Changes view and the PR view: hunk heads, old / new line numbers, + / − lines.
// A click on a line number selects it (shift-click extends); `below` puts something under a line (PR comments).
import * as React from 'react'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'
import type { DiffLine } from './api'

export type Hunk = { head: string; o: number; n: number; lines: DiffLine[] }
export type Row = { kind: 'head'; text: string } | { kind: 'line'; l: DiffLine }
export type Sel = { a: number; b: number }

export function diffRows(hunks: Hunk[]): Row[] {
  const out: Row[] = []
  for (const h of hunks) {
    out.push({ kind: 'head', text: h.head })
    for (const l of h.lines) out.push({ kind: 'line', l })
  }
  return out
}

export function useLineSelection() {
  const [sel, setSel] = React.useState<Sel | null>(null)
  const pick = React.useCallback(
    (i: number, ext: boolean) => setSel((s) => (ext && s ? { a: Math.min(s.a, i), b: Math.max(s.b, i) } : s && s.a === i && s.b === i ? null : { a: i, b: i })),
    [],
  )
  return { sel, setSel, pick }
}

/** The lines of a selection, and "12" / "12-18" (new numbers, else old ones). */
export function selected(rows: Row[], sel: Sel) {
  const lines = rows.slice(sel.a, sel.b + 1).flatMap((r) => (r.kind === 'line' ? [r.l] : []))
  const nums = lines.map((l) => l.n ?? l.o).filter((x): x is number => x != null)
  const range = nums.length ? (nums[0] === nums[nums.length - 1] ? `${nums[0]}` : `${nums[0]}-${nums[nums.length - 1]}`) : ''
  return { lines, range, last: lines[lines.length - 1] }
}

export function DiffRows({ rows, sel, onPick, below, footer }: { rows: Row[]; sel: Sel | null; onPick: (i: number, ext: boolean) => void; below?: (l: DiffLine, i: number) => React.ReactNode; footer?: React.ReactNode }) {
  const t = useT()
  return (
    <div className="min-h-0 flex-1 overflow-auto font-mono text-[12px] leading-[1.6]" data-testid="file-diff">
      <div className="min-w-max">
        {rows.map((r, i) =>
          r.kind === 'head' ? (
            <div key={i} className="sticky left-0 bg-primary/6 px-3 py-0.5 text-[11px] text-muted-foreground">
              {r.text}
            </div>
          ) : (
            <React.Fragment key={i}>
              <div className={cn('flex', r.l.t === '+' && 'bg-success/12', r.l.t === '-' && 'bg-destructive/12', sel && i >= sel.a && i <= sel.b && 'ring-1 ring-primary/60 ring-inset bg-primary/10')}>
                <button
                  type="button"
                  tabIndex={-1}
                  onClick={(e) => onPick(i, e.shiftKey)}
                  className="flex shrink-0 cursor-pointer text-right text-muted-foreground/70 select-none hover:text-foreground"
                  aria-label={t('code.selectLine')}
                >
                  <span className="w-10 pr-1.5">{r.l.o ?? ''}</span>
                  <span className="w-10 pr-1.5">{r.l.n ?? ''}</span>
                </button>
                <span className={cn('w-4 shrink-0 text-center select-none', r.l.t === '+' ? 'text-success' : r.l.t === '-' ? 'text-destructive' : 'text-muted-foreground')}>{r.l.t === ' ' ? '' : r.l.t}</span>
                <span className="pr-4 whitespace-pre">{r.l.s || ' '}</span>
              </div>
              {below?.(r.l, i)}
            </React.Fragment>
          ),
        )}
      </div>
      {footer}
    </div>
  )
}
