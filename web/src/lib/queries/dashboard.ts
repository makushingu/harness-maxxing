import * as React from 'react'
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { api, errorMessage, seg } from '../api'
import type { DashboardLayout, DashboardPayload, Ok, Widget } from '../types'
import { qk } from './keys'
import { useMut } from './util'

export const dashboardQuery = () => ({ queryKey: qk.dashboard.all, queryFn: () => api.get<DashboardPayload>('/api/dashboard'), staleTime: 30_000 })
export function useDashboard() {
  return useQuery(dashboardQuery())
}

const patchWidget = (qc: QueryClient, w: Widget) =>
  qc.setQueryData<DashboardPayload>(qk.dashboard.all, (old) => (old ? { ...old, widgets: old.widgets.map((x) => (x.id === w.id ? w : x)) } : old))

/** Force-refresh one widget and patch it into the dashboard cache (no full reload, no layout jump). */
export function useRefreshWidget() {
  const qc = useQueryClient()
  return useMut((id: string) => api.get<Widget>(`/api/dashboard/widgets/${seg(id)}`, { force: 1 }), {
    onSuccess: (w) => patchWidget(qc, w),
  })
}

/** The widgets the dashboard answered without (`pending`, still computing): fetched one by one, patched in. Each
 *  is asked once while its request runs: one arriving (the list changes) neither drops nor asks again the others. */
export function useFillPendingWidgets(widgets: Widget[] | undefined) {
  const qc = useQueryClient()
  const asked = React.useRef(new Set<string>())
  const live = React.useRef(true)
  React.useEffect(() => {
    live.current = true
    return () => {
      live.current = false
    }
  }, [])
  const ids = (widgets || []).filter((w) => w.pending).map((w) => w.id).join('\n')
  React.useEffect(() => {
    if (!ids) return
    for (const id of ids.split('\n')) {
      if (asked.current.has(id)) continue
      asked.current.add(id)
      api
        .get<Widget>(`/api/dashboard/widgets/${seg(id)}`)
        .then(
          (w) => live.current && patchWidget(qc, w),
          (err) => {
            // A failed request: the error card and its Retry button, never a skeleton forever.
            if (!live.current) return
            const w = qc.getQueryData<DashboardPayload>(qk.dashboard.all)?.widgets.find((x) => x.id === id)
            if (w) patchWidget(qc, { ...w, pending: false, error: errorMessage(err) })
          },
        )
        .finally(() => asked.current.delete(id))
    }
  }, [ids, qc])
}

export function useSaveLayout() {
  return useMut((b: DashboardLayout) => api.put<Ok>('/api/dashboard/layout', b), { invalidate: [qk.dashboard.all] })
}
