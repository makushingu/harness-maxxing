import * as React from 'react'
import * as AD from '@radix-ui/react-alert-dialog'
import { create } from 'zustand'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { buttonVariants } from './button'
import { Input } from './input'

export const AlertDialog = AD.Root
export const AlertDialogTrigger = AD.Trigger

export function AlertDialogContent({ className, children, ...props }: React.ComponentProps<typeof AD.Content>) {
  return (
    <AD.Portal>
      <AD.Overlay className="fixed inset-0 z-50 bg-overlay data-[state=closed]:animate-overlay-out data-[state=open]:animate-overlay-in" />
      <AD.Content
        className={cn(
          'fixed z-50 grid gap-4 border bg-popover text-popover-foreground shadow-pop outline-none',
          'inset-x-0 bottom-[var(--kbd-inset)] max-h-[calc(var(--vvh,100dvh)*0.92)] overflow-y-auto overscroll-contain rounded-t-2xl p-5 pb-[calc(1.25rem+var(--safe-bottom))] data-[state=closed]:animate-sheet-down data-[state=open]:animate-sheet-up',
          'md:inset-auto md:top-1/2 md:left-1/2 md:w-full md:max-w-md md:-translate-x-1/2 md:-translate-y-1/2 md:rounded-xl md:p-6 md:data-[state=closed]:animate-out md:data-[state=open]:animate-in',
          className,
        )}
        {...props}
      >
        {children}
      </AD.Content>
    </AD.Portal>
  )
}
export const AlertDialogTitle = ({ className, ...p }: React.ComponentProps<typeof AD.Title>) => (
  <AD.Title className={cn('text-base font-semibold tracking-tight', className)} {...p} />
)
export const AlertDialogDescription = ({ className, ...p }: React.ComponentProps<typeof AD.Description>) => (
  <AD.Description className={cn('text-sm text-muted-foreground', className)} {...p} />
)
export const AlertDialogAction = AD.Action
export const AlertDialogCancel = AD.Cancel

/* ------------------------------------------------------------------------------------------
 * confirm({title, description, destructive, confirmText, typeToConfirm}) → Promise<boolean>
 * Imperative helper, rendered by <ConfirmHost/> (mounted once in App). Never use window.confirm.
 * ---------------------------------------------------------------------------------------- */
export type ConfirmOptions = {
  title: React.ReactNode
  description?: React.ReactNode
  destructive?: boolean
  confirmText?: string
  cancelText?: string
  /** User must type this exact string to enable the confirm button (dangerous, irreversible actions). */
  typeToConfirm?: string
}
type Pending = ConfirmOptions & { resolve: (v: boolean) => void }
const useConfirmStore = create<{ pending: Pending | null }>(() => ({ pending: null }))

export function confirm(opts: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    const prev = useConfirmStore.getState().pending
    prev?.resolve(false)
    useConfirmStore.setState({ pending: { ...opts, resolve } })
  })
}

export function ConfirmHost() {
  const t = useT()
  const pending = useConfirmStore((s) => s.pending)
  const [typed, setTyped] = React.useState('')
  const [open, setOpen] = React.useState(false)
  const last = React.useRef<Pending | null>(null)
  if (pending) last.current = pending
  React.useEffect(() => {
    setOpen(!!pending)
    setTyped('')
  }, [pending])
  const p = pending || last.current
  const close = (v: boolean) => {
    pending?.resolve(v)
    useConfirmStore.setState({ pending: null })
  }
  const blocked = !!p?.typeToConfirm && typed !== p.typeToConfirm
  return (
    <AlertDialog open={open} onOpenChange={(o) => !o && close(false)}>
      {p && (
        <AlertDialogContent>
          <div className="grid gap-2">
            <AlertDialogTitle>{p.title}</AlertDialogTitle>
            {p.description && <AlertDialogDescription asChild={typeof p.description !== 'string'}>{typeof p.description === 'string' ? p.description : <div>{p.description}</div>}</AlertDialogDescription>}
          </div>
          {p.typeToConfirm && (
            <div className="grid gap-2">
              <label className="text-[13px] text-muted-foreground" htmlFor="mx-confirm-type">
                {/* The text to type is a button: one click fills the field. */}
                {t('confirm.typeToConfirm', { text: '\u0001' }).split('\u0001').flatMap((part, i) =>
                  i === 0 ? [part] : [
                    <button key="fill" type="button" className="font-mono font-medium text-foreground underline decoration-dotted underline-offset-4 hover:text-primary" onClick={() => setTyped(p.typeToConfirm || '')}>
                      {p.typeToConfirm}
                    </button>,
                    part,
                  ],
                )}
              </label>
              <Input
                id="mx-confirm-type"
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.nativeEvent.isComposing && !blocked) {
                    e.preventDefault()
                    close(true)
                  }
                }}
                autoComplete="off"
                autoFocus
                spellCheck={false}
              />
            </div>
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <AlertDialogCancel className={buttonVariants({ variant: 'outline' })} onClick={() => close(false)}>
              {p.cancelText || t('common.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={blocked}
              className={buttonVariants({ variant: p.destructive ? 'destructive' : 'default' })}
              onClick={(e) => {
                if (blocked) {
                  e.preventDefault()
                  return
                }
                close(true)
              }}
            >
              {p.confirmText || (p.destructive ? t('common.delete') : t('common.confirm'))}
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      )}
    </AlertDialog>
  )
}
