// Small helpers shared by the browser's views: names of profiles and exits, who uses a tab, an exit's state line.
import type { TFn as T } from '@/i18n'
import type { BrowserExit, BrowserExitTest, BrowserProfile, BrowserTab } from '@/lib/types'

/** `main` with no name of its own reads "Main" in the user's language. */
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
  return [where, ms != null ? `${ms} ms` : '', e.state === 'unknown' && !where ? t('browser.exit.untested') : ''].filter(Boolean).join(' · ')
}

/** "Orange, France" from a test. */
export const testWhere = (x: BrowserExitTest | null | undefined) => (x?.ok ? [x.operator, x.country].filter(Boolean).join(', ') : '')

/** green / red / grey dot of an exit (direct: always green). */
export const exitTone = (e: BrowserExit | undefined) => (!e ? 'bg-success' : e.state === 'up' ? 'bg-success' : e.state === 'down' ? 'bg-destructive' : 'bg-muted-foreground/50')

/** The tab a session last used, else the newest one a turn of that folder opened. */
export function tabOfSession(tabs: BrowserTab[], session: string, path?: string): BrowserTab | undefined {
  const own = tabs.filter((t) => t.by.sid === session).sort((a, b) => b.used - a.used)
  if (own.length) return own[0]
  return path ? tabs.filter((t) => t.by.path === path).sort((a, b) => b.used - a.used)[0] : undefined
}

/** "projects/acme/topics/blog/agents/writer" -> { kind: 'agent', name: 'writer', where: 'acme / blog' }. */
export function ownerParts(path: string): { kind: 'project' | 'topic' | 'agent'; name: string; where: string } {
  const m = path.match(/^projects\/([^/]+)(?:\/topics\/([^/]+)(?:\/agents\/([^/]+))?)?/)
  if (!m) return { kind: 'project', name: path, where: '' }
  if (m[3]) return { kind: 'agent', name: m[3], where: `${m[1]} / ${m[2]}` }
  if (m[2]) return { kind: 'topic', name: `${m[1]} / ${m[2]}`, where: m[1] }
  return { kind: 'project', name: m[1], where: '' }
}
