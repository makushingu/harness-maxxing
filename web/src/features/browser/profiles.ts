// Small helpers shared by the browser's views: names of profiles and exits, who uses a tab, an exit's state line.
import type { TFn as T } from '@/i18n'
import type { BrowserExit, BrowserExitTest, BrowserNavigator, BrowserProfile } from '@/lib/types'

/** `main` with no name of its own reads "General" in the user's language. */
export const profileName = (p: Pick<BrowserProfile, 'id' | 'name'> | undefined, t: T) =>
  !p ? '' : p.name || (p.id === 'main' ? t('browser.mainProfile') : p.id)

export const exitName = (id: string, exits: BrowserExit[] | undefined, t: T) =>
  id === 'direct' ? t('browser.exit.direct') : exits?.find((e) => e.id === id)?.name || id

/** "Orange, France · 38 ms" / "offline for 12 min" / "server address". */
export function exitLine(e: BrowserExit | undefined, t: T, now = Date.now() / 1000): string {
  if (!e) return t('browser.exit.directLine')
  if (e.state === 'down') return e.since ? t('browser.exit.downSince', { min: Math.max(1, Math.round((now - e.since) / 60)) }) : t('browser.exit.down')
  const where = testWhere(e.test)
  const ms = e.latency_ms ?? e.test?.latency_ms
  return [where, ms != null ? `${ms} ms` : '', e.state === 'unknown' && !where ? t(e.checking ? 'browser.exit.checking' : 'browser.exit.untested') : ''].filter(Boolean).join(' · ')
}

/** "Orange, France" from a test. */
export const testWhere = (x: BrowserExitTest | null | undefined) => (x?.ok ? [x.operator, x.country].filter(Boolean).join(', ') : '')

/** green / red / grey dot of an exit (direct: always green). */
export const exitTone = (e: BrowserExit | undefined) => (!e ? 'bg-success' : e.state === 'up' ? 'bg-success' : e.state === 'down' ? 'bg-destructive' : 'bg-muted-foreground/50')

/** "projects/acme/topics/blog/agents/writer" -> { kind: 'agent', name: 'writer', where: 'acme / blog' }. */
export function ownerParts(path: string): { kind: 'project' | 'topic' | 'agent'; name: string; where: string } {
  const m = path.match(/^projects\/([^/]+)(?:\/topics\/([^/]+)(?:\/agents\/([^/]+))?)?/)
  if (!m) return { kind: 'project', name: path, where: '' }
  if (m[3]) return { kind: 'agent', name: m[3], where: `${m[1]} / ${m[2]}` }
  if (m[2]) return { kind: 'topic', name: `${m[1]} / ${m[2]}`, where: m[1] }
  return { kind: 'project', name: m[1], where: '' }
}

/** The navigator of a turn: an agent's (all its runs share it), else the session's; "me" = the person's own. */
export function navOf(session?: string, path?: string): string {
  const p = (path || '').replace(/\/+$/, '')
  if (/^projects\/[^/]+\/topics\/[^/]+\/agents\/[^/]+$/.test(p)) return `agent:${p}`
  return session ? `session:${session}` : 'me'
}

/** A navigator's name: "Your browser", an agent's, a session's title. */
export function navName(n: Pick<BrowserNavigator, 'id' | 'kind' | 'name'> | undefined, t: T): string {
  if (!n) return ''
  if (n.name) return n.name
  if (n.kind === 'person') return t('browser.nav.me')
  return n.kind === 'session' ? t('browser.nav.session') : n.id
}

/** Profiles in the order of the sidebar: the person's, then the projects' (by name), then the others. */
export function orderedProfiles<P extends BrowserProfile & { project?: string | null; gone?: boolean }>(rows: P[], t: T): P[] {
  const rank = (p: P) => (p.id === 'main' ? 0 : p.project && !p.gone ? 1 : 2)
  return [...rows].sort((a, b) => rank(a) - rank(b) || profileName(a, t).localeCompare(profileName(b, t)))
}
