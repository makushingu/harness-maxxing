// Web Push of this browser (Settings -> Notifications -> Mobile notifications): the server wakes the service worker
// with an empty push, which asks /api/push/pending what to show (see sw/sw.js and server/maxxing/webpush.py).
import { api, seg } from '@/lib/api'

export type PushDevice = { id: string; label: string; at: number }

export const pushDevicesKey = ['push', 'devices'] as const

export function pushSupported(): boolean {
  return typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

/** iPhone / iPad: Web Push only works for the app added to the Home Screen. */
export function needsInstall(): boolean {
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent)
  const standalone = window.matchMedia('(display-mode: standalone)').matches || (navigator as unknown as { standalone?: boolean }).standalone
  return ios && !standalone
}

async function registration(): Promise<ServiceWorkerRegistration | undefined> {
  return navigator.serviceWorker.getRegistration()
}

/** Same id as the server's (`webpush.device_id`): the first 16 hex digits of the SHA-256 of the endpoint. */
async function deviceId(endpoint: string): Promise<string> {
  const h = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(endpoint))
  return Array.from(new Uint8Array(h)).map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 16)
}

/** The id of this browser's device when it is registered, else null. */
export async function thisDevice(): Promise<string | null> {
  if (!pushSupported()) return null
  const sub = await (await registration())?.pushManager.getSubscription()
  return sub ? deviceId(sub.endpoint) : null
}

function keyBytes(b64: string): Uint8Array<ArrayBuffer> {
  const s = atob(b64.replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(s, (c) => c.charCodeAt(0))
}

/** Ask for the permission, subscribe and register this browser on the server. Throws 'denied' / 'no-worker'. */
export async function enablePush(label: string): Promise<string> {
  const reg = await registration()
  if (!reg) throw new Error('no-worker')
  if ((Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission) !== 'granted') throw new Error('denied')
  const { key } = await api.get<{ key: string }>('/api/push/key')
  const sub = (await reg.pushManager.getSubscription()) ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) }))
  const { id } = await api.post<PushDevice>('/api/push/devices', { endpoint: sub.endpoint, label })
  return id
}

/** Remove this browser: from the server first, then the subscription itself. */
export async function disablePush(): Promise<void> {
  const sub = await (await registration())?.pushManager.getSubscription()
  if (!sub) return
  await api.del(`/api/push/devices/${seg(await deviceId(sub.endpoint))}`).catch(() => {})
  await sub.unsubscribe().catch(() => {})
}
