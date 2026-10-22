import type { LucideIcon } from 'lucide-react'
import { Sparkles } from 'lucide-react'
import { useT } from '@/i18n'
import { Badge } from '@/components/ui'
import { Page } from './Page'

/** Placeholder page used until a feature page is implemented. */
export function ComingSoon({ title, description, icon: Icon = Sparkles }: { title: string; description?: string; icon?: LucideIcon }) {
  const t = useT()
  return (
    <Page title={title}>
      <div className="relative flex min-h-[60vh] flex-col items-center justify-center overflow-hidden rounded-2xl border border-dashed px-6 py-16 text-center">
        <div aria-hidden className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,color-mix(in_oklch,var(--primary)_10%,transparent),transparent_65%)]" />
        <div className="relative flex size-14 items-center justify-center rounded-2xl border bg-card shadow-xs">
          <Icon className="size-6 text-primary" strokeWidth={1.7} />
        </div>
        <Badge variant="outline" className="relative mt-5">
          {t('common.comingSoon')}
        </Badge>
        <h2 className="relative mt-3 text-lg font-semibold tracking-tight">{title}</h2>
        <p className="relative mt-1 max-w-md text-sm text-muted-foreground">{description || t('common.comingSoonDesc')}</p>
      </div>
    </Page>
  )
}
