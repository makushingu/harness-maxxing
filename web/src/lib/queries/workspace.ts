import { useQuery } from '@tanstack/react-query'
import { api, seg } from '../api'
import type { NameBody, Ok, PatchNameBody, Project, Topic, WorkspaceTree } from '../types'
import { qk } from './keys'
import { useMut } from './util'

export const workspaceQuery = () => ({ queryKey: qk.workspace, queryFn: () => api.get<WorkspaceTree>('/api/workspace/tree') })
export function useWorkspace() {
  return useQuery(workspaceQuery())
}

/** Flat list of topics (handy for selects and the command palette). */
export function useTopics() {
  const q = useWorkspace()
  const topics: Topic[] = q.data ? q.data.projects.flatMap((p) => p.topics) : []
  return { ...q, topics }
}

const inv = [qk.workspace, qk.onboarding] as const

export function useCreateProject() {
  return useMut((b: NameBody) => api.post<Project>('/api/workspace/projects', b), { invalidate: inv, errorToast: false })
}
export function usePatchProject() {
  return useMut(({ project, ...b }: PatchNameBody & { project: string }) => api.patch<Project>(`/api/workspace/projects/${seg(project)}`, b), {
    invalidate: [...inv, qk.sessions.all],
  })
}
export function useDeleteProject() {
  return useMut((project: string) => api.del<Ok>(`/api/workspace/projects/${seg(project)}`), { invalidate: inv })
}
export function useCreateTopic() {
  return useMut(({ project, ...b }: NameBody & { project: string }) => api.post<Topic>(`/api/workspace/projects/${seg(project)}/topics`, b), {
    invalidate: inv,
    errorToast: false,
  })
}
export function usePatchTopic() {
  return useMut(
    ({ project, topic, ...b }: PatchNameBody & { project: string; topic: string }) =>
      api.patch<Topic>(`/api/workspace/projects/${seg(project)}/topics/${seg(topic)}`, b),
    { invalidate: [...inv, qk.sessions.all] },
  )
}
export function useDeleteTopic() {
  return useMut(({ project, topic }: { project: string; topic: string }) => api.del<Ok>(`/api/workspace/projects/${seg(project)}/topics/${seg(topic)}`), {
    invalidate: inv,
  })
}

/** Drag and drop in the Sessions tree: the projects' order (saved on the server, same on every device). */
export function useReorderProjects() {
  return useMut((names: string[]) => api.put<{ projects: string[] }>('/api/workspace/order', { names }), {
    optimistic: (names) => [{
      key: qk.workspace,
      update: (old: WorkspaceTree) => ({ ...old, projects: [...old.projects].sort((a, b) => names.indexOf(a.name) - names.indexOf(b.name)) }),
    }],
    invalidate: [qk.workspace],
  })
}
/** The topics' order inside one project (a topic never changes project this way). */
export function useReorderTopics() {
  return useMut(({ project, names }: { project: string; names: string[] }) => api.put<{ topics: string[] }>(`/api/workspace/projects/${seg(project)}/order`, { names }), {
    optimistic: ({ project, names }) => [{
      key: qk.workspace,
      update: (old: WorkspaceTree) => ({
        ...old,
        projects: old.projects.map((p) => (p.name === project ? { ...p, topics: [...p.topics].sort((a, b) => names.indexOf(a.name) - names.indexOf(b.name)) } : p)),
      }),
    }],
    invalidate: [qk.workspace],
  })
}
