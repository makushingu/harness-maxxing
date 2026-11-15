// An agent's devices in its info panel: the person's devices its project may use, each with its switch (agent.json
// `devices`; off by default). Nothing while Devices is off or no device exists.
import { Laptop, Smartphone } from 'lucide-react'
import { useT } from '@/i18n'
import { useDevices, usePatchAgent, useSettings } from '@/lib/queries'
import { Switch } from '@/components/ui'

export function AgentDevicesCard({ path, devices }: { path: string; devices: string[] }) {
  const t = useT()
  const { data: s } = useSettings()
  const on = !!s?.devices_feature
  const { data: st } = useDevices(on)
  const patch = usePatchAgent()
  if (!on || !st?.devices.some((d) => d.confirmed)) return null
  const project = path.split('/')[1]
  const mine = st.devices.filter((d) => d.confirmed && (d.scope.includes('*') || d.scope.includes(`project:${project}`) || d.scope.includes(`agent:${path}`)))
  return (
    <section className="grid min-w-0 gap-2" data-testid="agent-devices-card">
      <h3 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('devices.agent.title')}</h3>
      <p className="text-[12px] text-muted-foreground">{mine.length ? t('devices.agent.hint') : t('devices.agent.none')}</p>
      {mine.map((d) => {
        const I = d.os === 'android' ? Smartphone : Laptop
        const checked = devices.includes(d.id)
        return (
          <label key={d.id} className="flex min-w-0 cursor-pointer items-center gap-2 text-[13px] pointer-coarse:min-h-10">
            <I className="size-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate">
              {d.name} <span className="text-[11px] text-muted-foreground">{d.mode === 'view' ? t('devices.mode.view') : t('devices.mode.control')}</span>
            </span>
            <Switch checked={checked} onCheckedChange={(v) => patch.mutate({ path, devices: v ? [...devices, d.id] : devices.filter((x) => x !== d.id) })} />
          </label>
        )
      })}
    </section>
  )
}
