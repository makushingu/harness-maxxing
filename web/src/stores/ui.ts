// Persistent UI preferences (localStorage key `mx-ui`). index.html reads the same key before the
// first paint to avoid a theme flash — keep field names in sync.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Language } from '@/lib/types'
import { applyFavicon } from '@/lib/accent'
import { applyFonts, MONO_FONTS, SANS_FONTS, type MonoFont, type SansFont } from '@/lib/fonts'

export type Theme = 'dark' | 'light' | 'system'
export type Density = 'comfortable' | 'compact'
/** Background: neutral greys, or a shade of the accent color. */
export type Tint = 'neutral' | 'tinted'
/** Material of the bars and floating layers: solid colors, or translucent glass over a wallpaper of the accent. */
export type Material = 'solid' | 'glass'
/** Layout of this device: auto (touch screens and narrow windows get the touch layout), always touch, or the
 *  desktop layout whenever the window is wide enough. */
export type Layout = 'auto' | 'touch' | 'desktop'
/** First screen of the touch layout when the app opens on `/`: the last session, or the dashboard. */
export type TouchHome = 'session' | 'dashboard'
export const ACCENTS = ['blue', 'clay', 'violet', 'green', 'amber', 'rose'] as const
export type Accent = (typeof ACCENTS)[number]

/** Expanded sidebar width (px): dragged by its right edge, double-click = default. */
/** The sidebar entries that open a list beside the bar (Sidebar.tsx). */
export const SIDEBAR_W = { min: 220, max: 440, default: 264 }
const clampSidebar = (w: number) => Math.round(Math.max(SIDEBAR_W.min, Math.min(SIDEBAR_W.max, w)))
/** The second-level sidebar's width (components/shell/PageList.tsx). */
export const SECOND_W = { min: 220, max: 520, default: 288 }
const clampSecond = (w: number) => Math.round(Math.max(SECOND_W.min, Math.min(SECOND_W.max, w)))

type UIState = {
  theme: Theme
  accent: Accent
  density: Density
  tint: Tint
  material: Material
  /** Interface and code fonts (this browser). */
  font: SansFont
  monoFont: MonoFont
  language: Language
  sidebarCollapsed: boolean
  /** Width of the expanded sidebar dragged by the user (desktop); null = the default (SIDEBAR_W). */
  sidebarWidth: number | null
  /** The second-level sidebar (the list of Sessions, Agents, Team; desktop, components/shell/PageList.tsx) is open, for
   *  every page; closed, the page's entry in the sidebar shows it on hover. */
  secondBarOpen: boolean
  /** The Extensions folder of the sidebar (the pinned extension pages) is unfolded. */
  extFolderOpen: boolean
  /** Its width dragged by the user; null = the default (SECOND_W). */
  secondBarWidth: number | null
  layout: Layout
  touchHome: TouchHome
  /** Presentation mode: every <Sensitive> renders a mask instead of its content. */
  presentation: boolean
  /** Presentation mode turned on only for a Feedback screenshot: a page reloaded or closed during the shot turns it
   *  back off on the next load. */
  presentationShot: boolean
  /** The guided tour was completed or skipped (it starts automatically once, after onboarding). */
  tourDone: boolean
  /** Desktop notification when a Claude session finishes its turn (this browser). */
  notifyDone: boolean
  /** Notifications panel next to the dashboard widgets (wide screens). */
  feedPanel: boolean
  /** Notification for a new Team message (a chat that is not on screen, not muted). */
  notifyTeam: boolean
  /** Team chats as Messenger-style bubbles at the bottom right of every page (off: Team opens its page). */
  teamBubbles: boolean
  /** Resting the pointer on an agent of a page's list shows its card (features/agents/AgentHover.tsx); off by default. */
  agentPreview: boolean
  /** Short sound with that notification. */
  notifySound: boolean
  /** The unread badges (sidebar, tab bar, tree) pulse. */
  badgePulse: boolean
  /** HUD mode: each session gets a button opening its floating bar (this browser). */
  hud: boolean
  /** Theme, accent or tint chosen in this browser; until then it shows the server's look (`adoptLook`). */
  lookChosen: boolean
  setTheme: (t: Theme) => void
  setAccent: (a: Accent) => void
  setDensity: (d: Density) => void
  setTint: (t: Tint) => void
  setMaterial: (m: Material) => void
  setFont: (f: SansFont) => void
  setMonoFont: (f: MonoFont) => void
  setLanguage: (l: Language) => void
  toggleSidebar: () => void
  setSidebarWidth: (w: number | null) => void
  setSecondBarOpen: (v: boolean) => void
  setExtFolderOpen: (v: boolean) => void
  setSecondBarWidth: (w: number | null) => void
  setLayout: (l: Layout) => void
  setTouchHome: (h: TouchHome) => void
  setPresentation: (on: boolean) => void
  setTourDone: (done: boolean) => void
  setNotify: (p: Partial<Pick<UIState, 'notifyDone' | 'notifyTeam' | 'teamBubbles' | 'agentPreview' | 'notifySound' | 'badgePulse'>>) => void
  setFeedPanel: (v: boolean) => void
  setHud: (on: boolean) => void
  adoptLook: (look: Look) => void
}

