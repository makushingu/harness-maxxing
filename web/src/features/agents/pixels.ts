// The pixel art behind an agent's face (Avatar.tsx draws it): a 20x20 grid built from small pixel maps, one per
// part, painted in order (tile, back hair, shirt, head, hair, face, hat), then outlined in ink where the character
// meets the empty grid. Pure data + functions, no React (so a script can render contact sheets).
//
// Map rows: 20 characters = the row as is; 10 characters = the left half, mirrored (faces stay symmetric).
// '.' = nothing; the other letters are colour roles resolved by `palette()` below.
import type { AgentAvatar } from '@/lib/types'

export const GRID = 20

export const AVATAR_OPTIONS = {
  color: ['violet', 'blue', 'teal', 'green', 'amber', 'orange', 'rose', 'slate'],
  eyes: ['dots', 'happy', 'wide', 'sleepy', 'wink', 'visor', 'glasses', 'angry'],
  mouth: ['smile', 'grin', 'flat', 'open', 'smirk', 'tongue', 'mustache'],
  hat: ['none', 'antenna', 'cap', 'beanie', 'crown', 'headphones', 'wizard', 'bow'],
  bg: ['violet', 'blue', 'teal', 'green', 'amber', 'orange', 'rose', 'slate'],
  skin: ['light', 'fair', 'tan', 'brown', 'dark', 'green', 'blue', 'metal'],
  head: ['round', 'square', 'long', 'wide'],
  hair: ['none', 'short', 'spiky', 'long', 'bob', 'mohawk', 'curly', 'bun', 'side'],
  hair_color: ['black', 'brown', 'blond', 'red', 'white', 'pink', 'blue', 'green'],
} as const
export type AvatarPart = keyof typeof AVATAR_OPTIONS
export const DEFAULT_AVATAR: AgentAvatar = {
  color: 'violet', eyes: 'dots', mouth: 'smile', hat: 'antenna', bg: 'slate',
  skin: 'light', head: 'round', hair: 'short', hair_color: 'brown',
}

/** Outfit / tile colours: body, shade, light, tile (background) and tile2 (its lower band), hat = the hat's colour. */
export const SWATCH: Record<string, { body: string; shade: string; light: string; tile: string; tile2: string; hat: string }> = {
  violet: { body: '#8b5cf6', shade: '#6d28d9', light: '#a78bfa', tile: '#ddd6fe', tile2: '#c4b5fd', hat: 'amber' },
  blue: { body: '#3b82f6', shade: '#1d4ed8', light: '#60a5fa', tile: '#bfdbfe', tile2: '#93c5fd', hat: 'amber' },
  teal: { body: '#14b8a6', shade: '#0f766e', light: '#2dd4bf', tile: '#99f6e4', tile2: '#5eead4', hat: 'rose' },
  green: { body: '#22c55e', shade: '#15803d', light: '#4ade80', tile: '#bbf7d0', tile2: '#86efac', hat: 'violet' },
  amber: { body: '#f59e0b', shade: '#b45309', light: '#fbbf24', tile: '#fde68a', tile2: '#fcd34d', hat: 'blue' },
  orange: { body: '#f97316', shade: '#c2410c', light: '#fb923c', tile: '#fed7aa', tile2: '#fdba74', hat: 'teal' },
  rose: { body: '#f43f5e', shade: '#be123c', light: '#fb7185', tile: '#fecdd3', tile2: '#fda4af', hat: 'teal' },
  slate: { body: '#64748b', shade: '#334155', light: '#94a3b8', tile: '#e2e8f0', tile2: '#cbd5e1', hat: 'amber' },
}
/** skin: base, shade, light */
export const SKIN: Record<string, [string, string, string]> = {
  light: ['#ffe1cc', '#f0bb9c', '#fff1e6'],
  fair: ['#f8c9a0', '#e0a47a', '#ffdcbc'],
  tan: ['#dc9d6b', '#bd7d4c', '#eab48a'],
  brown: ['#a8693f', '#8a522d', '#bd7f53'],
  dark: ['#80502f', '#633b22', '#9a6646'],
  green: ['#8fd97a', '#62b552', '#b4eca4'],
  blue: ['#8ec3f5', '#5f9ae0', '#b9dafa'],
  metal: ['#c5ccd8', '#8c96a8', '#eef1f6'],
}
/** hair: base, light, dark */
export const HAIR: Record<string, [string, string, string]> = {
  black: ['#2e2838', '#544a68', '#17131d'],
  brown: ['#7b4a26', '#a5683a', '#5a3519'],
  blond: ['#f0c445', '#ffe58f', '#c99a1e'],
  red: ['#d4502a', '#f07a48', '#a83a1b'],
  white: ['#e6e7ee', '#ffffff', '#b4b8c8'],
  pink: ['#f472b6', '#f9a8d4', '#db2777'],
  blue: ['#3b82f6', '#93c5fd', '#1d4ed8'],
  green: ['#22c55e', '#86efac', '#15803d'],
}
export const INK = '#1f1830'

