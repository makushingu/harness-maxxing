// Guided tour state (not persisted; `tourDone` lives in the persisted UI store).
import { create } from 'zustand'
import { useWorkspace } from '@/lib/queries'
import type { TourStep } from './steps'

/** The interactive tutorial topic shipped in the default workspace (`system/tutorial`; workspaces installed
 *  before 2.0.0a33 have the former `tutorial` project, whose first lesson is used then). */
export const TUTORIAL_PATHS = ['projects/system/topics/tutorial', 'projects/tutorial/topics/1-first-steps']
export const tutorialHref = (path: string) => `/sessions?path=${encodeURIComponent(path)}&new=1`
/** Set by onboarding when it completes: the shell starts the tour once on the next landing. */
export const TOUR_PENDING_KEY = 'mx-tour-pending'

type TourState = {
  active: boolean
  /** Bumped on every start so a replay restarts from step 1. */
  run: number
  /** A short showcase of one feature (What's new -> Show me) instead of the guided tour; null = the tour. */
  showcase: TourStep[] | null
  start: (showcase?: TourStep[]) => void
  stop: () => void
}

export const useTour = create<TourState>((set) => ({
  active: false,
  run: 0,
  showcase: null,
  start: (showcase) => set((s) => ({ active: true, run: s.run + 1, showcase: showcase?.length ? showcase : null })),
  stop: () => set({ active: false }),
}))

/** Start (or restart) the tour. Deferred a tick so menus/palettes that triggered it can close first. */
export function startTour() {
  setTimeout(() => useTour.getState().start(), 120)
}

/** Link to the tutorial topic of this workspace, or null when it was deleted (then the entries are hidden). */
export function useTutorialHref(): string | null {
  const { data } = useWorkspace()
  const paths = new Set(data?.projects.flatMap((p) => p.topics.map((tp) => tp.path)) || [])
  const found = TUTORIAL_PATHS.find((p) => paths.has(p))
  return found ? tutorialHref(found) : null
}

export function requestTourAfterOnboarding() {
  try {
    sessionStorage.setItem(TOUR_PENDING_KEY, '1')
  } catch {
    /* storage blocked: no automatic tour, still replayable from the menu */
  }
}
