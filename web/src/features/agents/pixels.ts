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
  skin: ['light', 'tan', 'brown', 'dark', 'olive'],
  hair: ['none', 'short', 'spiky', 'long', 'curly', 'bun', 'afro', 'ponytail', 'mohawk', 'buzz', 'bobcut', 'braids', 'pigtails', 'spacebuns', 'swept', 'frog', 'bigbrain', 'chad'],
  hair_color: ['black', 'brown', 'blond', 'red', 'white'],
  face: ['smile', 'happy', 'focused', 'sleepy', 'wink', 'surprised', 'grin', 'cheeky', 'calm'],
  accessory: ['none', 'glasses', 'headphones', 'cap', 'crown', 'antenna'],
} as const
export type AvatarPart = keyof typeof AVATAR_OPTIONS
export const AVATAR_PARTS = Object.keys(AVATAR_OPTIONS) as AvatarPart[]
export const DEFAULT_AVATAR: AgentAvatar = { color: 'blue', skin: 'light', hair: 'short', hair_color: 'brown', face: 'smile', accessory: 'none' }

/** Outfit = the UI accent colours (lib/accent.ts, bright step), its collar a darker shade of it. */
export const OUTFIT: Record<string, string> = ACCENT_HEX.dark
export const SKIN: Record<string, string> = { light: '#ffdcc2', tan: '#e8ad7e', brown: '#b0744a', dark: '#7a4b2e', olive: '#f2c196' }
/** Random characters: 4 in 5 have a matte or lightly matte skin, the others any of the rest. */
export const MATTE_SKINS = ['olive', 'tan'] as const
export const MATTE_SHARE = 0.8
export const HAIR: Record<string, string> = { black: '#3a3444', brown: '#7c4a29', blond: '#ecc457', red: '#cc5a32', white: '#e6e6ee' }
const INK = '#1d1924'

type Layer = { y: number; rows: string[] }
const L = (y: number, ...rows: string[]): Layer => ({ y, rows })
const rep = (n: number, row: string) => Array<string>(n).fill(row)

// ---- the body: one head shape (rows 3-11), a bust (rows 12-15) ----
const HEAD = L(3, '.....sss', '....ssss', ...rep(5, '...sssss'), '....ssss', '.....sss')
/** First row of the bust: what is above it nods. */
const NECK = 12
const SHIRT = L(NECK, '...cccCs', ...rep(3, '..cccccc'))
const BLUSH = L(9, '....b...')

