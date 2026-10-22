import * as React from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Input } from './input'

/** Password/token input with a show/hide toggle. Never autofilled by password managers unless `autoComplete` says so. */
export function SecretInput({ className, autoComplete = 'off', ...props }: React.ComponentProps<'input'>) {
  const t = useT()
  const [show, setShow] = React.useState(false)
  return (
    <div className={cn('relative', className)}>
      <Input
        {...props}
        type={show ? 'text' : 'password'}
        autoComplete={autoComplete}
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
        className="pr-10 font-mono"
      />
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        aria-label={show ? t('common.hide') : t('common.show')}
        aria-pressed={show}
        className="absolute inset-y-0 right-0 flex w-10 pointer-coarse:w-11 items-center justify-center rounded-r-md text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  )
}
