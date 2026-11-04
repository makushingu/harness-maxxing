// The pixel art behind an agent's face (Avatar.tsx draws it): a 16x16 grid painted from a few small maps, one per
// part (back hair, shirt, head, hair, face, accessory), then outlined in ink where the character meets the empty
// grid. Flat colours, no shading: it must read at 16 px and stay calm at 96 px. Pure data + functions, no React (a
// script can render contact sheets with it).
//
// Map rows: 16 characters = the row as is; 8 characters = the left half, mirrored (faces stay symmetric).
// '.' = nothing; the other letters are colour roles resolved by `palette()` below.
import type { AgentAvatar } from '@/lib/types'
import { ACCENT_HEX } from '@/lib/accent'

export const GRID = 16

/** = agents.AVATAR on the server (same names, same order). */
export const AVATAR_OPTIONS = {
  color: ['blue', 'clay', 'violet', 'green', 'amber', 'rose'],
  skin: ['light', 'tan', 'brown', 'dark'],
  hair: ['none', 'short', 'spiky', 'long', 'curly', 'bun'],
  hair_color: ['black', 'brown', 'blond', 'red', 'white'],
  face: ['smile', 'happy', 'focused', 'sleepy', 'wink', 'surprised'],
  accessory: ['none', 'glasses', 'headphones', 'cap', 'crown', 'antenna'],
} as const
export type AvatarPart = keyof typeof AVATAR_OPTIONS
export const AVATAR_PARTS = Object.keys(AVATAR_OPTIONS) as AvatarPart[]
export const DEFAULT_AVATAR: AgentAvatar = { color: 'blue', skin: 'light', hair: 'short', hair_color: 'brown', face: 'smile', accessory: 'none' }

/** Outfit = the UI accent colours (lib/accent.ts, bright step), its collar a darker shade of it. */
export const OUTFIT: Record<string, string> = ACCENT_HEX.dark
export const SKIN: Record<string, string> = { light: '#ffdcc2', tan: '#e8ad7e', brown: '#b0744a', dark: '#7a4b2e' }
export const HAIR: Record<string, string> = { black: '#3a3444', brown: '#7c4a29', blond: '#ecc457', red: '#cc5a32', white: '#e6e6ee' }
export const INK = '#1d1924'

type Layer = { y: number; rows: string[] }
const L = (y: number, ...rows: string[]): Layer => ({ y, rows })
const rep = (n: number, row: string) => Array<string>(n).fill(row)

// ---- the body: one head shape (rows 3-11), a bust (rows 12-15) ----
const HEAD = L(3, '.....sss', '....ssss', ...rep(5, '...sssss'), '....ssss', '.....sss')
const SHIRT = L(12, '...cccCs', ...rep(3, '..cccccc'))
const BLUSH = L(9, '....b...')

// ---- hair: front (over the head) and back (behind the head, over the shoulders) ----
const HAIR_FRONT: Record<string, Layer | null> = {
  none: null,
  short: L(2, '.....hhh', '....hhhh', '...hhhhh', '...hhhhh', '...h....'),
  spiky: L(1, '...h..h.', '...hh.hh', '...hhhhh', '...hhhhh', '...hh.hh', '...h....'),
  long: L(2, '.....hhh', '....hhhh', '...hhhhh', '...hhhhh', '...hh...', '...h....', '...h....'),
  curly: L(1, '....hh.h', '...hhhhh', '..hhhhhh', '..hhhhhh', '..hhhhhh', '..hhh...', '..hh....', '..hh....'),
  bun: L(0, '......hh', '......hh', '.....hhh', '....hhhh', '...hhhhh', '...hhhhh', '...h....'),
}
const HAIR_BACK: Record<string, Layer> = {
  long: L(5, ...rep(9, '..hh....')),
  curly: L(9, '..hh....', '..hh....'),
}
/** a few darker pixels: the curls, the knot of the bun */
const HAIR_DARK: Record<string, [number, number][]> = {
  curly: [[5, 3], [10, 3], [3, 5], [8, 4], [12, 5]],
  bun: [[6, 1], [7, 1], [8, 1], [9, 1]],
}

