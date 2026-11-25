// The getting-started guide's steps (same ids as server/maxxing/guide.py STEPS). A step = where to look (the
// `data-tour` targets, a page to open) and a fixed one-line explanation + a tip; the personal part of its card (a line
// that links it to what the user just did, ready-to-send prompts) is written by Opus on the server when the user gets
// near it. A target not on screen (a page switched off, a phone layout) never blocks: the card shows in the middle.
import type { TKey } from '@/i18n'
import type { Settings } from '@/lib/types'
import { panel, sessionsList, type StepCtx } from '@/tour/steps'

export type Use = 'automate' | 'phone' | 'code' | 'sites' | 'mail' | 'team' | 'content'
export const USES: Use[] = ['automate', 'phone', 'code', 'sites', 'mail', 'team', 'content']

export type GuideStep = {
  id: string
  /** Part of the guide: `basics` are left out of the partial tour, a use only when chosen. */
  part: 'core' | 'basics' | Use | 'end'
  targets: string[]
  /** Route to visit before looking for the target (null = stay). */
  route?: (ctx: StepCtx) => string | null
  before?: (ctx: StepCtx) => void
  /** An optional page this step is about: off -> the card offers to switch it on. */
  feature?: keyof Settings & `${string}_page`
  /** Opus writes prompts for this card (else only its intro line, or nothing). */
  prompts?: boolean
}

const page = (to: string) => (c: StepCtx) => (c.pathname === to ? null : to)
const onSessions = (c: StepCtx) => (c.pathname === '/sessions' ? null : '/sessions')

export const GUIDE_STEPS: GuideStep[] = [
  { id: 'welcome', part: 'core', targets: [] },
  { id: 'nav', part: 'basics', targets: ['nav', 'touch-sessions'], before: panel(null) },
  { id: 'tree', part: 'basics', targets: ['tree'], route: sessionsList, before: panel('sessions') },
  { id: 'first-prompt', part: 'core', targets: ['new-session'], route: sessionsList, before: panel('sessions'), prompts: true },
  { id: 'memory', part: 'basics', targets: [], route: page('/settings/memory'), before: panel(null), prompts: true },
  { id: 'view-switch', part: 'core', targets: ['view-switch'], route: onSessions, before: panel(null) },
  { id: 'palette', part: 'basics', targets: ['palette'], before: panel('app') },
  { id: 'agents', part: 'automate', targets: ['nav-agents'], before: panel('app'), feature: 'agents_page', prompts: true },
  { id: 'agents-sessions', part: 'automate', targets: ['tree'], route: sessionsList, before: panel('sessions'), feature: 'agents_page', prompts: true },
  { id: 'crons', part: 'automate', targets: [], route: page('/settings/crons'), before: panel(null), prompts: true },
  { id: 'tasks', part: 'automate', targets: ['nav-tasks'], before: panel('app'), feature: 'tasks_page', prompts: true },
  { id: 'telegram', part: 'phone', targets: [], route: page('/settings/telegram'), before: panel(null) },
  { id: 'code', part: 'code', targets: ['nav-git'], before: panel('app'), feature: 'git_page', prompts: true },
  { id: 'sites', part: 'sites', targets: ['nav-infra'], before: panel('app'), feature: 'infra_page', prompts: true },
  { id: 'mail', part: 'mail', targets: ['nav-mail'], before: panel('app'), feature: 'mail_page', prompts: true },
  { id: 'team', part: 'team', targets: ['nav-team'], before: panel('app'), feature: 'team_page' },
  { id: 'content', part: 'content', targets: ['nav-files'], before: panel('app'), prompts: true },
  { id: 'safety', part: 'end', targets: [], route: page('/settings/backup'), before: panel(null) },
  { id: 'features', part: 'end', targets: [], route: page('/settings/features'), before: panel(null) },
  { id: 'health', part: 'end', targets: ['health'], before: panel('app') },
  { id: 'final', part: 'end', targets: [], before: panel(null), prompts: true },
]
export const STEP_BY_ID = Object.fromEntries(GUIDE_STEPS.map((s) => [s.id, s])) as Record<string, GuideStep>

/** Full tour: every step (someone who already uses Harness skips the very first basics). Partial tour: the core,
 *  the chosen uses, and the last card. */
export function plan(mode: 'full' | 'partial', uses: Use[], existing: boolean): string[] {
  const keep = (s: GuideStep) => {
    if (mode === 'full') return !(existing && (s.id === 'nav' || s.id === 'tree'))
    if (s.part === 'core' || s.id === 'final') return true
    return (uses as string[]).includes(s.part)
  }
  return GUIDE_STEPS.filter(keep).map((s) => s.id)
}

export const stepTitle = (id: string) => `guide.${id}.title` as TKey
export const stepBody = (id: string) => `guide.${id}.body` as TKey
export const stepTip = (id: string) => `guide.${id}.tip` as TKey
export const useLabel = (u: Use) => `guide.use.${u}` as TKey