type Layer = { y: number; rows: string[] }
const L = (y: number, ...rows: string[]): Layer => ({ y, rows })
const rep = (n: number, row: string) => Array<string>(n).fill(row)

// ---- heads (skin), all with the same top so hair and hats fit every shape ----
const HEADS: Record<string, Layer> = {
  round: L(4, '......ssss', '.....sssss', ...rep(6, '....ssssss'), '.....sssss', '......ssss', '........dd'),
  square: L(4, '.....sssss', ...rep(9, '....ssssss'), '........dd'),
  long: L(4, '......ssss', ...rep(8, '.....sssss'), '......ssss', '.......sss'),
  wide: L(4, '......ssss', '....ssssss', ...rep(6, '...sssssss'), '....ssssss', '......ssss', '........dd'),
}
const SHIRT = L(
  15,
  '.....cccLddLccc.....',
  '...cLccccLLccccCC...',
  '..cLcccccccccccccC..',
  '..ccccccccccccccCC..',
  '..ccccccccccccccCC..',
)
const BLUSH = L(10, '.....bb...')

// ---- hair: front (over the head) and back (behind the head and the shirt) ----
const HAIR_FRONT: Record<string, Layer | null> = {
  none: null,
  short: L(2, '.......hhh', '.....hhhhh', '....hhhhhh', '...hhhhhhh', '...hhhhhhh', '...hh.....', '...h......'),
  spiky: L(0, '....h....h', '....hh..hh', '....hhhhhh', '...hhhhhhh', '..hhhhhhhh', '...hhhhhhh', '...hh.h...', '...h......'),
  long: L(2, '.......hhh', '.....hhhhh', '....hhhhhh', '...hhhhhhh', '...hhhhh..', '...hhh....', ...rep(8, '...hh.....'), '....h.....'),
  bob: L(2, '.......hhh', '.....hhhhh', '....hhhhhh', '...hhhhhhh', '..hhhhhhhh', ...rep(5, '..hhh.....'), '...hh.....'),
  mohawk: L(0, '.........h', '........hh', '........hh', '........hh', '........hh', '.........h'),
  curly: L(1, '......hh.h', '....hhhhhh', '...hhhhhhh', '..hhhhhhhh', '.hhhhhhhhh', '..hhhhhhhh', '..hhh.h...', '.hhhh.....', '..hhh.....', '...hh.....'),
  bun: L(0, '........hh', '.......hhh', '........hh', '.....hhhhh', '....hhhhhh', '...hhhhhhh', '...hhh....', '...hh.....', '...h......'),
  side: L(
    2,
    '.......hhhhhh.......',
    '.....hhhhhhhhhh.....',
    '....hhhhhhhhhhhh....',
    '...hhhhhhhhhhhhhh...',
    '...hhhhhhhhhhhhhh...',
    '...hhhhhhhh....hh...',
    '...hhhh.........h...',
    '...hh...............',
  ),
}
const HAIR_BACK: Record<string, Layer> = {
  long: L(6, ...rep(11, '..jjjjjjjj')),
  bob: L(7, ...rep(5, '..jjjjjjjj')),
  curly: L(6, ...rep(5, '..jjjjjjjj')),
}
/** a few lighter pixels on the left (light comes from the top left) */
const HAIR_SHINE: Record<string, [number, number][]> = {
  short: [[6, 3], [7, 3], [5, 4]],
  spiky: [[5, 2], [6, 3], [5, 3]],
  long: [[6, 3], [7, 3], [5, 4]],
  bob: [[6, 3], [7, 3], [5, 4]],
  mohawk: [[9, 1], [9, 2]],
  curly: [[6, 2], [9, 3], [4, 4], [12, 3], [3, 6], [7, 4], [15, 5]],
  bun: [[9, 0], [6, 4], [7, 4]],
  side: [[7, 3], [8, 3], [6, 4]],
}

