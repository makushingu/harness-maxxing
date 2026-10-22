// The tour script. Each step points at `data-tour="<id>"` elements (the visible ones are unioned into the
// spotlight); a step whose target cannot be found (after an optional route change) is skipped.
import type { TKey } from '@/i18n'
import { useTouchNav } from '@/components/shell/TouchNav'

export type StepCtx = { pathname: string; search: URLSearchParams; mobile: boolean; firstTopic: string | null }

export type TourStep = {
  id: string
  /** `data-tour` ids to spotlight; empty = a card in the middle of the screen (nothing to point at). */
  targets: string[]
  title: TKey
  body: TKey
  /** Touch-layout wording when the UI differs (the ☰ and ⊞ drawers). */
  bodyMobile?: TKey
  /** Route to visit before looking for the target (null = stay). */
  route?: (ctx: StepCtx) => string | null
  /** Only follow `route` when the target is not already on screen. */
  routeIfMissing?: boolean
  /** Run once before looking for the target (open a panel...). */
  before?: (ctx: StepCtx) => void
  /** Showcase: label of the last button and what it does after the card closes ("Try it" -> open a demo). */
  cta?: TKey
  after?: () => void
}

/** On the Sessions page (desktop: the tree is there; touch layout: the tree is in the ☰ drawer, opened by `before`). */
export const sessionsList = (c: StepCtx) => (c.mobile || c.pathname === '/sessions' ? null : '/sessions')
/** Touch layout: the drawer a step points into (null closes them). */
const panel = (p: 'sessions' | 'app' | null) => (c: StepCtx) => {
  if (c.mobile) useTouchNav.getState().setPanel(p)
}

export const STEPS: TourStep[] = [
  { id: 'nav', targets: ['nav', 'touch-sessions'], title: 'tour.nav.title', body: 'tour.nav.body', bodyMobile: 'tour.nav.bodyMobile', before: panel(null) },
  { id: 'tree', targets: ['tree'], title: 'tour.tree.title', body: 'tour.tree.body', route: sessionsList, before: panel('sessions') },
  { id: 'new', targets: ['new-session'], title: 'tour.new.title', body: 'tour.new.body', bodyMobile: 'tour.new.bodyMobile', route: sessionsList, before: panel('sessions') },
  {
    id: 'composer',
    targets: ['composer'],
    title: 'tour.composer.title',
    body: 'tour.composer.body',
    before: panel(null),
    // A composer only exists inside a session column: open a "new session" column if none is visible.
    routeIfMissing: true,
    route: (c) => (c.firstTopic === null ? null : `/sessions?path=${encodeURIComponent(c.search.get('path') ?? c.firstTopic)}&new=1`),
  },
  { id: 'palette', targets: ['palette'], title: 'tour.palette.title', body: 'tour.palette.body', bodyMobile: 'tour.palette.bodyMobile', before: panel('app') },
  { id: 'tasks', targets: ['nav-tasks', 'nav-crons'], title: 'tour.tasks.title', body: 'tour.tasks.body', before: panel('app') },
  { id: 'settings', targets: ['nav-settings'], title: 'tour.settings.title', body: 'tour.settings.body', before: panel('app') },
  { id: 'health', targets: ['health'], title: 'tour.health.title', body: 'tour.health.body', bodyMobile: 'tour.health.bodyMobile', before: panel('app') },
]
