// Interface and code fonts (Settings > General > Appearance). All are bundled (no network). Only Inter (the
// default) is in the entry CSS; the @font-face rules of the others are loaded on demand (`loadFont`), and a font
// file is only downloaded by the browser once it is used. index.html keeps a copy of the stacks (generated) -
// change both.
export type FontGroup = 'modern' | 'character' | 'rounded' | 'serif' | 'readable' | 'mono' | 'system'

export const SANS_FONTS = {
  inter: { label: "Inter", group: 'modern' as FontGroup, stack: "'Inter Variable', ui-sans-serif, system-ui, sans-serif" },
  geist: { label: "Geist", group: 'modern' as FontGroup, stack: "'Geist Variable', ui-sans-serif, system-ui, sans-serif" },
  plex: { label: "IBM Plex Sans", group: 'modern' as FontGroup, stack: "'IBM Plex Sans Variable', ui-sans-serif, system-ui, sans-serif" },
  dmsans: { label: "DM Sans", group: 'modern' as FontGroup, stack: "'DM Sans Variable', ui-sans-serif, system-ui, sans-serif" },
  manrope: { label: "Manrope", group: 'modern' as FontGroup, stack: "'Manrope Variable', ui-sans-serif, system-ui, sans-serif" },
  jakarta: { label: "Plus Jakarta Sans", group: 'modern' as FontGroup, stack: "'Plus Jakarta Sans Variable', ui-sans-serif, system-ui, sans-serif" },
  grotesk: { label: "Space Grotesk", group: 'character' as FontGroup, stack: "'Space Grotesk Variable', ui-sans-serif, system-ui, sans-serif" },
  outfit: { label: "Outfit", group: 'character' as FontGroup, stack: "'Outfit Variable', ui-sans-serif, system-ui, sans-serif" },
  sora: { label: "Sora", group: 'character' as FontGroup, stack: "'Sora Variable', ui-sans-serif, system-ui, sans-serif" },
  nunito: { label: "Nunito Sans", group: 'rounded' as FontGroup, stack: "'Nunito Sans Variable', ui-sans-serif, system-ui, sans-serif" },
  quicksand: { label: "Quicksand", group: 'rounded' as FontGroup, stack: "'Quicksand Variable', ui-sans-serif, system-ui, sans-serif" },
  comfortaa: { label: "Comfortaa", group: 'rounded' as FontGroup, stack: "'Comfortaa Variable', ui-sans-serif, system-ui, sans-serif" },
  rubik: { label: "Rubik", group: 'rounded' as FontGroup, stack: "'Rubik Variable', ui-sans-serif, system-ui, sans-serif" },
  sourceserif: { label: "Source Serif", group: 'serif' as FontGroup, stack: "'Source Serif 4 Variable', ui-serif, Georgia, 'Times New Roman', serif" },
  lora: { label: "Lora", group: 'serif' as FontGroup, stack: "'Lora Variable', ui-serif, Georgia, 'Times New Roman', serif" },
  newsreader: { label: "Newsreader", group: 'serif' as FontGroup, stack: "'Newsreader Variable', ui-serif, Georgia, 'Times New Roman', serif" },
  fraunces: { label: "Fraunces", group: 'serif' as FontGroup, stack: "'Fraunces Variable', ui-serif, Georgia, 'Times New Roman', serif" },
  garamond: { label: "EB Garamond", group: 'serif' as FontGroup, stack: "'EB Garamond Variable', ui-serif, Georgia, 'Times New Roman', serif" },
  atkinson: { label: "Atkinson Hyperlegible", group: 'readable' as FontGroup, stack: "'Atkinson Hyperlegible Next Variable', ui-sans-serif, system-ui, sans-serif" },
  lexend: { label: "Lexend", group: 'readable' as FontGroup, stack: "'Lexend Variable', ui-sans-serif, system-ui, sans-serif" },
  jetbrainsui: { label: "JetBrains Mono", group: 'mono' as FontGroup, stack: "'JetBrains Mono Variable', ui-monospace, monospace" },
  martian: { label: "Martian Mono", group: 'mono' as FontGroup, stack: "'Martian Mono Variable', ui-monospace, monospace" },
  system: { label: "System", group: 'system' as FontGroup, stack: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif" },
} as const

export const MONO_FONTS = {
  system: { label: "System", stack: "ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace" },
  jetbrains: { label: "JetBrains Mono", stack: "'JetBrains Mono Variable', ui-monospace, monospace" },
  fira: { label: "Fira Code", stack: "'Fira Code Variable', ui-monospace, monospace" },
  geist: { label: "Geist Mono", stack: "'Geist Mono Variable', ui-monospace, monospace" },
  cascadia: { label: "Cascadia Code", stack: "'Cascadia Code Variable', ui-monospace, monospace" },
  sourcecode: { label: "Source Code Pro", stack: "'Source Code Pro Variable', ui-monospace, monospace" },
  victor: { label: "Victor Mono", stack: "'Victor Mono Variable', ui-monospace, monospace" },
  martian: { label: "Martian Mono", stack: "'Martian Mono Variable', ui-monospace, monospace" },
  roboto: { label: "Roboto Mono", stack: "'Roboto Mono Variable', ui-monospace, monospace" },
  redhat: { label: "Red Hat Mono", stack: "'Red Hat Mono Variable', ui-monospace, monospace" },
  atkinsonmono: { label: "Atkinson Mono", stack: "'Atkinson Hyperlegible Mono Variable', ui-monospace, monospace" },
} as const

export type SansFont = keyof typeof SANS_FONTS
export type MonoFont = keyof typeof MONO_FONTS

export const FONT_GROUPS: FontGroup[] = ['modern', 'character', 'rounded', 'serif', 'readable', 'mono', 'system']

// Font CSS per family (the default Inter is imported by globals.css; System needs nothing).
const FONT_CSS: Record<string, () => Promise<unknown>> = {
  'Geist Variable': () => import('@fontsource-variable/geist'),
  'IBM Plex Sans Variable': () => import('@fontsource-variable/ibm-plex-sans'),
  'DM Sans Variable': () => import('@fontsource-variable/dm-sans'),
  'Manrope Variable': () => import('@fontsource-variable/manrope'),
  'Plus Jakarta Sans Variable': () => import('@fontsource-variable/plus-jakarta-sans'),
  'Space Grotesk Variable': () => import('@fontsource-variable/space-grotesk'),
  'Outfit Variable': () => import('@fontsource-variable/outfit'),
  'Sora Variable': () => import('@fontsource-variable/sora'),
  'Nunito Sans Variable': () => import('@fontsource-variable/nunito-sans'),
  'Quicksand Variable': () => import('@fontsource-variable/quicksand'),
  'Comfortaa Variable': () => import('@fontsource-variable/comfortaa'),
  'Rubik Variable': () => import('@fontsource-variable/rubik'),
  'Source Serif 4 Variable': () => import('@fontsource-variable/source-serif-4'),
  'Lora Variable': () => import('@fontsource-variable/lora'),
  'Newsreader Variable': () => import('@fontsource-variable/newsreader'),
  'Fraunces Variable': () => import('@fontsource-variable/fraunces'),
  'EB Garamond Variable': () => import('@fontsource-variable/eb-garamond'),
  'Atkinson Hyperlegible Next Variable': () => import('@fontsource-variable/atkinson-hyperlegible-next'),
  'Lexend Variable': () => import('@fontsource-variable/lexend'),
  'JetBrains Mono Variable': () => import('@fontsource-variable/jetbrains-mono'),
  'Martian Mono Variable': () => import('@fontsource-variable/martian-mono'),
  'Fira Code Variable': () => import('@fontsource-variable/fira-code'),
  'Geist Mono Variable': () => import('@fontsource-variable/geist-mono'),
  'Cascadia Code Variable': () => import('@fontsource-variable/cascadia-code'),
  'Source Code Pro Variable': () => import('@fontsource-variable/source-code-pro'),
  'Victor Mono Variable': () => import('@fontsource-variable/victor-mono'),
  'Roboto Mono Variable': () => import('@fontsource-variable/roboto-mono'),
  'Red Hat Mono Variable': () => import('@fontsource-variable/red-hat-mono'),
  'Atkinson Hyperlegible Mono Variable': () => import('@fontsource-variable/atkinson-hyperlegible-mono'),
}
const loaded = new Set<string>()

/** Loads the @font-face rules of a stack's first family (once). Until they arrive the fallback of the stack shows. */
export function loadFont(stack: string) {
  const family = /^'([^']+)'/.exec(stack)?.[1]
  if (!family || loaded.has(family) || !FONT_CSS[family]) return
  loaded.add(family)
  FONT_CSS[family]().catch(() => loaded.delete(family))
}

type IdleWindow = Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number }
const previews: string[] = []
let draining = false
/** Like loadFont, for a font shown only as a preview (the Settings font picker): queued and loaded one at a time
 *  when the browser is idle, so opening the page does not fetch and lay out ~30 fonts before it is shown. */
export function loadFontPreview(stack: string) {
  previews.push(stack)
  if (draining) return
  draining = true
  const w = window as IdleWindow
  const next = () => {
    const s = previews.shift()
    if (!s) return void (draining = false)
    loadFont(s)
    if (w.requestIdleCallback) w.requestIdleCallback(next, { timeout: 400 })
    else setTimeout(next, 30)
  }
  setTimeout(next, 250)
}

export function applyFonts(sans: SansFont, mono: MonoFont) {
  loadFont((SANS_FONTS[sans] || SANS_FONTS.inter).stack)
  loadFont((MONO_FONTS[mono] || MONO_FONTS.system).stack)
  const r = document.documentElement.style
  r.setProperty('--mx-font-sans', (SANS_FONTS[sans] || SANS_FONTS.inter).stack)
  r.setProperty('--mx-font-mono', (MONO_FONTS[mono] || MONO_FONTS.system).stack)
}
