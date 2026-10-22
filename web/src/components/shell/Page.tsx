// Page scaffolding. Every routed page renders <Page> (or <PageHeader> + its own body for full-bleed
// layouts like Sessions). The header is the page's top bar on desktop AND mobile; in the touch layout it carries the
// two buttons that open the sessions (left) and the app menu (right).
import * as React from 'react'
import { cn } from '@/lib/utils'
import { useCompact } from '@/stores/media'
import { TouchAppButton, TouchSessionsButton } from './TouchNav'

export function useDocumentTitle(title?: string) {
  React.useEffect(() => {
    document.title = title ? `${title} · Harness Maxxing` : 'Harness Maxxing'
  }, [title])
}

export function PageHeader({
  title,
  description,
  actions,
  leading,
  className,
  sensitiveTitle,
}: {
  title: React.ReactNode
  description?: React.ReactNode
  /** Right-aligned actions (buttons). Keep ≤ 3 on mobile; overflow into a "…" menu. */
  actions?: React.ReactNode
  /** Left element before the title (back button, breadcrumb root). */
  leading?: React.ReactNode
  className?: string
  /** document.title string (when `title` is a node). */
  sensitiveTitle?: string
}) {
  const touch = useCompact()
  useDocumentTitle(typeof title === 'string' ? title : sensitiveTitle)
  return (
    <header
      className={cn(
        'sticky top-0 z-20 flex shrink-0 items-center gap-3 border-b bg-background/95 px-4 max-md:gap-2 max-md:px-3 md:px-6',
        'min-h-[calc(var(--header-h)+var(--safe-top))] pt-[var(--safe-top)]',
        className,
      )}
    >
      {touch && <TouchSessionsButton />}
      {leading}
      <div className="flex min-w-0 flex-1 flex-col justify-center py-2">
        <h1 className="truncate text-[15px] leading-tight font-semibold tracking-tight md:text-base">{title}</h1>
        {description && <p className="truncate text-[13px] text-muted-foreground max-md:hidden">{description}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {actions}
        {touch && <TouchAppButton />}
      </div>
    </header>
  )
}

const widths = {
  narrow: 'max-w-3xl',
  default: 'max-w-6xl',
  wide: 'max-w-[1600px]',
  full: 'max-w-none',
}

/** Standard page: sticky header + scrolling body with a centered container. */
export function Page({
  title,
  description,
  actions,
  leading,
  width = 'default',
  className,
  bodyClassName,
  children,
}: {
  title: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
  leading?: React.ReactNode
  width?: keyof typeof widths
  className?: string
  bodyClassName?: string
  children: React.ReactNode
}) {
  return (
    <div className={cn('flex min-h-0 flex-1 flex-col', className)}>
      <PageHeader title={title} description={description} actions={actions} leading={leading} />
      <PageBody width={width} className={bodyClassName}>
        {children}
      </PageBody>
    </div>
  )
}

export function PageBody({ width = 'default', className, children }: { width?: keyof typeof widths; className?: string; children: React.ReactNode }) {
  return (
    <div className="min-h-0 flex-1">
      <div className={cn('mx-auto w-full px-4 py-5 md:px-6 md:py-6', widths[width], className)}>{children}</div>
    </div>
  )
}

/** Section inside a page (settings blocks, dashboard groups). */
export function Section({ title, description, actions, children, className }: { title?: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn('grid gap-4', className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="grid gap-1">
            {title && <h2 className="text-[15px] font-semibold tracking-tight">{title}</h2>}
            {description && <p className="max-w-2xl text-sm text-muted-foreground">{description}</p>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  )
}
