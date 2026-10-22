import * as React from 'react'
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { api, seg } from '../api'
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

/** The widgets the dashboard answered without (`pending`, still computing): fetched one by one, patched in. */
export function useFillPendingWidgets(widgets: Widget[] | undefined) {
  const qc = useQueryClient()
  const ids = (widgets || []).filter((w) => w.pending).map((w) => w.id).join('\n')
  React.useEffect(() => {
    if (!ids) return
    let live = true
    for (const id of ids.split('\n'))
      api.get<Widget>(`/api/dashboard/widgets/${seg(id)}`).then(
        (w) => live && patchWidget(qc, w),
        () => undefined,
      )
    return () => {
      live = false
    }
  }, [ids, qc])
}

export function useSaveLayout() {
  return useMut((b: DashboardLayout) => api.put<Ok>('/api/dashboard/layout', b), { invalidate: [qk.dashboard.all] })
}
