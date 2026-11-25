/** Widths of the two sidebars (Sidebar.tsx, PageList.tsx SecondBar) that always leave the page MAIN_MIN pixels:
 * the widths dragged at 440 + 520 px on a large screen are kept, and shown narrower on a smaller window. */
export const MAIN_MIN = 480

type Range = { min: number; max: number }

/** The main sidebar: room is kept for the second one at its smallest. */
export function sideMax(vw: number, side: Range, second: Range): number {
  return Math.max(side.min, Math.min(side.max, vw - MAIN_MIN - second.min))
}

/** The second-level sidebar, right of a main sidebar `left` pixels wide. */
export function secondMax(vw: number, left: number, second: Range): number {
  return Math.max(second.min, Math.min(second.max, vw - MAIN_MIN - left))
}
