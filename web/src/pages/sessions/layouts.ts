// Ready-made layouts of the sessions strip (the "snap layouts" shown when hovering a column's grip or the grid
// button). A layout is a list of strip columns, left to right: `one` session, a `big` one (two shares of the
// width), a `half` one (half the strip's visible width, held in place while the other sessions scroll past it),
// a `pair` stacked top / bottom or a `trio` (three stacked). Zones are numbered left to right, top before bottom.
import type { Col } from './store'

export type Slot = 'one' | 'big' | 'half' | 'pair' | 'trio'

/** Narrowest a strip column gets before the strip scrolls. */
export const MIN_W = 380
/** Lowest a session of a stack gets. */
const ROW_MIN = 120

/** Sessions a strip column of that kind holds. */
export const slotSize = (s: Slot) => (s === 'pair' ? 2 : s === 'trio' ? 3 : 1)
export const zones = (slots: Slot[]) => slots.reduce((n, s) => n + slotSize(s), 0)
export const layoutId = (slots: Slot[]) => slots.join('-')

const L = (...slots: Slot[]) => slots
const pairs = (n: number): Slot[] => [...Array<Slot>(Math.floor(n / 2)).fill('pair'), ...(n % 2 ? ['one' as Slot] : [])]
const trios = (n: number): Slot[] => [...Array<Slot>(Math.floor(n / 3)).fill('trio'), ...(n % 3 === 2 ? ['pair' as Slot] : n % 3 ? ['one' as Slot] : [])]

/** The layouts offered for `n` open sessions (none under 2): every session gets a place (no layout leaves one out),
 *  the simplest first, a big one on the left then its mirror. */
export function layoutsFor(n: number): Slot[][] {
  if (n < 2) return []
  if (n === 2) return [L('one', 'one'), L('big', 'one'), L('one', 'big'), L('pair')]
  if (n === 3) return [L('one', 'one', 'one'), L('big', 'pair'), L('pair', 'big'), L('one', 'pair')]
  // from 4: one session on half the screen (the others beside it, by 2 or by 3, scrolling past it when they do
  // not fit), then its mirror
  const half: Slot[][] = [
    ['half', ...pairs(n - 1)], [...pairs(n - 1), 'half'],
    ['half', ...trios(n - 1)], [...trios(n - 1), 'half'],
  ]
  if (n === 4) return [L('pair', 'pair'), L('one', 'one', 'one', 'one'), L('big', 'one', 'pair'), L('pair', 'one', 'big'), ...half]
  return [pairs(n), trios(n), ...half, ['big', ...pairs(n - 1)], [...pairs(n - 1), 'big'], Array<Slot>(n).fill('one')]
}

/** Strip columns a layout needs. */
export const columnsOf = (slots: Slot[]) => slots.length

/** Columns a layout needs side by side on screen: a `half` one only needs its half and one column beside it (the
 *  rest scrolls past it). */
const needs = (l: Slot[]) => (l.includes('half') ? 2 : columnsOf(l))

/** The layouts that fit `room` px (each strip column at least `minW`); never none: the narrowest one stays. */
export function fitting(all: Slot[][], room: number, minW: number): Slot[][] {
  const max = Math.max(1, Math.floor(room / minW))
  // the grids stay even when they scroll: with many sessions they are the densest way to see them
  const ok = all.filter((l) => needs(l) <= max || (l.length > 1 && /^grid/.test(layoutName(l))))
  return ok.length ? ok : [all.reduce((a, b) => (columnsOf(b) < columnsOf(a) ? b : a))]
}

