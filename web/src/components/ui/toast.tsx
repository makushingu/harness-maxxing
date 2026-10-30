import { Toaster as Sonner, toast as sonner } from 'sonner'
import { useUI, resolveTheme } from '@/stores/ui'
import { useIsMobile } from '@/stores/media'

/** Mounted once in App. Bottom-right on desktop, top-center on mobile (clear of the tab bar). */
export function Toaster() {
  const theme = useUI((s) => s.theme)
  const mobile = useIsMobile()
  return (
    <Sonner
      theme={theme === 'system' ? resolveTheme('system') : theme}
      position={mobile ? 'top-center' : 'bottom-right'}
      offset={mobile ? { top: 'calc(var(--safe-top) + 8px)' } : 16}
      closeButton
      toastOptions={{
        classNames: {
          toast: '!bg-popover !text-popover-foreground !border-border !shadow-pop !rounded-lg !font-sans',
          description: '!text-muted-foreground',
          actionButton: '!bg-primary !text-primary-foreground pointer-coarse:!h-10 pointer-coarse:!px-4',
          closeButton: '!bg-popover !border-border !text-muted-foreground pointer-coarse:before:absolute pointer-coarse:before:-inset-3',
        },
      }}
    />
  )
}

/** Toasts = results of user actions (saved, failed…). Form validation errors are shown inline. */
export const toast = {
  success: (msg: string, description?: string) => sonner.success(msg, { description }),
  error: (msg: string, description?: string) => sonner.error(msg, { description, duration: 7000 }),
  info: (msg: string, description?: string) => sonner(msg, { description }),
  /** A notice with one action button (e.g. "Open"). */
  action: (msg: string, description: string | undefined, action: { label: string; onClick: () => void }) => sonner(msg, { description, action, duration: 8000 }),
  promise: sonner.promise,
  dismiss: sonner.dismiss,
}
