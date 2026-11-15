// A device live in a window, the same everywhere: Settings -> Devices (Watch), "Watch" above a session's composer, a
// request of Claude (ask_human). Full screen on a phone. Closing it only stops the pictures.
import * as React from 'react'
import { useT } from '@/i18n'
import { Dialog, DialogContent, DialogDescription, DialogTitle, Skeleton } from '@/components/ui'

const DeviceLive = React.lazy(() => import('./DeviceLive').then((m) => ({ default: m.DeviceLive })))

export function DeviceWindow({ id, name, open, onOpenChange }: { id: string; name?: string; open: boolean; onOpenChange: (v: boolean) => void }) {
  const t = useT()
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        hideClose
        onOpenAutoFocus={(e) => e.preventDefault()}
        className="gap-0 overflow-hidden p-0 md:p-0 max-md:inset-0 max-md:max-h-none max-md:rounded-none max-md:pt-(--safe-top) max-md:pb-(--safe-bottom) md:h-[min(92dvh,1200px)] md:max-h-none md:w-[min(96vw,1600px)] md:max-w-none [&>div[aria-hidden]:first-child]:hidden"
        data-testid="device-window"
      >
        <DialogTitle className="sr-only">{t('devices.live.title', { name: name || '' })}</DialogTitle>
        <DialogDescription className="sr-only">{t('devices.live.desc')}</DialogDescription>
        <React.Suspense fallback={<Skeleton className="m-4 h-80" />}>{open && <DeviceLive id={id} onClose={() => onOpenChange(false)} className="h-full" />}</React.Suspense>
      </DialogContent>
    </Dialog>
  )
}