// ---- faces: eyes (rows 6-8, hidden by the blink) and mouth (rows 9-10) ----
const EYES: Record<string, Layer> = {
  smile: L(7, '.....k..', '.....k..'),
  happy: L(7, '.....k..', '....k.k.'),
  focused: L(6, '....kk..', '.....k..', '.....k..'),
  sleepy: L(8, '....kk..'),
  wink: L(7, '.....k..........', '.....k....kk....'),
  surprised: L(7, '....wk....wk....', '....kk....kk....'),
}
const MOUTHS: Record<string, Layer> = {
  smile: L(9, '......k.', '.......k'),
  happy: L(9, '......kk', '.......r'),
  focused: L(10, '.......k'),
  sleepy: L(10, '.......k'),
  wink: L(9, '......k.', '.......k'),
  surprised: L(9, '.......k', '.......k'),
}
/** the eyes closed, for the blink (none for the faces whose eyes are closed already) */
const BLINK: Record<string, Layer | null> = {
  smile: L(8, '....kk..'),
  focused: L(6, '....kk..', '........', '....kk..'),
  wink: L(8, '....kk....kk....'),
  surprised: L(8, '....kk..'),
  happy: null,
  sleepy: null,
}
/** the eyes of a character asleep (an agent that is off) */
const ASLEEP = L(8, '....kk..')

// ---- accessories ----
const ACCESSORY: Record<string, Layer | null> = {
  none: null,
  glasses: L(6, '...gggg.', '...g..gg', '...gggg.'),
  headphones: L(1, '.....ggg', '....g...', '...g....', '..g.....', '.aa.....', '.aa.....', '.aa.....'),
  cap: L(1, '.....aaa', '....aaaa', '....aaaw', '...aaaaa', '..AAAAAA'),
  crown: L(0, '.....y.y', '.....yyy', '.....yyr'),
  antenna: L(0, '..........aa....', '..........aa....', '..........g.....'),
}
/** accessories that hide the hair above this row */
const COVER: Record<string, number> = { cap: 6 }

const rowOf = (r: string) => (r.length === GRID ? r : r + [...r].reverse().join(''))

function paint(grid: (string | null)[], layer: Layer | null, from = 0) {
  if (!layer) return
  layer.rows.forEach((raw, dy) => {
    const y = layer.y + dy
    if (y < from) return
    const r = rowOf(raw)
    for (let x = 0; x < GRID; x++) if (r[x] !== '.') grid[y * GRID + x] = r[x]
  })
}

/** `hex` mixed with black (amount 0..1). */
function darken(hex: string, amount: number): string {
  const n = parseInt(hex.slice(1), 16)
  const ch = (v: number) => Math.round(v * (1 - amount)).toString(16).padStart(2, '0')
  return `#${ch(n >> 16)}${ch((n >> 8) & 255)}${ch(n & 255)}`
}

function palette(a: AgentAvatar): Record<string, string> {
  const c = OUTFIT[a.color]
  const s = SKIN[a.skin]
  return {
    o: INK, k: INK, w: '#ffffff', r: '#e5484d', g: '#3f3a4a', G: '#6f6a7c',
    s, b: a.skin === 'dark' || a.skin === 'brown' ? '#d97b7b' : '#f7a7a7',
    h: HAIR[a.hair_color], j: darken(HAIR[a.hair_color], 0.25),
    c, C: darken(c, 0.28), a: c, A: darken(c, 0.28),
    y: '#f5c518', Y: '#c99a06',
  }
}

export type Run = { x: number; y: number; w: number; fill: string }
export type Pixels = { body: Run[]; eyes: Run[]; blink: Run[]; tile: string }

function runs(grid: (string | null)[], pal: Record<string, string>): Run[] {
  const out: Run[] = []
  for (let y = 0; y < GRID; y++) {
    let x = 0
    while (x < GRID) {
      const c = grid[y * GRID + x]
      if (!c) {
        x++
        continue
      }
      let w = 1
      while (x + w < GRID && grid[y * GRID + x + w] === c) w++
      out.push({ x, y, w, fill: pal[c] || INK })
      x += w
    }
  }
  return out
}