// ---- hair: front (over the head) and back (behind the head, over the shoulders) ----
const HAIR_FRONT: Record<string, Layer> = {
  short: L(2, '.....hhh', '....hhhh', '...hhhhh', '...hhhhh', '...h....'),
  spiky: L(1, '...h..h.', '...hh.hh', '...hhhhh', '...hhhhh', '...hh.hh', '...h....'),
  long: L(2, '.....hhh', '....hhhh', '...hhhhh', '...hhhhh', '...h....', '...h....', '...h....'),
  curly: L(1, '....hh.h', '...hhhhh', '..hhhhhh', '..hhhhhh', '..hhh...', '..hh....', '..hh....', '..hh....'),
  bun: L(0, '......hh', '......hh', '.....hhh', '....hhhh', '...hhhhh', '...hhhhh', '...h....'),
  afro: L(0, '....hhhh', '..hhhhhh', '.hhhhhhh', '.hhhhhhh', '.hhhhhhh', '.hhhhhhh', '.hh.....', '.hh.....', '..h.....'),
  ponytail: L(2, '.....hhh', '....hhhh', '...hhhhh', '...hhhhh', '...h....'),
  mohawk: L(0, '.......h', '.......h', '.......h', '.......h', '......hh'),
  buzz: L(3, '.....hhh', '....hhhh', '...h....'),
  bobcut: L(2, '.....hhh', '....hhhh', '...hhhhh', '..hhhhhh', '..hh....', '..hh....', '..hh....', '..hh....', '..hhh...'),
  braids: L(2, '.....hhh', '....hhhh', '...hhhhh', '...hhh.h', '...h....'),
  pigtails: L(2, '.....hhh', '....hhhh', '...hhhhh', '...hhhhh', '...h....'),
  spacebuns: L(0, '..hh....', '.hhhh...', '.hhhhhhh', '...hhhhh', '...hhhhh', '...h....'),
  swept: L(2, '.....hhhhhh.....', '....hhhhhhhh....', '...hhhhhhhhhh...', '...hhhhhhh..h...', '...h........h...', '...h............'),
}
const HAIR_BACK: Record<string, Layer> = {
  long: L(5, ...rep(9, '..hh....')),
  curly: L(9, '..hh....', '..hh....'),
  ponytail: L(3, '.............hh.', '.............hh.', '..............hh', '..............hh', '.............hh.', '............hh..'),
  braids: L(6, ...rep(9, '.hh.....')),
  pigtails: L(3, '.hh.....', 'hhh.....', 'hhh.....', 'hhh.....', '.hh.....', '.h......'),
}
/** a few darker pixels: the curls, the knot of the bun */
const HAIR_DARK: Record<string, [number, number][]> = {
  curly: [[5, 3], [10, 3], [3, 5], [8, 4], [12, 5]],
  bun: [[6, 1], [7, 1], [8, 1], [9, 1]],
  afro: [[4, 1], [11, 2], [2, 4], [13, 3], [6, 3], [9, 4], [3, 7], [12, 7]],
  ponytail: [[13, 3], [14, 6]],
  braids: [[1, 7], [2, 9], [1, 11], [2, 13], [14, 7], [13, 9], [14, 11], [13, 13]],
  pigtails: [[2, 4], [13, 4]],
  spacebuns: [[2, 1], [13, 1]],
  swept: [[9, 3], [7, 5]],
}

// ---- special characters: picked as a hair style, they replace the whole head (hair, face and accessory are not
// drawn; the outfit, the breath, the blink, the glance and the sleep stay). Never picked at random. ----
type Special = { body: Layer; bust?: Layer; eyes: Layer; blink: Layer; asleep: Layer }
export const SPECIALS: Record<string, Special> = {
  // a round green frog: eyes on top of the head, a wide smile, a light chin
  frog: {
    body: L(1, '...fff..', '..fwwwf.', '..fwwwf.', '.fffffff', '.fffffff', '.fbfffff', '.fffffff', '.fkffffF', '..fkkkkk', '...fffff', '....eeee'),
    eyes: L(3, '....k...'),
    blink: L(2, '...fff..', '...kkk..'),
    asleep: L(2, '...fff..', '...kkk..'),
  },
  // a huge folded brain over a small, blank face
  bigbrain: {
    body: L(0, '...mmmmm', '..mMMmmM', '.mmmmMmm', '.mMMmmMM', '.mmmMmmm', '..mMmmMm', '....ssss', '....ssss', '....ssss', '....sskk', '.....sss', '......ss'),
    eyes: L(7, '.....k..'),
    blink: L(7, '....kk..'),
    asleep: L(7, '....kk..'),
  },
  // slicked hair, low brows, a square jaw wider than the neck, stubble, a thick neck
  chad: {
    body: L(1, '....hhhh', '...hhhhh', '...hhhhh', '...hssss', '...sssss', '...skkss', '...sssss', '...ssssn', '..ssssss', '..sddkkk', '..dddddd'),
    bust: L(12, '..cccsss'),
    eyes: L(7, '.....k..'),
    blink: L(7, '....kk..'),
    asleep: L(6, '...sssss', '........', '....kk..'),
  },
}

