import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, seg } from '../api'
import type { Ok, Task, TaskBulkBody, TaskBulkResult, TaskInput, TaskProject, TaskProjectInput, TasksPayload } from '../types'
import { qk } from './keys'
import { useMut } from './util'

export const tasksQuery = () => ({ queryKey: qk.tasks, queryFn: () => api.get<TasksPayload>('/api/tasks') })
export function useTasks() {
  return useQuery(tasksQuery())
}

export function useCreateTask() {
  return useMut((b: TaskInput & { title: string }) => api.post<Task>('/api/tasks', b), { invalidate: [qk.tasks] })
}

/** Optimistic: the card moves immediately; rolled back on error. */
export function usePatchTask(scopeId?: string) {
  const qc = useQueryClient()
  return useMut(({ id, ...b }: TaskInput & { id: string }) => api.patch<Task>(`/api/tasks/${seg(id)}`, b), {
    ...(scopeId ? { scope: { id: `task:${scopeId}` } } : {}),
    onMutate: async ({ id, ...b }) => {
      await qc.cancelQueries({ queryKey: qk.tasks })
      const prev = qc.getQueryData<TasksPayload>(qk.tasks)
      if (prev) qc.setQueryData<TasksPayload>(qk.tasks, { ...prev, tasks: prev.tasks.map((t) => (t.id === id ? ({ ...t, ...b } as Task) : t)) })
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      const c = ctx as { prev?: TasksPayload } | undefined
      if (c?.prev) qc.setQueryData(qk.tasks, c.prev)
    },
    invalidate: [qk.tasks],
  })
}
/** One change on many tasks (or delete them), optimistic like usePatchTask. */
export function useBulkTasks() {
  const qc = useQueryClient()
  return useMut((b: TaskBulkBody) => api.post<TaskBulkResult>('/api/tasks/bulk', b), {
    onMutate: async (b) => {
      await qc.cancelQueries({ queryKey: qk.tasks })
      const prev = qc.getQueryData<TasksPayload>(qk.tasks)
      if (prev) {
        const ids = new Set(b.ids)
        const tasks = b.delete
          ? prev.tasks.filter((t) => !ids.has(t.id))
          : prev.tasks.map((t) => {
              if (!ids.has(t.id)) return t
              let labels = t.labels
              if (b.labels_remove?.length) labels = labels.filter((l) => !b.labels_remove!.includes(l))
              if (b.labels_add?.length) labels = [...labels, ...b.labels_add.filter((l) => !labels.includes(l))]
              return { ...t, ...b.patch, labels } as Task
            })
        qc.setQueryData<TasksPayload>(qk.tasks, { ...prev, tasks })
      }
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      const c = ctx as { prev?: TasksPayload } | undefined
      if (c?.prev) qc.setQueryData(qk.tasks, c.prev)
    },
    invalidate: [qk.tasks],
  })
}
export function useDeleteTask() {
  return useMut((id: string) => api.del<Ok>(`/api/tasks/${seg(id)}`), { invalidate: [qk.tasks] })
}
export function useCreateTaskProject() {
  return useMut((b: TaskProjectInput) => api.post<TaskProject>('/api/tasks/projects', b), { invalidate: [qk.tasks] })
}
export function usePatchTaskProject() {
  return useMut(({ id, ...b }: Partial<TaskProjectInput> & { id: string }) => api.patch<TaskProject>(`/api/tasks/projects/${seg(id)}`, b), {
    invalidate: [qk.tasks],
  })
}
export function useDeleteTaskProject() {
  return useMut((id: string) => api.del<Ok>(`/api/tasks/projects/${seg(id)}`), { invalidate: [qk.tasks] })
}
