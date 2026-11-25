// A showcase step (features/whatsnew/showcases.ts) or a guide step (guide/steps.ts) points at `data-tour="<id>"` elements (the visible ones are unioned into the
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
export const panel = (p: 'sessions' | 'app' | null) => (c: StepCtx) => {
  if (c.mobile) useTouchNav.getState().setPanel(p)
}