/** The look last chosen in a signed-in browser, kept by the server (`/api/auth/state` `look`). */
export type Look = { theme: Theme; accent: Accent; tint: Tint }

const initialLang = (): Language => (typeof navigator !== 'undefined' && navigator.language?.toLowerCase().startsWith('fr') ? 'fr' : 'en')

export const useUI = create<UIState>()(
  persist(
    (set) => ({
      theme: 'dark',
      accent: 'blue',
      density: 'comfortable',
      tint: 'neutral',
      material: 'solid',
      font: 'inter',
      monoFont: 'system',
      language: initialLang(),
      // New browsers start with the labelled sidebar (pinned); the pin folds it to the icon bar.
      sidebarCollapsed: false,
      sidebarWidth: null,
      secondBarOpen: true,
      extFolderOpen: true,
      secondBarWidth: null,
      layout: 'auto',
      touchHome: 'session',
      presentation: false,
      presentationShot: false,
      tourDone: false,
      notifyDone: false,
      notifyTeam: true,
      teamBubbles: true,
      agentPreview: false,
      feedPanel: true,
      notifySound: true,
      badgePulse: false,
      hud: false,
      lookChosen: false,
      setTheme: (theme) => set({ theme, lookChosen: true }),
      setAccent: (accent) => set({ accent, lookChosen: true }),
      setDensity: (density) => set({ density }),
      setTint: (tint) => set({ tint, lookChosen: true }),
      setMaterial: (material) => set({ material }),
      setFont: (font) => set({ font }),
      setMonoFont: (monoFont) => set({ monoFont }),
      setLanguage: (language) => set({ language }),
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setSidebarWidth: (w) => set({ sidebarWidth: w == null ? null : clampSidebar(w) }),
      setSecondBarOpen: (secondBarOpen) => set({ secondBarOpen }),
      setExtFolderOpen: (extFolderOpen) => set({ extFolderOpen }),
      setSecondBarWidth: (w) => set({ secondBarWidth: w == null ? null : clampSecond(w) }),
      setLayout: (layout) => set({ layout }),
      setTouchHome: (touchHome) => set({ touchHome }),
      setPresentation: (presentation) => set({ presentation }),
      setTourDone: (tourDone) => set({ tourDone }),
      setNotify: (p) => set(p),
      setFeedPanel: (feedPanel) => set({ feedPanel }),
      setHud: (hud) => set({ hud }),
      adoptLook: ({ theme, accent, tint }) => set({ theme, accent, tint }),
    }),
    {
      name: 'mx-ui',
      version: 2,
      // v2: the teal and graphite accents were removed; unknown values fall back to the defaults.
      migrate: (old) => {
        const s = (old || {}) as Partial<UIState>
        if (!ACCENTS.includes(s.accent as Accent)) s.accent = 'blue'
        return s as UIState
      },
      merge: (persisted, current) => {
        const p = (persisted || {}) as Partial<UIState>
        const out = { ...current, ...p }
        // Saved before lookChosen existed: a browser that stored a theme or accent had picked it.
        if (p.lookChosen === undefined) out.lookChosen = p.theme !== undefined || p.accent !== undefined
        if (!ACCENTS.includes(out.accent)) out.accent = 'blue'
        if (!(out.font in SANS_FONTS)) out.font = 'inter'
        if (out.tint !== 'tinted') out.tint = 'neutral'
        if (out.material !== 'glass') out.material = 'solid'
        if (!(out.monoFont in MONO_FONTS)) out.monoFont = 'system'
        if (out.layout !== 'touch' && out.layout !== 'desktop') out.layout = 'auto'
        out.sidebarWidth = typeof out.sidebarWidth === 'number' && Number.isFinite(out.sidebarWidth) ? clampSidebar(out.sidebarWidth) : null
        out.secondBarOpen = out.secondBarOpen !== false
        out.extFolderOpen = out.extFolderOpen !== false
        out.secondBarWidth = typeof out.secondBarWidth === 'number' && Number.isFinite(out.secondBarWidth) ? clampSecond(out.secondBarWidth) : null
        if (out.touchHome !== 'dashboard') out.touchHome = 'session'
        if (out.presentationShot) {
          out.presentation = false
          out.presentationShot = false
        }
        return out
      },
    },
  ),
)

/** Resolved theme ('system' → OS preference), live. */
export function resolveTheme(t: Theme): 'dark' | 'light' {
  if (t !== 'system') return t
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** Applies theme/accent/density/lang to <html>. Called once from main.tsx (subscribes). */
export function bindUIToDocument() {
  const apply = () => {
    const s = useUI.getState()
    const r = document.documentElement
    const dark = resolveTheme(s.theme) === 'dark'
    r.classList.toggle('dark', dark)
    r.dataset.accent = s.accent
    r.dataset.density = s.density
    r.dataset.tint = s.tint
    r.dataset.material = s.material
    r.lang = s.language
    applyFavicon(s.accent)
    applyFonts(s.font, s.monoFont)
    // The app theme may differ from the OS one: every theme-color meta (dark/light media variants) follows it.
    document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute('content', dark ? '#09090b' : '#ffffff'))
  }
  apply()
  useUI.subscribe(apply)
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', apply)
}
