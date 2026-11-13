// A pull request inside Harness (the PR view of the file viewer: `mx-pr:` paths). Server: gitview.github_pull and
// the /api/git/pull* routes; a session on a PR: /api/code/pr-session. Plan: plans/code-worktree-pr.md (lot 5).
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Session } from '@/lib/types'
import type { DiffLine } from './api'

export type PrPerson = { login: string; avatar: string }
export type PrFile = { path: string; old: string | null; status: 'A' | 'M' | 'D' | 'R' | 'C'; add: number; del: number; hunks: { head: string; o: number; n: number; lines: DiffLine[] }[]; binary: boolean; cut: boolean; lines: number; /** A text file too big for GitHub to send its diff. */ too_big?: boolean }
export type PrEntry = { kind: 'comment' | 'review'; id: number; author: PrPerson; body: string; state?: string; at: number; url?: string }
export type PrLineComment = { id: number; path: string; line: number | null; side: 'LEFT' | 'RIGHT'; author: PrPerson; body: string; at: number; reply_to: number | null; outdated: boolean }
export type PrCheck = { name: string; status: string | null; conclusion: string | null; url: string | null }
export type Pull = {
  full: string
  number: number
  title: string
  body: string
  author: PrPerson
  association: string
  outside: boolean
  state: 'open' | 'closed' | 'merged'
  draft: boolean
  mergeable: boolean | null
  mergeable_state: string | null
  head: string
  head_sha: string
  head_repo: string
  fork: boolean
  base: string
  url: string
  created: number
  updated: number
  commits: number
  add: number
  del: number
  files: PrFile[]
  files_total: number
  conversation: PrEntry[]
  line_comments: PrLineComment[]
  checks: PrCheck[]
  methods: ('squash' | 'merge' | 'rebase')[]
  can_write: boolean
  local_paths: string[]
}
export type ReviewEvent = 'APPROVE' | 'REQUEST_CHANGES' | 'COMMENT'
export type DraftComment = { path: string; line: number; side?: 'LEFT' | 'RIGHT'; body: string }

export const prKeys = { one: (full: string, n: number) => ['git', 'pull', full, n] as const }

export function usePull(full: string, n: number) {
  return useQuery({ queryKey: prKeys.one(full, n), queryFn: () => api.get<Pull>('/api/git/pull', { repo: `github:${full}`, number: n }), staleTime: 30_000, retry: false })
}

const at = (full: string, number: number) => ({ repo: `github:${full}`, number })
export const prApi = {
  comment: (full: string, n: number, body: string) => api.post('/api/git/pull/comment', { ...at(full, n), body }),
  review: (full: string, n: number, event: ReviewEvent, body: string, comments: DraftComment[] = []) => api.post('/api/git/pull/review', { ...at(full, n), event, body, comments }),
  merge: (full: string, n: number, method: string, sha?: string) => api.post<{ merged: boolean; message?: string }>('/api/git/pull/merge', { ...at(full, n), method, sha }),
  close: (full: string, n: number) => api.post('/api/git/pull/close', at(full, n)),
  session: (full: string, n: number, review: boolean, message?: string) => api.post<Session>('/api/code/pr-session', { ...at(full, n), review, message }),
}

/** Checks of a pull request in one word: failed > pending > ok (none: null). */
export function checksState(cs: PrCheck[]): 'failed' | 'pending' | 'ok' | null {
  if (!cs.length) return null
  if (cs.some((c) => ['failure', 'timed_out', 'cancelled', 'action_required'].includes(c.conclusion || ''))) return 'failed'
  if (cs.some((c) => c.status !== 'completed')) return 'pending'
  return 'ok'
}

// ---- viewer paths: `mx-pr:<owner/name>|<n>` = the PR (Conversation), `…|<n>|files` / `…|<n>|checks` its other
// tabs, `…|<n>|file|<path>` one file's diff. Fields URI-encoded.
export const PR_PREFIX = 'mx-pr:'
export type PrTab = 'conversation' | 'files' | 'checks'
export type PrRef = { full: string; n: number; tab: PrTab; path?: string }
const enc = encodeURIComponent

export function prPath(r: { full: string; n: number; tab?: PrTab; path?: string }): string {
  const head = `${PR_PREFIX}${enc(r.full)}|${r.n}`
  if (r.path != null) return `${head}|file|${enc(r.path)}`
  return r.tab && r.tab !== 'conversation' ? `${head}|${r.tab}` : head
}

export function parsePrPath(p: string): PrRef | null {
  if (!p.startsWith(PR_PREFIX)) return null
  const [full, n, kind, path] = p.slice(PR_PREFIX.length).split('|').map(decodeURIComponent)
  const num = Number(n)
  if (!full || !Number.isInteger(num) || num < 1) return null
  if (kind === 'file') return { full, n: num, tab: 'files', path: path ?? '' }
  return { full, n: num, tab: kind === 'files' || kind === 'checks' ? kind : 'conversation' }
}

export const isPrPath = (p: string) => p.startsWith(PR_PREFIX)
export const openPr = (full: string, n: number) => import('@/features/files/viewerStore').then((m) => m.openFileViewer(prPath({ full, n })))
