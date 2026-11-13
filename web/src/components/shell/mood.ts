import { useEffect } from 'react'
import { useAgentsAttention, useFeed, useHealth, useTeam, useUsage, useWorkspace } from '@/lib/queries'
import { fmtDate } from '@/lib/format'
import { loadGroups, useLang, useT, type TKey, type TVars } from '@/i18n'
import type { Health, UsagePayload, UsageWindow } from '@/lib/types'
import { useNav } from './nav'

/** What the status line says is picked from these (everything the shell already loads). */
export type MoodFacts = {
  health?: Health
  usage?: UsagePayload | null
  feedUnread: number
  sessionsUnread: number
  running: number
  teamUnread: number
  agents: number
  /** Unix seconds */
  now: number
  /** local hour, 0-23 */
  hour: number
}

/** One short sentence about the server. `level`: ok (green dot), note (amber dot), warn / error (the line in its
 *  alert colour), idle (not known yet). `issues`: about the health problems (the line opens their window). `when`:
 *  times (Unix seconds) the text names, formatted by the hook (`days`: another day is named without its hour). */
export type Mood = {
  key: TKey
  vars?: TVars
  when?: { hit?: number; reset?: number; days?: boolean }
  level: 'ok' | 'note' | 'warn' | 'error' | 'idle'
  to?: string
  issues?: boolean
}

const FIVE_H = 5 * 3600
const WEEK = 7 * 86400

/** A light forecast of a plan window: the usage so far drawn as a straight line to the reset. `hit`: when the quota
 *  would run out, only when that is before the reset; null too early in the window (under 15 % of it, or under
 *  20 % used: a first burst says nothing) to tell. */
export function forecast(w: UsageWindow | null | undefined, len: number, now: number): { pct: number; reset: number | null; hit: number | null } | null {
  if (!w || typeof w.pct !== 'number' || !Number.isFinite(w.pct)) return null
  const pct = w.pct
  const reset = w.resets_at && w.resets_at > now ? w.resets_at : null
  if (!reset) return { pct, reset, hit: null }
  const elapsed = len - (reset - now)
  if (elapsed < len * 0.15 || pct < 20 || pct >= 100) return { pct, reset, hit: null }
  const hit = now + (elapsed * (100 - pct)) / pct
  return { pct, reset, hit: hit < reset - len * 0.03 ? hit : null }
}

/** The sentence of each health problem (the server's own text is in English only); others keep the count. */
const ISSUE_MOOD: Record<string, TKey> = {
  disk_full: 'mood.issue.disk',
  low_memory: 'mood.issue.memory',
  service_down: 'mood.issue.service',
  cron_failed: 'mood.issue.cron',
  login_failures: 'mood.issue.logins',
  claude_auth: 'mood.issue.claude',
  backup_never: 'mood.issue.backupNever',
  backup_old: 'mood.issue.backupOld',
  backup_failed: 'mood.issue.backupFailed',
}

/** The one thing worth saying now, most pressing first: health problems, quota out, a busy server (CPU, memory),
 *  quota that will not last until its reset, disk filling up, things left unread, then how well it all goes. */
