// Settings -> Webhooks / Events (API.md "Webhooks & events"). The bus topic `webhooks` refreshes all of it.
import { useQuery } from '@tanstack/react-query'
import { api, seg } from '../api'
import type { Ok, Webhook, WebhookCall, WebhookCallDetail, WebhookData, WebhooksPayload } from '../types'
import { qk } from './keys'
import { useMut } from './util'

export const webhooksQuery = () => ({ queryKey: qk.webhooks.list, queryFn: () => api.get<WebhooksPayload>('/api/webhooks') })
export function useWebhooks() {
  return useQuery(webhooksQuery())
}
export function useWebhookCalls(id: string | null, limit = 20) {
  return useQuery({
    queryKey: [...qk.webhooks.calls(id || ''), limit],
    queryFn: () => api.get<{ calls: WebhookCall[] }>(`/api/webhooks/${seg(id!)}/calls`, { limit }),
    enabled: !!id,
  })
}
export function useWebhookCall(id: string, call: string | null) {
  return useQuery({
    queryKey: qk.webhooks.call(id, call || ''),
    queryFn: () => api.get<WebhookCallDetail>(`/api/webhooks/${seg(id)}/calls/${seg(call!)}`),
    enabled: !!call,
  })
}
export function useWebhookData(id: string | null, limit = 20) {
  return useQuery({
    queryKey: [...qk.webhooks.data(id || ''), limit],
    queryFn: () => api.get<WebhookData>(`/api/webhooks/${seg(id!)}/data`, { limit }),
    enabled: !!id,
  })
}
/** The CSV download of a store hook (a plain link: the cookie signs it in). */
export const webhookCsvUrl = (id: string) => `/api/webhooks/${seg(id)}/data?format=csv`

const inv = [qk.webhooks.all] as const
const patchList = (id: string, b: Partial<Webhook>) => (old: WebhooksPayload) => ({ ...old, hooks: old.hooks.map((h) => (h.id === id ? { ...h, ...b } : h)) })

/** The on / off switch: instant, rolled back when refused. */
export function useToggleWebhook() {
  return useMut(({ id, enabled }: { id: string; enabled: boolean }) => api.patch<Webhook>(`/api/webhooks/${seg(id)}`, { enabled }), {
    optimistic: ({ id, enabled }) => [{ key: qk.webhooks.list, update: patchList(id, { enabled }) }],
    invalidate: inv,
  })
}
export function useDeleteWebhook() {
  return useMut((id: string) => api.del<Ok>(`/api/webhooks/${seg(id)}`), {
    optimistic: (id) => [{ key: qk.webhooks.list, update: (old: WebhooksPayload) => ({ ...old, hooks: old.hooks.filter((h) => h.id !== id) }) }],
    invalidate: inv,
  })
}
export function useRotateWebhook() {
  return useMut((id: string) => api.post<Webhook>(`/api/webhooks/${seg(id)}/rotate`), { invalidate: inv })
}
export function useTestWebhook() {
  return useMut((id: string) => api.post<{ id: string; status: string }>(`/api/webhooks/${seg(id)}/test`), { invalidate: inv })
}
export function useReplayWebhookCall() {
  return useMut(({ id, call }: { id: string; call: string }) => api.post<{ id: string; status: string }>(`/api/webhooks/${seg(id)}/calls/${seg(call)}/replay`), { invalidate: inv })
}
/** Set (or remove with "") the signing secret / access key of an incoming hook. */
export function useWebhookSecret(id: string, successToast: string) {
  return useMut((secret: string) => api.post<Webhook>(`/api/webhooks/${seg(id)}/secret`, { secret }), { invalidate: inv, successToast })
}
/** Create (no id) or change a hook from the form of Settings -> Webhooks / Events. `trigger` and `action` are sent
 *  whole (the server replaces top-level keys), so the form merges them with what it does not show. */
export function useSaveWebhook() {
  return useMut(
    ({ id, ...b }: { id?: string; name: string; description: string; trigger: object; action: object; report: string; secret?: string }) =>
      id ? api.patch<Webhook>(`/api/webhooks/${seg(id)}`, b) : api.post<Webhook>('/api/webhooks', b),
    { invalidate: inv, errorToast: false },
  )
}