/** A colour in greys (same lightness), for a sleeping character. */
function grey(hex: string): string {
  const n = parseInt(hex.slice(1), 16)
  const l = Math.round(0.3 * (n >> 16) + 0.59 * ((n >> 8) & 255) + 0.11 * (n & 255))
  return `#${l.toString(16).padStart(2, '0').repeat(3)}`
}

const cache = new Map<string, Pixels>()

/** The runs of pixels (one <rect> each) of a character; `sleep` closes its eyes and greys it (an agent that is
 *  off). Cached: lists draw the same faces often. */
export function pixelsOf(a: AgentAvatar, sleep = false): Pixels {
  const key = `${AVATAR_PARTS.map((k) => a[k]).join('.')}:${sleep ? 1 : 0}`
  const hit = cache.get(key)
  if (hit) return hit
  const pal = palette(a)
  if (sleep) for (const k in pal) if (k !== 'o' && k !== 'k') pal[k] = grey(pal[k])
  const g: (string | null)[] = Array(GRID * GRID).fill(null)
  paint(g, SHIRT)
  paint(g, HAIR_BACK[a.hair] || null)
  paint(g, HEAD)
  paint(g, BLUSH)
  paint(g, HAIR_FRONT[a.hair], COVER[a.accessory] ?? 0)
  for (const [x, y] of HAIR_DARK[a.hair] || []) if (g[y * GRID + x] === 'h') g[y * GRID + x] = 'j'
  paint(g, sleep ? MOUTHS.sleepy : MOUTHS[a.face])
  // The face goes in its own layer (the blink hides it), the glasses over it.
  const eyes: (string | null)[] = Array(GRID * GRID).fill(null)
  paint(eyes, sleep ? ASLEEP : EYES[a.face])
  paint(g, ACCESSORY[a.accessory])
  if (a.accessory === 'glasses') for (let i = 0; i < eyes.length; i++) if (g[i] === 'g') eyes[i] = null
  // Ink outline around the silhouette (4 neighbours), so the character reads on any background.
  const filled = g.slice()
  const at = (x: number, y: number) => x >= 0 && x < GRID && y >= 0 && y < GRID && !!filled[y * GRID + x]
  for (let y = 0; y < GRID; y++)
    for (let x = 0; x < GRID; x++) if (!filled[y * GRID + x] && (at(x + 1, y) || at(x - 1, y) || at(x, y + 1) || at(x, y - 1))) g[y * GRID + x] = 'o'
  const blink: (string | null)[] = Array(GRID * GRID).fill(null)
  if (!sleep) paint(blink, BLINK[a.face])
  if (a.accessory === 'glasses') for (let i = 0; i < blink.length; i++) if (g[i] === 'g') blink[i] = null
  const out = { body: runs(g, pal), eyes: runs(eyes, pal), blink: runs(blink, pal), tile: sleep ? grey(pal.c) : pal.c }
  cache.set(key, out)
  return out
}

export const pick = (part: AvatarPart, v: string | undefined): string =>
  (AVATAR_OPTIONS[part] as readonly string[]).includes(v || '') ? v! : DEFAULT_AVATAR[part]

/** Every part checked (an unknown value falls back to the default). */
export function normalize(a?: Partial<AgentAvatar> | null): AgentAvatar {
  const out = {} as AgentAvatar
  for (const k of AVATAR_PARTS) out[k] = pick(k, a?.[k])
  return out
}

/** The outfit colour of a project's agents: FNV-1a over its name (= agents.project_color() on the server). */
export function projectColor(project: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < project.length; i++) h = Math.imul(h ^ project.charCodeAt(i), 0x01000193) >>> 0
  return AVATAR_OPTIONS.color[h % AVATAR_OPTIONS.color.length]
}

/** A random character; `project` keeps its outfit colour. Accessories stay rare (one in two has none). */
export function randomAvatar(project?: string): AgentAvatar {
  const r = <K extends AvatarPart>(k: K): string => AVATAR_OPTIONS[k][Math.floor(Math.random() * AVATAR_OPTIONS[k].length)]
  const out = {} as AgentAvatar
  for (const k of AVATAR_PARTS) out[k] = r(k)
  if (Math.random() < 0.5) out.accessory = 'none'
  if (project) out.color = projectColor(project)
  return out
}
