// "Install app" when the browser has no one-click prompt to offer (Safari, Firefox, iOS, Android without it,
// Chrome / Edge before they offer it): the steps for this browser, the others one click away. Mounted once in the shell.
import { useT } from '@/i18n'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui'
import { LogoMark } from '@/components/shell/Logo'
import { usePWA } from './index'
import { InstallGuide } from './InstallSteps'

export function InstallDialog() {
  const t = useT()
  const open = usePWA((s) => s.helpOpen)
  const setOpen = usePWA((s) => s.setHelpOpen)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="md:max-w-xl" data-testid="install-dialog">
        <DialogHeader>
          <div className="mb-2 flex justify-center">
            <LogoMark className="size-12" />
          </div>
          <DialogTitle className="text-center">{t('pwa.guide.title')}</DialogTitle>
          <DialogDescription className="text-center">{t('pwa.installDesc')}</DialogDescription>
        </DialogHeader>
        {open && <InstallGuide />}
      </DialogContent>
    </Dialog>
  )
}
