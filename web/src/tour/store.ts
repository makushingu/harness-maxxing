// Showcase state (What's new -> Show me) and the entry point of the getting-started guide (guide/Guide.tsx).
import { create } from 'zustand'
import { useWorkspace } from '@/lib/queries'
import type { TourStep } from './steps'

/** The interactive tutorial topic shipped in the default workspace (`system/tutorial`; workspaces installed
 *  before 2.0.0a33 have the former `tutorial` project, whose first lesson is used then). */
export const TUTORIAL_PATHS = ['projects/system/topics/tutorial', 'projects/tutorial/topics/1-first-steps']
export const tutorialHref = (path: string) => `/sessions?path=${encodeURIComponent(path)}&new=1`

type TourState = {
  active: boolean
  /** Bumped on every start so a replay restarts from step 1. */
  run: number
  /** The showcase played (null: none). */
  showcase: TourStep[] | null
  start: (showcase: TourStep[]) => void
  stop: () => void
}

export const useTour = create<TourState>((set) => ({
  active: false,
  run: 0,
  showcase: null,
  start: (showcase) => set((s) => ({ active: !!showcase.length, run: s.run + 1, showcase: showcase.length ? showcase : null })),
  stop: () => set({ active: false }),
}))

/** The getting-started guide: `open` = its first dialog (level, mode, or "Resume"). */
export const useGuideOpen = create<{ open: boolean; setOpen: (open: boolean) => void }>((set) => ({ open: false, setOpen: (open) => set({ open }) }))

/** The guide's card is on screen (the touch drawers then let its taps through, as for a showcase). */
export const useGuideOn = create<{ on: boolean }>(() => ({ on: false }))

/** Open the guide. Deferred a tick so menus/palettes that triggered it can close first. */
export function startGuide() {
  setTimeout(() => useGuideOpen.getState().setOpen(true), 120)
}

/** Link to the tutorial topic of this workspace, or null when it was deleted (then the entries are hidden). */
export function useTutorialHref(): string | null {
  const { data } = useWorkspace()
  const paths = new Set(data?.projects.flatMap((p) => p.topics.map((tp) => tp.path)) || [])
  const found = TUTORIAL_PATHS.find((p) => paths.has(p))
  return found ? tutorialHref(found) : null
}
