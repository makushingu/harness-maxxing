// Separate copies (Code mode): a session on its own folder and branch of the topic's repository.
// Server: maxxing/worktrees.py, api/code.py (/api/code/copy-*, /api/sessions/{id}/copy*). Plan: plans/code-worktree-pr.md.
import { useQuery } from '@tanstack/react-query'
import { api, seg } from '@/lib/api'

export type CopyRepo = {
  root: string
  name: string
  branch: string | null
  branches: string[]
  default_base: string | null
  github: string | null
  prefs: { prefix: string; prepare: string; copy_env: boolean }
  error?: string
}
export type CopyStatus = {
  path: string
  repo: string
  branch: string
  base: string
  pr?: { number: number; url?: string; fork?: boolean; full?: string } | null
  prepare?: { cmd: string; state: 'running' | 'done' | 'failed' } | null
  env_copied?: string[]
  exists: boolean
  removed: boolean
  /** Commits of the branch not in its base / of the base not in the branch. */
  ahead?: number
  behind?: number
  /** Files a commit would take. */
  dirty?: number
  upstream?: string | null
  /** Commits not pushed yet. */
  pushed_ahead?: number
  github?: string | null
  fork?: boolean
}
export type CopyListed = CopyStatus & { sid: string; title: string; path: string; archived: boolean }

export const copyKeys = {
  repos: (path: string) => ['code', 'copy-repos', path] as const,
  status: (sid: string) => ['code', 'copy', sid] as const,
  all: ['code', 'copies'] as const,
}

export function useCopyRepos(path: string, enabled = true) {
  return useQuery({
    queryKey: copyKeys.repos(path),
    queryFn: () => api.get<{ enabled: boolean; repos: CopyRepo[] }>('/api/code/copy-repos', { path }),
    enabled,
    staleTime: 30_000,
    retry: false,
  })
}

export function useCopyStatus(sid: string, enabled = true) {
  return useQuery({ queryKey: copyKeys.status(sid), queryFn: () => api.get<CopyStatus>(`/api/sessions/${seg(sid)}/copy`), enabled, staleTime: 5_000, retry: false })
}

export function useCopies(enabled = true) {
  return useQuery({ queryKey: copyKeys.all, queryFn: () => api.get<CopyListed[]>('/api/code/copies'), enabled, staleTime: 30_000, retry: false })
}

export const copyApi = {
  merge: (sid: string, message?: string) => api.post<{ merged: boolean; base: string; kept_branch: string | null }>(`/api/sessions/${seg(sid)}/copy/merge`, { message }),
  remove: (sid: string, force: boolean) => api.post<{ removed: boolean; kept_branch: string | null }>(`/api/sessions/${seg(sid)}/copy/remove`, { force }),
  prefs: (repo: string, p: { prefix?: string; prepare?: string; copy_env?: boolean }) => api.put<CopyRepo['prefs']>('/api/code/copy-prefs', { repo, ...p }),
  prepareLog: (sid: string) => api.get<{ log: string }>(`/api/sessions/${seg(sid)}/copy/prepare-log`),
}

/** "Fix the login page!" -> "fix-the-login-page" (as the server names the branch). */
export function branchSlug(text: string): string {
  const t = text
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  if (t.length <= 40) return t
  const cut = t.slice(0, 40)
  return (cut.includes('-') ? cut.slice(0, cut.lastIndexOf('-')) : cut).replace(/-+$/, '')
}
