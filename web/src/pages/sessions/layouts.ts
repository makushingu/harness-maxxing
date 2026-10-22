// Ready-made layouts of the sessions strip (the "snap layouts" shown when hovering a column's grip or the grid
// button). A layout is a list of strip columns, left to right: `one` session, a `big` one (two shares of the
// width) or a `pair` stacked top / bottom. Zones are numbered left to right, top before bottom.
import type { Col } from './store'

export type Slot = 'one' | 'big' | 'pair'

/** Narrowest a strip column gets before the strip scrolls. */
export const MIN_W = 380

export const zones = (slots: Slot[]) => slots.reduce((n, s) => n + (s === 'pair' ? 2 : 1), 0)
export const layoutId = (slots: Slot[]) => slots.join('-')

const L = (...slots: Slot[]) => slots
const pairs = (n: number): Slot[] => [...Array<Slot>(Math.floor(n / 2)).fill('pair'), ...(n % 2 ? ['one' as Slot] : [])]

/** The layouts offered for `n` open sessions (none under 2): every session gets a place (no layout leaves one out),
 *  the simplest first, a big one on the left then its mirror. */
export function layoutsFor(n: number): Slot[][] {
  if (n < 2) return []
  if (n === 2) return [L('one', 'one'), L('big', 'one'), L('one', 'big'), L('pair')]
  if (n === 3) return [L('one', 'one', 'one'), L('big', 'pair'), L('pair', 'big'), L('one', 'pair')]
  if (n === 4) return [L('pair', 'pair'), L('one', 'one', 'one', 'one'), L('big', 'one', 'pair'), L('pair', 'one', 'big')]
  const grid = pairs(n)
  return [grid, ['big' as Slot, ...pairs(n - 1)], [...pairs(n - 1), 'big' as Slot], Array<Slot>(n).fill('one')]
}

/** Strip columns a layout needs. */
export const columnsOf = (slots: Slot[]) => slots.length

/** The layouts that fit `room` px (each strip column at least `minW`); never none: the narrowest one stays. */
export function fitting(all: Slot[][], room: number, minW: number): Slot[][] {
  const max = Math.max(1, Math.floor(room / minW))
  const ok = all.filter((l) => columnsOf(l) <= max)
  return ok.length ? ok : [all.reduce((a, b) => (columnsOf(b) < columnsOf(a) ? b : a))]
}

/** What a layout is called (i18n key suffix). */
export function layoutName(slots: Slot[]): 'columns' | 'grid' | 'mainLeft' | 'mainRight' | 'stacked' | 'mixed' {
  if (slots.length === 1 && slots[0] === 'pair') return 'stacked'
  if (slots[0] === 'big') return 'mainLeft'
  if (slots[slots.length - 1] === 'big') return 'mainRight'
  if (slots.every((s) => s === 'one')) return 'columns'
  if (slots.every((s, i) => s === 'pair' || (s === 'one' && i === slots.length - 1))) return 'grid'
  return 'mixed'
}

/** The current arrangement, as slots. */
export function slotsOf(cols: Col[]): Slot[] {
  const out: Slot[] = []
  cols.forEach((c, i) => {
    if (c.below) return
    out.push(cols[i + 1]?.below ? 'pair' : c.wide ? 'big' : 'one')
  })
  return out
}

/** Columns rearranged into `slots` (in their order; `move` first puts that session in that zone). */
export function arrange(cols: Col[], slots: Slot[], move?: { key: string; zone: number }): Col[] {
  let order = cols.map(({ below: _b, wide: _w, ...c }) => c as Col)
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
    if (s === 'pair') {
      out.push(order[i++])
      if (i < order.length) out.push({ ...order[i++], below: true })
    } else out.push(s === 'big' ? { ...order[i++], wide: true } : order[i++])
  }
  return [...out, ...order.slice(i)]
}