// ---- eyes (y 7..10) and mouths (y 11..13) ----
const EYES: Record<string, Layer> = {
  dots: L(8, '......kw....kw......', '......kk....kk......'),
  happy: L(8, '......kk..', '.....k..k.'),
  wide: L(7, '.....kkk..', '.....kkw....kkw.....', '.....kkk..'),
  sleepy: L(8, '.....ddd..', '.....kkk..'),
  wink: L(8, '......kw....kk......', '......kk...k..k.....'),
  visor: L(8, '....kggkkk', '....kggkkk'),
  glasses: L(7, '.....kkkk..kkkk.....', '.....kwwkkkkwwk.....', '.....kwkk..kkwk.....', '.....kkkk..kkkk.....'),
  angry: L(7, '.....kk...', '.......k..', '......kk..'),
}
/** the eyes closed, for the blink (none for the eyes that are closed already or hidden) */
const BLINK: Record<string, Layer | null> = {
  dots: L(9, '......kk..'),
  wide: L(9, '.....kkk..'),
  wink: L(9, '......kk...k..k.....'),
  angry: L(9, '......kk..'),
  happy: null,
  sleepy: null,
  visor: null,
  glasses: null,
}
const SLEEP_EYES = L(9, '.....kkk..')
const MOUTHS: Record<string, Layer> = {
  smile: L(11, '........k.', '.........k'),
  grin: L(11, '.......kww', '........kk'),
  flat: L(11, '........kk'),
  open: L(11, '.........k', '........kr', '.........k'),
  smirk: L(11, '...........k........', '........kkk.........'),
  tongue: L(11, '........kk', '..........tt........', '..........tT........'),
  mustache: L(11, '.......mmm', '......mm..'),
}

// ---- hats ----
const HATS: Record<string, Layer | null> = {
  none: null,
  antenna: L(0, '........aa', '........aa', '.........q', '.........q'),
  cap: L(1, '......aaaa', '....aaaaaa', '...aaaaaaw', '...aaaaaaa', '...aaaaaaa', '..AAAAAAAA'),
  beanie: L(0, '.........w', '......aaaa', '....aaaaaa', '...aaaaaaa', '...aaaaaaa', '...AaAaAaA', '...AaAaAaA'),
  crown: L(0, '.....y...y', '.....yy.yy', '.....yyyyy', '.....YYrYY'),
  headphones: L(1, '......qqqq', '....qq....', '...q......', '..q.......', '..q.......', '..q.......', '..aa......', '.aaa......', '.aAa......', '..aa......'),
  wizard: L(
    0,
    '...........a........',
    '..........aa........',
    '.........aaaa.......',
    '........aayaaa......',
    '......aaaaaaaa......',
    '..AAAAAAAAAAAAAAAA..',
  ),
  bow: L(1, '..........aa....aa..', '..........aaaAAaaa..', '..........aaaAAaaa..', '..........aa....aa..'),
}
const HAT_SHINE: Record<string, [number, number][]> = {
  antenna: [[8, 0]],
  cap: [[6, 2], [5, 3]],
  beanie: [[7, 2], [5, 3]],
  crown: [[6, 2]],
  wizard: [[10, 1], [8, 4]],
  bow: [[10, 1], [15, 2]],
}
/** hats that cover the top of the head: the hair above this row is not drawn */
const HAT_COVER: Record<string, number> = { cap: 6, beanie: 6, wizard: 6 }

const rowOf = (r: string) => (r.length === GRID ? r : r + [...r].reverse().join(''))

function paint(grid: (string | null)[], layer: Layer | null, only?: (cur: string | null) => boolean) {
  if (!layer) return
  layer.rows.forEach((raw, dy) => {
    const y = layer.y + dy
    const r = rowOf(raw)
    for (let x = 0; x < GRID; x++) if (r[x] !== '.' && (!only || only(grid[y * GRID + x]))) grid[y * GRID + x] = r[x]
  })
}

const isSkin = (c: string | null) => c === 's' || c === 'd'

function palette(a: AgentAvatar): Record<string, string> {
  const c = SWATCH[a.color]
  const hat = SWATCH[c.hat]
  const [s, sd, sl] = SKIN[a.skin]
  const [h, hl, hd] = HAIR[a.hair_color]
  return {
    o: INK, k: INK, w: '#ffffff', g: '#67e8f9', r: '#9f1239', t: '#fb7185', T: '#e11d48',
    s, d: sd, l: sl, b: a.skin === 'dark' || a.skin === 'brown' ? '#d9707e' : '#f9a0aa',
    h, H: hl, j: hd, m: hd,
    c: c.body, C: c.shade, L: c.light,
    a: hat.body, A: hat.shade, e: hat.light,
    y: '#facc15', Y: '#ca8a04', q: '#475569',
  }
}

export type Run = { x: number; y: number; w: number; fill: string }
export type Pixels = { body: Run[]; eyes: Run[]; blink: Run[] }

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