// ---- faces: eyes (rows 6-8, hidden by the blink) and mouth (rows 9-11): a free row between them, and between
// the eyes and the fringe (checked for every face x hair) ----
const EYES: Record<string, Layer> = {
  smile: L(7, '.....k..', '.....k..'),
  happy: L(7, '.....k..', '....k.k.'),
  focused: L(7, '....kk..', '.....k..'),
  sleepy: L(8, '....kk..'),
  wink: L(7, '.....k..........', '.....k....kk....'),
  surprised: L(7, '....wk....wk....', '....kk....kk....'),
  grin: L(7, '.....k..', '.....k..'),
  cheeky: L(7, '.....k..', '....k.k.'),
  calm: L(7, '....k.k.', '.....k..'),
}
const MOUTHS: Record<string, Layer> = {
  smile: L(10, '......k.', '.......k'),
  happy: L(10, '......kk', '.......r'),
  focused: L(10, '.......k'),
  sleepy: L(10, '.......k'),
  wink: L(10, '......k.', '.......k'),
  surprised: L(9, '.......k', '.......k'),
  grin: L(10, '.....kkk', '......ww'),
  cheeky: L(10, '......kkkk......', '........rr......'),
  calm: L(10, '......kk'),
}
/** the eyes closed, for the blink (none for the faces whose eyes are closed already) */
const BLINK: Record<string, Layer> = {
  smile: L(8, '....kk..'),
  focused: L(7, '....kk..'),
  wink: L(8, '....kk....kk....'),
  surprised: L(8, '....kk..'),
  grin: L(8, '....kk..'),
}
/** the eyes of a character asleep (an agent that is off) */
const ASLEEP = L(8, '....kk..')

// ---- accessories ----
const ACCESSORY: Record<string, Layer> = {
  glasses: L(6, '...gggg.', '...g..gg', '...gggg.'),
  headphones: L(1, '.....ggg', '....g...', '...g....', '..g.....', '.aa.....', '.aa.....', '.aa.....'),
  cap: L(1, '.....aaa', '....aaaa', '....aaaw', '...aaaaa', '..AAAAAA'),
  crown: L(0, '.....y.y', '.....yyy', '.....yyr'),
  antenna: L(0, '..........aa....', '..........aa....', '..........g.....'),
}
/** accessories that hide the hair above this row */
const COVER: Record<string, number> = { cap: 6 }

const rowOf = (r: string) => (r.length === GRID ? r : r + [...r].reverse().join(''))

function paint(grid: (string | null)[], layer: Layer | undefined, from = 0) {
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
    // special characters: frog greens, brain pinks, stubble and nose (shades of the skin)
    f: '#5fb54a', F: '#3f8a33', e: '#a8d98a', m: '#f4a6c0', M: '#c96a8e', d: darken(s, 0.35), n: darken(s, 0.15),
  }
}

export type Run = { x: number; y: number; w: number; fill: string }
/** `head` + `bust` = `body` split at the neck (the head nods on its own). */
/** `look` = how far the eyes may glance left / right (0 or 1 pixel): only onto bare skin, never over hair, glasses
 *  or out of the face. */
type Pixels = { body: Run[]; head: Run[]; bust: Run[]; eyes: Run[]; blink: Run[]; tile: string; look: [number, number] }

