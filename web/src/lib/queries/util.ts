import { useMutation, useQueryClient, type QueryKey, type UseMutationOptions } from '@tanstack/react-query'
import { toast } from '@/components/ui/toast'
import { errorMessage } from '../api'

type MutOpts<TData, TVars> = Omit<UseMutationOptions<TData, Error, TVars>, 'mutationFn'> & {
  /** Query key prefixes to invalidate after success (a function: read when the call succeeds, see unlessBus). */
  invalidate?: readonly QueryKey[] | (() => readonly QueryKey[])
  /** Toast shown on success (string or builder). */
  successToast?: string | ((data: TData, vars: TVars) => string | null)
  /** Show a toast on error (default true). Set false when the form shows the error inline. */
  errorToast?: boolean
  /**
   * Instant UI for toggles and small edits: patches the cached queries under each key prefix before the request
   * is sent, puts them back if it fails. The server's answer / the invalidation then reconciles.
   */
  optimistic?: (vars: TVars) => Optimistic[]
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Optimistic = { key: QueryKey; update: (old: any) => any }
type Snapshot = [QueryKey, unknown][]

/**
 * useMutation with the app conventions: invalidation of related queries and toasts.
 * Inline form errors: pass `errorToast: false` and read `mutation.error`.
 */
export function useMut<TData, TVars = void>(fn: (vars: TVars) => Promise<TData>, opts: MutOpts<TData, TVars> = {}) {
  const qc = useQueryClient()
  const { invalidate, successToast, errorToast = true, onSuccess, onError, optimistic, ...rest } = opts
  return useMutation<TData, Error, TVars>({
    mutationFn: fn,
    ...rest,
    ...(optimistic && {
      onMutate: async (vars: TVars) => {
        const patches = optimistic(vars)
        await Promise.all(patches.map((o) => qc.cancelQueries({ queryKey: o.key })))
        const snapshot: Snapshot = []
        for (const o of patches) {
          for (const [key, data] of qc.getQueriesData({ queryKey: o.key })) {
            snapshot.push([key, data])
            if (data !== undefined) qc.setQueryData(key, o.update(data))
          }
        }
        return { snapshot }
      },
    }),
    onSuccess: async (data, vars, ...more) => {
      // The hook's own onSuccess first (it usually writes the server's answer into the cache): the screen shows
      // the result right away instead of after every invalidated query has been fetched again.
      const out = await onSuccess?.(data, vars, ...more)
      const keys = typeof invalidate === 'function' ? invalidate() : invalidate
      if (keys) await Promise.all(keys.map((k) => qc.invalidateQueries({ queryKey: k })))
      if (successToast) {
        const msg = typeof successToast === 'function' ? successToast(data, vars) : successToast
        if (msg) toast.success(msg)
      }
      return out
    },
    onError: (err, vars, ctx, ...more) => {
      // Refused: the optimistic change goes back (the toast says why).
      const snap = (ctx as { snapshot?: Snapshot } | undefined)?.snapshot
      if (optimistic && snap) for (const [key, data] of snap) qc.setQueryData(key, data)
      if (errorToast) toast.error(errorMessage(err))
      return onError?.(err, vars, ctx, ...more)
    },
  })
}
