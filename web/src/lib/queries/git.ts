import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { GitCommitDetail, GitGraph, GitOverview, GitPull } from '../types'

// Read-only git view (server/maxxing/gitview.py). `repo` = a path on the server or `github:owner/name`.
export const gitKeys = {
  all: ['git'] as const,
  repos: ['git', 'repos'] as const,
  graph: (repo: string, limit: number, branches: string) => ['git', 'graph', repo, limit, branches] as const,
  commit: (repo: string, sha: string) => ['git', 'commit', repo, sha] as const,
  pulls: (repo: string) => ['git', 'pulls', repo] as const,
}

export function useGitRepos() {
  return useQuery({ queryKey: gitKeys.repos, queryFn: () => api.get<GitOverview>('/api/git/repos'), staleTime: 30_000 })
}
export const refreshGitRepos = () => api.get<GitOverview>('/api/git/repos', { refresh: 1 })

export function useGitGraph(repo: string | null, opts: { limit?: number; branches?: string[] } = {}) {
  const limit = opts.limit ?? 200
  const branches = (opts.branches || []).join(',')
  return useQuery({
    queryKey: gitKeys.graph(repo || '', limit, branches),
    queryFn: () => api.get<GitGraph>('/api/git/graph', { repo: repo!, limit, ...(branches ? { branches } : {}) }),
    enabled: !!repo,
    staleTime: 15_000,
    retry: false,
    placeholderData: keepPreviousData,
  })
}
export function useGitCommit(repo: string | null, sha: string | null) {
  return useQuery({
    queryKey: gitKeys.commit(repo || '', sha || ''),
    queryFn: () => api.get<GitCommitDetail>('/api/git/commit', { repo: repo!, sha: sha! }),
    enabled: !!repo && !!sha,
    staleTime: Infinity,
    retry: false,
  })
}
export function useGitPulls(repo: string | null) {
  return useQuery({
    queryKey: gitKeys.pulls(repo || ''),
    queryFn: () => api.get<GitPull[]>('/api/git/pulls', { repo: repo! }),
    enabled: !!repo && repo.startsWith('github:'),
    staleTime: 60_000,
    retry: false,
  })
}
