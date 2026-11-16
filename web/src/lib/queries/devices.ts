import { useQuery } from '@tanstack/react-query'
import { api, seg } from '../api'
import type { Device, DeviceAsk, DeviceInvite, DevicesStatus, Ok, SessionDevices } from '../types'
import { useMut } from './util'

// Devices (api/devices.py): the person's computers and phones running Harness Link. The bus topic `devices` refreshes
// every key below (BUS_KEYS).
export const deviceKeys = {
  all: ['devices'] as const,
  status: ['devices', 'status'] as const,
  session: (sid: string) => ['devices', 'session', sid] as const,
}

/** `every`: refetch every N ms (a code waiting: the device shows up as soon as it pairs). */
export function useDevices(enabled = true, every?: number | false) {
  return useQuery({ queryKey: deviceKeys.status, queryFn: () => api.get<DevicesStatus>('/api/devices'), enabled, refetchInterval: every })
}

/** A one-time code (15 min) for one device: the commands, the phone's link. */
export function useNewInvite() {
  return useMut((v: { os?: string }) => api.post<DeviceInvite>('/api/devices/invites', v), { invalidate: [deviceKeys.all] })
}

export function useConfirmDevice() {
  return useMut(({ id, ok }: { id: string; ok: boolean }) => api.post<Ok>(`/api/devices/${seg(id)}/confirm`, { ok }), {
    invalidate: [deviceKeys.all],
  })
}

/** Rename, change its rights or who may use it. */
export function useSaveDevice() {
  return useMut(({ id, ...v }: { id: string; name?: string; mode?: 'view' | 'control'; scope?: string[]; display?: number }) => api.put<Device>(`/api/devices/${seg(id)}`, v), {
    invalidate: [deviceKeys.all, ['agents', 'one']],
    optimistic: ({ id, ...v }) => [{ key: deviceKeys.status, update: (s?: DevicesStatus) => s && { ...s, devices: s.devices.map((d) => (d.id === id ? { ...d, ...v } : d)) } }],
  })
}

export function useRemoveDevice() {
  return useMut((id: string) => api.del<Ok>(`/api/devices/${seg(id)}`), { invalidate: [deviceKeys.all, ['agents', 'one']] })
}

/** What a session's line shows: the devices its Claude uses now and its requests waiting. */
export function useSessionDevices(sid: string, enabled = true) {
  return useQuery({
    queryKey: deviceKeys.session(sid),
    queryFn: () => api.get<SessionDevices>(`/api/devices/session/${seg(sid)}`),
    enabled: enabled && !!sid,
    // "Claude is using it" fades out by itself once Claude stopped acting: look again now and then
    refetchInterval: (q) => (q.state.data?.using.length ? 5000 : false),
  })
}

export function useAnswerDeviceAsk() {
  return useMut(
    ({ id, action, note }: { id: string; action: 'done' | 'skip'; note?: string }) =>
      api.post<DeviceAsk>(`/api/devices/asks/${seg(id)}`, { action, ...(note ? { note } : {}) }),
    { invalidate: [deviceKeys.all, ['sessions'], ['agents', 'thread']] },
  )
}

/** A one-use token (30 s) for WS /api/devices/<id>/live. */
export function deviceLiveToken() {
  return api.post<{ token: string }>('/api/devices/live-token', {})
}
