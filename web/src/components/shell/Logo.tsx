import { cn } from '@/lib/utils'
import { logoSrc } from '@/lib/accent'
import * as React from 'react'
import { resolveTheme, useUI } from '@/stores/ui'

/** `boot`: where the boot logo of index.html lands (the first visible one). The theme in use may bring its own logo
 *  (per mode); one that cannot load (signed out: theme files need a session) falls back to the Harness logo. */
export function LogoMark({ className, boot }: { className?: string; boot?: boolean }) {
  const accent = useUI((s) => s.accent)
  const logo = useUI((s) => s.customTheme?.logo)
  const mode = useUI((s) => s.customTheme?.mode ?? resolveTheme(s.theme))
  const own = logo ? logo[mode] : null
  const [failed, setFailed] = React.useState<string | null>(null)
  return (
    <img
      src={own && failed !== own ? own : logoSrc(accent)}
      onError={() => own && setFailed(own)}
      alt=""
      width={28}
      height={28}
      draggable={false}
      data-boot-logo={boot || undefined}
      className={cn('size-7 shrink-0 select-none', own && failed !== own && 'rounded-md object-contain', className)}
      aria-hidden
    />
  )
}

export function Logo({ collapsed, className, nameClassName, boot }: { collapsed?: boolean; className?: string; nameClassName?: string; boot?: boolean }) {
  return (
    <span className={cn('flex min-w-0 items-center gap-2.5', className)}>
      <LogoMark boot={boot} />
      {!collapsed && <span className={cn('truncate text-[15px] font-semibold tracking-tight', nameClassName)}>Harness Maxxing</span>}
    </span>
  )
}
