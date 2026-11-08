import { cn } from '@/lib/utils'
import { logoSrc } from '@/lib/accent'
import { useUI } from '@/stores/ui'

/** `boot`: where the boot logo of index.html lands (the first visible one). */
export function LogoMark({ className, boot }: { className?: string; boot?: boolean }) {
  const accent = useUI((s) => s.accent)
  return (
    <img
      src={logoSrc(accent)}
      alt=""
      width={28}
      height={28}
      draggable={false}
      data-boot-logo={boot || undefined}
      className={cn('size-7 shrink-0 select-none', className)}
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