export function pickMood(f: MoodFacts): Mood {
  const h = f.health
  if (!h) return { key: 'health.checking', level: 'idle' }

  const open = h.issues.filter((i) => !i.seen)
  const level = open.some((i) => i.level === 'error') ? 'error' : open.some((i) => i.level === 'warn') ? 'warn' : null
  if (level) {
    const loud = open.filter((i) => i.level === 'error' || i.level === 'warn')
    const key = loud.length === 1 ? ISSUE_MOOD[loud[0].code] : undefined
    if (!key) return { key: loud.length === 1 ? 'health.issues' : 'mood.issues', vars: { count: loud.length }, level, issues: true }
    return { key, vars: { pct: Math.round(h.disk.pct), count: h.failed_logins_1h }, level, issues: true }
  }

  const five = forecast(f.usage?.available ? f.usage.five_hour : null, FIVE_H, f.now)
  const week = forecast(f.usage?.available ? f.usage.seven_day : null, WEEK, f.now)
  const usage = '/settings/usage'
  if (five && five.pct >= 99.5) return five.reset ? { key: 'mood.quotaFiveOut', when: { reset: five.reset }, level: 'warn', to: usage } : { key: 'mood.quotaOut', level: 'warn', to: usage }
  if (week && week.pct >= 99.5) return week.reset ? { key: 'mood.quotaWeekOut', when: { reset: week.reset }, level: 'warn', to: usage } : { key: 'mood.quotaOut', level: 'warn', to: usage }

  const system = '/settings/system'
  const cpu = Math.round(h.cpu_pct)
  if (cpu >= 85) return { key: 'mood.cpuHot', vars: { pct: cpu }, level: 'note', to: system }
  const mem = h.mem.total ? Math.round(((h.mem.total - h.mem.avail) / h.mem.total) * 100) : 0
  if (mem >= 90) return { key: 'mood.memHigh', vars: { pct: mem }, level: 'note', to: system }

  if (five?.hit) return { key: 'mood.quotaFiveSoon', when: { hit: five.hit, reset: five.reset! }, level: 'note', to: usage }
  if (week?.hit) return { key: 'mood.quotaWeekSoon', when: { hit: week.hit, reset: week.reset!, days: true }, level: 'note', to: usage }
  if (five && five.pct >= 90 && five.reset) return { key: 'mood.quotaFiveTight', when: { reset: five.reset }, level: 'note', to: usage }
  if (week && week.pct >= 90 && week.reset) return { key: 'mood.quotaWeekTight', when: { reset: week.reset }, level: 'note', to: usage }

  const disk = Math.round(h.disk.pct)
  if (disk >= 80) return { key: 'mood.diskHigh', vars: { pct: disk }, level: 'note', to: system }

  if (f.feedUnread > 10) return { key: 'mood.notifs', vars: { count: f.feedUnread }, level: 'ok', to: '/feed' }
  if (f.sessionsUnread >= 5) return { key: 'mood.sessionsUnread', vars: { count: f.sessionsUnread }, level: 'ok', to: '/sessions' }
  if (f.agents > 0) return { key: 'mood.agents', vars: { count: f.agents }, level: 'ok', to: '/agents' }
  if (f.teamUnread >= 5) return { key: 'mood.team', vars: { count: f.teamUnread }, level: 'ok', to: '/team' }

  if (h.uptime_s < 600) return { key: 'mood.fresh', level: 'ok' }
  if (f.running >= 3) return { key: 'mood.busy', vars: { count: f.running }, level: 'ok', to: '/sessions' }
  if (f.running > 0) return { key: 'mood.working', vars: { count: f.running }, level: 'ok', to: '/sessions' }
  if (five && five.pct >= 50 && five.reset) return { key: 'mood.quotaFiveFine', when: { reset: five.reset }, level: 'ok', to: usage }
  if (f.hour < 5) return { key: 'mood.night', level: 'ok' }
  if (h.uptime_s >= 30 * 86400) return { key: 'mood.steady', vars: { days: Math.floor(h.uptime_s / 86400) }, level: 'ok' }
  return { key: 'shell.allGood', level: 'ok' }
}

/** The status line of the sidebar (and of the touch menu): the mood, its text in the user's language. */
export function useMood(): Mood & { text: string } {
  const t = useT()
  const lang = useLang()
  const pages = useNav()
  const has = (to: string) => pages.some((p) => p.to === to)
  const { data: health } = useHealth()
  const { data: usage } = useUsage(true, true)
  const { data: feed } = useFeed()
  const { data: ws } = useWorkspace()
  const { data: team } = useTeam(has('/team'))
  const agents = useAgentsAttention(has('/agents'))
  // the sentences are a dictionary group of their own (the first page does not wait for them)
  useEffect(() => void loadGroups(['mood']), [])
  let sessionsUnread = 0
  let running = 0
  for (const p of ws?.projects || [])
    for (const tp of p.topics) {
      sessionsUnread += tp.unread
      running += tp.running
    }
  const date = new Date()
  const now = date.getTime() / 1000
  const mood = pickMood({
    health,
    usage,
    feedUnread: feed?.unread ?? 0,
    sessionsUnread,
    running,
    teamUnread: team?.chats.reduce((n, c) => n + (c.muted ? 0 : c.unread), 0) || 0,
    agents,
    now,
    hour: date.getHours(),
  })
  // "16:40" today, "Fri 16:40" another day ("Friday" when the text names days)
  const at = (ts: number) => {
    const today = new Date(ts * 1000).toDateString() === date.toDateString()
    if (!today && mood.when?.days) return fmtDate(ts, lang, undefined, { dateStyle: undefined, timeStyle: undefined, weekday: 'long' })
    return fmtDate(ts, lang, undefined, { dateStyle: undefined, timeStyle: undefined, weekday: today ? undefined : 'short', hour: '2-digit', minute: '2-digit' })
  }
  const vars: TVars = { ...mood.vars }
  if (mood.when?.hit) vars.hit = at(mood.when.hit)
  if (mood.when?.reset) vars.reset = at(mood.when.reset)
  const text = t(mood.key, vars)
  // '' while the sentences download: nothing to say yet
  if (!text) return { key: 'health.checking', level: 'idle', text: t('health.checking') }
  return { ...mood, text }
}
