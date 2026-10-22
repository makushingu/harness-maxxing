// How to install the app in each browser (the dialog of "Install app" and Settings -> General -> App).
import * as React from 'react'
import { AppWindow, Compass, Download, EllipsisVertical, Globe, MoreHorizontal, PlusSquare, Share, Smartphone, TriangleAlert } from 'lucide-react'
import { useT, type TKey } from '@/i18n'
import { Segmented } from '@/components/ui'
import { cn } from '@/lib/utils'
import { INSTALL_PLATFORMS, detectPlatform, type InstallPlatform } from './index'

const STEPS: Record<InstallPlatform, React.ComponentType<{ className?: string }>[]> = {
  chrome: [Download, EllipsisVertical, AppWindow],
  edge: [Download, MoreHorizontal, AppWindow],
  safari: [Share, AppWindow],
  firefox: [TriangleAlert, Globe],
  ios: [Compass, Share, PlusSquare],
  android: [EllipsisVertical, Download, Smartphone],
}

/** The numbered steps of one platform. */
export function InstallSteps({ platform, compact }: { platform: InstallPlatform; compact?: boolean }) {
  const t = useT()
  return (
    <ol className={cn('grid', compact ? 'gap-2' : 'gap-3')}>
      {STEPS[platform].map((Icon, i) => (
        <li key={i} className={cn('flex items-center gap-3 rounded-lg border text-sm', compact ? 'p-2.5' : 'p-3')}>
          <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/12 text-primary">
            <Icon className="size-4" />
          </span>
          <span>{t(`pwa.steps.${platform}.${i + 1}` as TKey)}</span>
        </li>
      ))}
    </ol>
  )
}

/** Browser switch (starts on the one in use) + its steps; warns when the address is not https. */
export function InstallGuide({ only }: { only?: InstallPlatform[] }) {
  const t = useT()
  const list = only || INSTALL_PLATFORMS
  const [platform, setPlatform] = React.useState<InstallPlatform>(() => {
    const p = detectPlatform()
    return list.includes(p) ? p : list[0]
  })
  return (
    <div className="grid gap-3">
      {!window.isSecureContext && (
        <p className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 p-3 text-[13px]">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" />
          {t('pwa.needsHttps')}
        </p>
      )}
      <Segmented
        size="sm"
        value={platform}
        onChange={setPlatform}
        aria-label={t('pwa.browser')}
        options={list.map((p) => ({ value: p, label: t(`pwa.p.${p}` as TKey) }))}
      />
      <InstallSteps platform={platform} />
    </div>
  )
}