/** What a layout is called (i18n key suffix). */
export function layoutName(slots: Slot[]): 'columns' | 'grid' | 'grid3' | 'mainLeft' | 'mainRight' | 'halfLeft' | 'halfRight' | 'halfLeft3' | 'halfRight3' | 'stacked' | 'mixed' {
  const last = slots.length - 1
  if (slots.length === 1 && (slots[0] === 'pair' || slots[0] === 'trio')) return 'stacked'
  const by3 = slots.includes('trio')
  if (slots[0] === 'half') return by3 ? 'halfLeft3' : 'halfLeft'
  if (slots[last] === 'half') return by3 ? 'halfRight3' : 'halfRight'
  if (slots[0] === 'big') return 'mainLeft'
  if (slots[last] === 'big') return 'mainRight'
  if (slots.every((s) => s === 'one')) return 'columns'
  if (slots.every((s, i) => s === 'pair' || (s === 'one' && i === last))) return 'grid'
  if (slots.some((s) => s === 'trio') && slots.every((s, i) => s === 'trio' || (s !== 'big' && i === last))) return 'grid3'
  return 'mixed'
}

/** The current arrangement, as slots. */
export function slotsOf(cols: Col[]): Slot[] {
  const out: Slot[] = []
  cols.forEach((c, i) => {
    if (c.below) return
    if (cols[i + 1]?.below) out.push(cols[i + 2]?.below ? 'trio' : 'pair')
    else out.push(c.half ? 'half' : c.wide ? 'big' : 'one')
  })
  return out
}

/** Columns rearranged into `slots` (in their order; `move` first puts that session in that zone). */
export function arrange(cols: Col[], slots: Slot[], move?: { key: string; zone: number }): Col[] {
  let order = cols.map(({ below: _b, wide: _w, half: _h, ...c }) => c as Col)
  if (move) {
    const m = order.find((c) => c.key === move.key)
    if (m) {
      order = order.filter((c) => c !== m)
      order.splice(Math.max(0, Math.min(order.length, move.zone)), 0, m)
    }
  }
  const out: Col[] = []
  let i = 0
  for (const s of slots) {
    if (i >= order.length) break
    if (s === 'pair' || s === 'trio') {
      out.push(order[i++])
      for (let k = 1; k < slotSize(s) && i < order.length; k++) out.push({ ...order[i++], below: true })
    } else out.push(s === 'big' ? { ...order[i++], wide: true } : s === 'half' ? { ...order[i++], half: true } : order[i++])
  }
  return [...out, ...order.slice(i)]
}

/** Rows of the strip grid, shared by all its columns: a pair splits the height at `split` (its row handle), a trio
 *  in even thirds. The template has one row between every two cuts used; `lines(n, i)` = the grid lines of the
 *  `i`-th session of a stack of `n`. */
export function stripRows(sizes: Iterable<number>, split: number): { template: string; lines: (n: number, i: number) => string } {
  const round = (x: number) => Math.round(x * 1e4) / 1e4
  const span = (n: number, i: number): [number, number] =>
    n === 2 ? (i ? [split, 1] : [0, split]) : [i / n, (i + 1) / n]
  const cuts = new Set<number>([0, 1])
  for (const n of new Set(sizes)) for (let i = 0; i < n; i++) span(n, i).forEach((x) => cuts.add(round(x)))
  const sorted = [...cuts].sort((a, b) => a - b)
  // every session at least ROW_MIN px high: each row between two cuts gets its part of that, for the smallest
  // session it belongs to
  const spans = [...new Set(sizes)].flatMap((n) => Array.from({ length: n }, (_, i) => span(n, i)))
  const template = sorted
    .slice(1)
    .map((x, k) => {
      const lo = sorted[k]
      const seg = round(x - lo)
      const min = Math.max(0, ...spans.filter(([a, b]) => round(a) <= lo && round(b) >= x).map(([a, b]) => (ROW_MIN * seg) / (b - a)))
      return `minmax(${Math.round(min)}px, ${seg}fr)`
    })
    .join(' ')
  const line = (x: number) => sorted.indexOf(round(x)) + 1
  return { template, lines: (n, i) => (n === 1 ? '1 / -1' : span(n, i).map(line).join(' / ')) }
}
