// Settings -> Notifications -> Mobile notifications: one switch for this device (permission, subscription and
// registration in one go), a test, and the registered devices.
import * as React from 'react'
import { BellRing, Smartphone, Trash2 } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, errorMessage, seg } from '@/lib/api'
import { useT } from '@/i18n'
import { Button, Switch, toast } from '@/components/ui'
import { Callout, SettingRow } from '@/features/common'
import { SettingsCard } from '@/pages/settings/sections/ui'
import { disablePush, enablePush, needsInstall, pushDevicesKey, pushSupported, thisDevice, type PushDevice } from './push'

function deviceLabel(): string {
  const ua = navigator.userAgent
  const os = /Android/.test(ua) ? 'Android' : /iPhone|iPad|iPod/.test(ua) ? 'iOS' : /Windows/.test(ua) ? 'Windows' : /Mac/.test(ua) ? 'macOS' : /Linux/.test(ua) ? 'Linux' : ''
  const br = /Firefox/.test(ua) ? 'Firefox' : /Edg\//.test(ua) ? 'Edge' : /Chrome/.test(ua) ? 'Chrome' : /Safari/.test(ua) ? 'Safari' : ''
  return [br, os].filter(Boolean).join(' · ')
}

export function PushSettings() {
  const t = useT()
  const qc = useQueryClient()
  const supported = pushSupported()
  const { data: devices } = useQuery({ queryKey: pushDevicesKey, queryFn: () => api.get<PushDevice[]>('/api/push/devices'), enabled: supported })
  const [mine, setMine] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [perm, setPerm] = React.useState<NotificationPermission | null>(() => (supported ? Notification.permission : null))
  const refresh = React.useCallback(() => {
    void thisDevice().then(setMine).catch(() => setMine(null))
    void qc.invalidateQueries({ queryKey: pushDevicesKey })
  }, [qc])
  React.useEffect(() => {
    if (supported) void thisDevice().then(setMine).catch(() => setMine(null))
  }, [supported])
  // The server forgot this device (it was removed from another one): the switch follows.
  const registered = !!mine && !!devices?.some((d) => d.id === mine)

  const toggle = async (on: boolean) => {
    setBusy(true)
    try {
      if (on) await enablePush(deviceLabel())
      else await disablePush()
    } catch (e) {
      const m = e instanceof Error ? e.message : ''
      toast.error(m === 'denied' ? t('push.denied') : m === 'no-worker' ? t('push.noWorker') : errorMessage(e))
    } finally {
      setPerm(Notification.permission)
      setBusy(false)
      refresh()
    }
  }
  const test = async () => {
    try {
      const r = await api.post<{ sent: number }>('/api/push/test')
      if (r.sent) toast.success(t('push.testSent'))
      else toast.error(t('push.testNone'))
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }
  const remove = async (d: PushDevice) => {
    try {
      if (d.id === mine) await disablePush()
      else await api.del(`/api/push/devices/${seg(d.id)}`)
    } catch (e) {
      toast.error(errorMessage(e))
    }
    refresh()
  }

  return (
    <SettingsCard
      title={t('push.title')}
      description={t('push.desc')}
      actions={
        <Button variant="outline" size="sm" onClick={() => void test()} disabled={!devices?.length}>
          <BellRing /> {t('push.test')}
        </Button>
      }
    >
      {!supported ? (
        <Callout tone="info">{needsInstall() ? t('push.install') : t('push.unsupported')}</Callout>
      ) : (
        <>
          <SettingRow label={t('push.here')} description={t('push.hereDesc')} htmlFor="mx-push-here">
            <Switch id="mx-push-here" checked={registered} disabled={busy} onCheckedChange={(v) => void toggle(v)} />
          </SettingRow>
          {perm === 'denied' && !registered && (
            <Callout tone="warning" className="mt-4">
              {t('push.denied')}
            </Callout>
          )}
          {!!devices?.length && (
            <div className="mt-4 divide-y rounded-lg border">
              {devices.map((d) => (
                <div key={d.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <Smartphone className="size-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate">
                    {d.label || t('push.device')}
                    {d.id === mine && <span className="ml-2 text-xs text-muted-foreground">{t('push.thisOne')}</span>}
                  </span>
                  <Button variant="ghost" size="icon" aria-label={t('push.remove')} onClick={() => void remove(d)}>
                    <Trash2 />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </SettingsCard>
  )
}
