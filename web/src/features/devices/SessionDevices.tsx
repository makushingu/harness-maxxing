// Devices in a session: a line above the composer while Claude uses one of the person's devices ("Claude is using
// Pixel 7" + Watch), and a card per request of Claude on a device (ask_human: Open, Skip). A new request opens the
// device's window by itself (once: closing it is respected).
import * as React from 'react'
import { Hand, MonitorSmartphone, SkipForward } from 'lucide-react'
import { useT } from '@/i18n'
import { useAnswerDeviceAsk, useSessionDevices, useSettings } from '@/lib/queries'
import type { Session } from '@/lib/types'
import { Button } from '@/components/ui'
import { DeviceWindow } from './DeviceWindow'

const opened = new Set<string>()

/** Nothing unless Devices is on. */
export function SessionDevicesBar({ session }: { session: Session | undefined }) {
  const { data: s } = useSettings()
  if (!s?.devices_feature || !session) return null
  return <Bar session={session} />
}

function Bar({ session }: { session: Session }) {
  const t = useT()
  const { data } = useSessionDevices(session.id, session.state === 'running' || !!session.device_asks)
  const answer = useAnswerDeviceAsk()
  const [win, setWin] = React.useState<{ id: string; name: string } | null>(null)
  const asks = data?.asks || []
  const using = session.state === 'running' ? data?.using || [] : []
  const fresh = asks.find((a) => !opened.has(a.id))
  React.useEffect(() => {
    if (!fresh) return
    opened.add(fresh.id)
    setWin({ id: fresh.device, name: fresh.device_name })
  }, [fresh])
  if (!asks.length && !using.length && !win) return null
  return (
    <div className="mx-auto grid w-full max-w-(--mx-read,860px) shrink-0 gap-1.5 px-3 pb-2" data-testid="session-devices">
      {asks.map((a) => (
        <div key={a.id} className="mx-rise flex min-w-0 flex-wrap items-center gap-2 rounded-lg border border-warning/50 bg-warning/8 px-2.5 py-1.5 text-[13px]" data-testid="session-device-ask">
          <Hand className="size-3.5 shrink-0 text-warning" />
          <span className="min-w-0 flex-1">
            <span className="font-medium">{t('devices.ask.title', { name: a.device_name })}</span> {a.message}
          </span>
          <Button size="sm" className="h-6 px-2.5 text-xs" onClick={() => setWin({ id: a.device, name: a.device_name })}>
            {t('devices.ask.open')}
          </Button>
          <Button size="sm" variant="ghost" className="h-6 px-2 text-xs" onClick={() => answer.mutate({ id: a.id, action: 'skip' })}>
            <SkipForward className="size-3.5" /> {t('devices.ask.skip')}
          </Button>
        </div>
      ))}
      {!asks.length &&
        using.map((d) => (
          <div key={d.id} className="flex min-w-0 items-center gap-2 rounded-lg border bg-card py-1 pr-1 pl-2.5 text-[13px]">
            <MonitorSmartphone className="size-3.5 shrink-0 animate-pulse text-primary" />
            <span className="min-w-0 flex-1 truncate font-medium">{t('devices.bar.using', { name: d.name })}</span>
            <Button size="sm" variant="outline" className="h-6 px-2 text-xs" onClick={() => setWin({ id: d.id, name: d.name })} data-testid="session-device-watch">
              {t('devices.bar.watch')}
            </Button>
          </div>
        ))}
      {win && <DeviceWindow id={win.id} name={win.name} open onOpenChange={(v) => !v && setWin(null)} />}
    </div>
  )
}