const cache = new Map<string, Pixels>()

/** A colour in greys (same lightness), for a sleeping character. */
function grey(hex: string): string {
  const n = parseInt(hex.slice(1), 16)
  const l = Math.round(0.3 * (n >> 16) + 0.59 * ((n >> 8) & 255) + 0.11 * (n & 255))
  return `#${l.toString(16).padStart(2, '0').repeat(3)}`
}

/** The runs of pixels (one <rect> each) of a face; `sleep` closes the eyes and greys it (an agent that is off).
 *  Cached: lists draw the same faces often. */
export function pixelsOf(a: AgentAvatar, sleep = false): Pixels {
  const key = `${AVATAR_PARTS.map((k) => a[k]).join('.')}:${sleep ? 1 : 0}`
  const hit = cache.get(key)
  if (hit) return hit
  const pal = palette(a)
  if (sleep) for (const k in pal) pal[k] = grey(pal[k])
  const g: (string | null)[] = Array(GRID * GRID).fill(null)
  paint(g, HAIR_BACK[a.hair] || null)
  paint(g, SHIRT)
  paint(g, HEADS[a.head])
  paint(g, BLUSH, isSkin)
  const cover = HAT_COVER[a.hat] ?? 0
  const front = HAIR_FRONT[a.hair]
  if (front) {
    paint(g, { y: front.y, rows: front.rows.map((r, i) => (front.y + i < cover ? '.'.repeat(GRID) : r)) })
    for (const [x, y] of HAIR_SHINE[a.hair] || []) if (y >= cover && g[y * GRID + x] === 'h') g[y * GRID + x] = 'H'
    // The lowest hair pixel above the face is darker: it draws the line of the fringe.
    for (let i = 0; i < GRID * (GRID - 1); i++) if (g[i] === 'h' && isSkin(g[i + GRID])) g[i] = 'j'
  }
  paint(g, MOUTHS[a.mouth])
  const hat = HATS[a.hat]
  paint(g, hat)
  for (const [x, y] of HAT_SHINE[a.hat] || []) if (g[y * GRID + x] === 'a') g[y * GRID + x] = 'e'
  // Ink outline around the silhouette (4 neighbours), so the character reads on any background.
  const filled = g.slice()
  for (let y = 0; y < GRID; y++)
    for (let x = 0; x < GRID; x++) {
      if (filled[y * GRID + x]) continue
      const n = (dx: number, dy: number) => {
        const X = x + dx
        const Y = y + dy
        return X >= 0 && X < GRID && Y >= 0 && Y < GRID && !!filled[Y * GRID + X]
      }
      if (n(1, 0) || n(-1, 0) || n(0, 1) || n(0, -1)) g[y * GRID + x] = 'o'
    }
  const eyes: (string | null)[] = Array(GRID * GRID).fill(null)
  paint(eyes, sleep ? SLEEP_EYES : EYES[a.eyes])
  const blink: (string | null)[] = Array(GRID * GRID).fill(null)
  paint(blink, sleep ? null : BLINK[a.eyes])
  const out = { body: runs(g, pal), eyes: runs(eyes, pal), blink: runs(blink, pal) }
  cache.set(key, out)
  return out
}

/** The rounded tile behind the character: base colour, a lower band, corners cut by one pixel. */
export function tileRuns(bg: string): Run[] {
  const s = SWATCH[bg]
  const out: Run[] = []
  for (let y = 0; y < GRID; y++) {
    const cut = y === 0 || y === GRID - 1 ? 1 : 0
    out.push({ x: cut, y, w: GRID - 2 * cut, fill: y >= 13 ? s.tile2 : s.tile })
  }
  return out
}

export const AVATAR_PARTS: AvatarPart[] = ['skin', 'head', 'eyes', 'mouth', 'hair', 'hair_color', 'hat', 'color', 'bg']

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

/** A random face; `project` keeps its outfit colour. The tile never takes the outfit colour (it would hide it). */
export function randomAvatar(project?: string): AgentAvatar {
  const r = <K extends AvatarPart>(k: K): string => AVATAR_OPTIONS[k][Math.floor(Math.random() * AVATAR_OPTIONS[k].length)]
  const out = {} as AgentAvatar
  for (const k of AVATAR_PARTS) out[k] = r(k)
  if (project) out.color = projectColor(project)
  if (out.bg === out.color) out.bg = AVATAR_OPTIONS.bg[(AVATAR_OPTIONS.bg.indexOf(out.bg as never) + 3) % AVATAR_OPTIONS.bg.length]
  return out
}
