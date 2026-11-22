import type * as React from 'react'
import { Toaster as Sonner, toast as sonner } from 'sonner'
import { useUI, resolveTheme } from '@/stores/ui'
import { useIsMobile } from '@/stores/media'

/** Mounted once in App. Bottom-right on desktop, bottom-center on a phone: within thumb reach, and clear of the
 * header buttons a toast at the top covered (a swipe down dismisses it). */
export function Toaster() {
  const theme = useUI((s) => s.theme)
  const mobile = useIsMobile()
  // A tap on a toast stays on it: an open dialog or sheet (the file viewer...) takes a pointerdown outside it for a
  // dismissal (Radix listens on the document, which this stops short of), and its pointer-events: none on the body
  // let the tap fall through to what is behind (globals.css gives the toasts pointer-events back).
  return (
    <div className="contents" onPointerDown={(e) => e.stopPropagation()}>
      <Sonner
        theme={theme === 'system' ? resolveTheme('system') : theme}
        position={mobile ? 'bottom-center' : 'bottom-right'}
        offset={mobile ? { bottom: 'calc(var(--safe-bottom-ui) + 8px)' } : { bottom: 16, right: 'var(--mx-bubbles-w, 16px)' }}
        mobileOffset={{ bottom: 'calc(var(--safe-bottom-ui) + 8px)' }} // sonner's own offset under 600 px wide
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
    </div>
  )
}

/** Toasts = results of user actions (saved, failed…). Form validation errors are shown inline. */
export const toast = {
  success: (msg: string, description?: string) => sonner.success(msg, { description }),
  error: (msg: string, description?: string) => sonner.error(msg, { description, duration: 7000 }),
  info: (msg: string, description?: string) => sonner(msg, { description }),
  /** A notice with one action button (e.g. "Open"). */
  action: (msg: string, description: string | undefined, action: { label: string; onClick: () => void }, duration = 8000) => sonner(msg, { description, action, duration }),
  /** A card of its own in the stack (a Team message): it stays until `dismiss(id)`, or a swipe on a phone. */
  card: (id: string, render: () => React.ReactElement, onGone?: () => void) => sonner.custom(render, { id, duration: Infinity, onDismiss: onGone }),
  promise: sonner.promise,
  dismiss: sonner.dismiss,
}