function runs(grid: (string | null)[], pal: Record<string, string>): Run[] {
  const out: Run[] = []
  for (let y = 0; y < GRID; y++)
    for (let x = 0, w = 1; x < GRID; x += w) {
      const c = grid[y * GRID + x]
      for (w = 1; x + w < GRID && grid[y * GRID + x + w] === c; ) w++
      if (c) out.push({ x, y, w, fill: pal[c] || INK })
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
  const blank = (): (string | null)[] => Array(GRID * GRID).fill(null)
  const g = blank()
  const sp = SPECIALS[a.hair]
  const eyes = blank()
  if (sp) {
    paint(g, SHIRT)
    paint(g, sp.bust)
    paint(g, sp.body)
    paint(eyes, sleep ? sp.asleep : sp.eyes)
  } else {
    paint(g, SHIRT)
    paint(g, HAIR_BACK[a.hair])
    paint(g, HEAD)
    paint(g, BLUSH)
    paint(g, HAIR_FRONT[a.hair], COVER[a.accessory] ?? 0)
    for (const [x, y] of HAIR_DARK[a.hair] || []) if (g[y * GRID + x] === 'h') g[y * GRID + x] = 'j'
    paint(g, sleep ? MOUTHS.sleepy : MOUTHS[a.face])
    // The face goes in its own layer (the blink hides it), the glasses over it.
    paint(eyes, sleep ? ASLEEP : EYES[a.face])
    paint(g, ACCESSORY[a.accessory])
  }
  // How far the eyes can glance: every open-eye pixel must land on skin or an eye white (the blink stays in place).
  const glance = (dx: number) => {
    for (let i = 0; i < eyes.length; i++) {
      if (!eyes[i]) continue
      const x = (i % GRID) + dx
      if (x < 0 || x >= GRID || !['s', 'b', 'w', 'f'].includes(g[i + dx] || '') || (g[i] === 'w' && g[i + dx] !== 'w')) return 0
    }
    return 1
  }
  const look: [number, number] = [glance(-1), glance(1)]
  // Ink outline around the silhouette (4 neighbours), so the character reads on any background.
  const filled = g.slice()
  const at = (x: number, y: number) => x >= 0 && x < GRID && y >= 0 && y < GRID && !!filled[y * GRID + x]
  for (let y = 0; y < GRID; y++)
    for (let x = 0; x < GRID; x++) if (!filled[y * GRID + x] && (at(x + 1, y) || at(x - 1, y) || at(x, y + 1) || at(x, y - 1))) g[y * GRID + x] = 'o'
  const blink = blank()
  if (!sleep) paint(blink, sp ? sp.blink : BLINK[a.face])
  // the outline only fills empty cells: the glasses' cells are the same as before it
  if (!sp && a.accessory === 'glasses') for (let i = 0; i < g.length; i++) if (g[i] === 'g') eyes[i] = blink[i] = null
  const body = runs(g, pal)
  const out = { body, head: body.filter((r) => r.y < NECK), bust: body.filter((r) => r.y >= NECK), eyes: runs(eyes, pal), blink: runs(blink, pal), tile: sleep ? grey(pal.c) : pal.c, look }
  cache.set(key, out)
  return out
}

/** The character as SVG markup (16x16 viewBox, no tile), for what cannot render React: the Office views of
 *  extensions get it with each agent (`avatar_svg`, an <img src="data:image/svg+xml,..."> or innerHTML). */
export function avatarSvg(a: AgentAvatar, sleep = false): string {
  const px = pixelsOf(a, sleep)
  const rects = [...px.body, ...px.eyes].map((r) => `<rect x="${r.x}" y="${r.y}" width="${r.w}" height="1" fill="${r.fill}"/>`).join('')
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${GRID} ${GRID}" shape-rendering="crispEdges">${rects}</svg>`
}

const pick = (part: AvatarPart, v: string | undefined): string =>
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

/** A random character; `color` = its outfit (its project's: useProjectColorOf in layout.tsx). Accessories stay rare
 *  (one in two has none). */
export function randomAvatar(color?: string): AgentAvatar {
  const r = <K extends AvatarPart>(k: K): string => AVATAR_OPTIONS[k][Math.floor(Math.random() * AVATAR_OPTIONS[k].length)]
  const out = {} as AgentAvatar
  for (const k of AVATAR_PARTS) out[k] = r(k)
  while (SPECIALS[out.hair]) out.hair = r('hair')
  const others = AVATAR_OPTIONS.skin.filter((s) => !(MATTE_SKINS as readonly string[]).includes(s))
  const pool: readonly string[] = Math.random() < MATTE_SHARE ? MATTE_SKINS : others
  out.skin = pool[Math.floor(Math.random() * pool.length)]
  if (Math.random() < 0.5) out.accessory = 'none'
  if (color) out.color = color
  return out
}
