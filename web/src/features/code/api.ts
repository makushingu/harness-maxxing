// Changes view: what a session changed in git repositories (server: maxxing/codediff.py, api/code.py) and the
// git actions behind it. The viewer (features/files/Viewer.tsx) shows them through `mx-changes:` paths.
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export type ChangeStatus = 'A' | 'M' | 'D' | 'R' | 'C' | 'T'
export type ChangedFile = { path: string; old: string | null; status: ChangeStatus; add: number; del: number; binary: boolean }
export type RepoChanges = {
  root: string
  name: string
  branch: string | null
  upstream?: string | null
  ahead?: number
  behind?: number
  remote?: string | null
  /** Photo (or commit) before / after. */
  pre: string
  post: string
  /** First touched during the turn: compared with the last commit. */
  approx?: boolean
  files: ChangedFile[]
  more?: number
  add: number
  del: number
  error?: string
}
export type ChangesScope = 'turn' | 'session' | 'uncommitted' | 'branch'
export type Changes = { scope: ChangesScope; n: number | null; repos: RepoChanges[] }
export type { ChangesEvent } from '@/lib/types'

export type DiffLine = { t: ' ' | '+' | '-'; o: number | null; n: number | null; s: string }
export type FileDiff = { path: string; hunks: { head: string; o: number; n: number; lines: DiffLine[] }[]; binary: boolean; cut: boolean; lines: number }
export type RepoStatus = {
  root: string
  name: string
  branch: string | null
  upstream: string | null
  ahead: number
  behind: number
  /** Files a commit would take. */
  dirty: number
  github: string | null
  pr: { number: number; url: string; title: string; draft: boolean; base: string } | null
  checks: { total: number; ok: number; failed: number; pending: number } | null
  github_error?: string
}
export type Undo = { root: string; undo: string }

export const codeKeys = {
  changes: (sid: string, scope: ChangesScope, n: number | null) => ['code', 'changes', sid, scope, n] as const,
  diff: (repo: string, a: string, b: string, path: string, full: boolean) => ['code', 'diff', repo, a, b, path, full] as const,
  status: (repo: string) => ['code', 'status', repo] as const,
}

export function useChanges(sid: string, scope: ChangesScope, n: number | null) {
  return useQuery({
    queryKey: codeKeys.changes(sid, scope, n),
    queryFn: () => api.get<Changes>(`/api/sessions/${encodeURIComponent(sid)}/changes`, { scope, ...(n != null && scope === 'turn' ? { n } : {}) }),
    staleTime: scope === 'turn' ? 60_000 : 2_000,
  })
}

export function useFileDiff(repo: string, a: string, b: string, path: string, old: string | null, full: boolean) {
  return useQuery({
    queryKey: codeKeys.diff(repo, a, b, path, full),
    queryFn: () => api.get<FileDiff>('/api/code/diff', { repo, a, b, path, ...(old ? { old } : {}), ...(full ? { full: 1 } : {}) }),
    staleTime: b === 'now' ? 0 : Infinity,
  })
}

export function useRepoStatus(repo: string, enabled = true) {
  return useQuery({ queryKey: codeKeys.status(repo), queryFn: () => api.get<RepoStatus>('/api/code/status', { repo }), enabled, staleTime: 30_000, retry: false })
}

export const codeApi = {
  restore: (repo: string, source: string, paths?: string[]) => api.post<{ undo: string; restored: string[]; removed: string[] }>('/api/code/restore', { repo, source, paths }),
  undo: (repos: Undo[]) => api.post<{ repos: unknown[] }>('/api/code/undo', { repos }),
  revert: (sid: string, n: number) => api.post<{ n: number; repos: (Undo & { name: string; commits_kept: boolean })[] }>(`/api/sessions/${encodeURIComponent(sid)}/revert`, { n }),
  commit: (repo: string, message: string, push: boolean) => api.post<RepoStatus & { sha: string; pushed?: boolean }>('/api/code/commit', { repo, message, push }),
  push: (repo: string) => api.post<RepoStatus>('/api/code/push', { repo }),
  branch: (repo: string, name: string) => api.post<RepoStatus>('/api/code/branch', { repo, name }),
  pr: (repo: string) => api.post<{ number: number; url: string; title: string }>('/api/code/pr', { repo }),
  message: (repo: string, a = 'HEAD', b = 'now') => api.post<{ message: string }>('/api/code/message', { repo, a, b }),
}

// ---- viewer paths ----------------------------------------------------------------------------------------------
// `mx-changes:list|<sid>|<scope>|<n>` = the list of a view; `mx-changes:file|<sid>|<scope>|<n>|<root>|<path>` = one
// file of it (its diff). The fields are URI-encoded, so `|` never appears inside one.
export const CHANGES_PREFIX = 'mx-changes:'
export type ChangesRef = { sid: string; scope: ChangesScope; n: number | null; root?: string; path?: string }
const enc = encodeURIComponent

export function changesPath(r: ChangesRef): string {
  const head = [r.sid, r.scope, r.n ?? ''].map((x) => enc(String(x)))
  return r.root && r.path != null
    ? `${CHANGES_PREFIX}file|${[...head, enc(r.root), enc(r.path)].join('|')}`
    : `${CHANGES_PREFIX}list|${head.join('|')}`
}

export function parseChangesPath(p: string): ChangesRef | null {
  if (!p.startsWith(CHANGES_PREFIX)) return null
  const [kind, ...f] = p.slice(CHANGES_PREFIX.length).split('|').map(decodeURIComponent)
  const [sid, scope, n] = f
  if (!sid || !scope) return null
  const ref: ChangesRef = { sid, scope: scope as ChangesScope, n: n ? Number(n) : null }
  if (kind === 'file') return { ...ref, root: f[3], path: f[4] }
  return ref
}

export const isChangesPath = (p: string) => p.startsWith(CHANGES_PREFIX)

/** Asks the session column `sid` to put `text` in its composer's quotes (the viewer is outside the column). */
export const QUOTE_EVENT = 'mx-code-quote'
export function quoteInSession(sid: string, text: string) {
  window.dispatchEvent(new CustomEvent(QUOTE_EVENT, { detail: { sid, text } }))
}
