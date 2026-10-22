import * as React from 'react'
import { Languages } from 'lucide-react'
import { useUI } from '@/stores/ui'
import { LANGUAGES, useT } from '@/i18n'
import { LogoMark } from '@/components/shell/Logo'
import { useDocumentTitle } from '@/components/shell/Page'
import { DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger, Button } from '@/components/ui'
import type { Language } from '@/lib/types'

export function LanguageMenu() {
  const t = useT()
  const lang = useUI((s) => s.language)
  const setLanguage = useUI((s) => s.setLanguage)
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" aria-label={t('settings.language')}>
          <Languages /> {LANGUAGES.find((l) => l.id === lang)?.label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuRadioGroup value={lang} onValueChange={(v) => setLanguage(v as Language)}>
          {LANGUAGES.map((l) => (
            <DropdownMenuRadioItem key={l.id} value={l.id}>
              {l.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Centered card layout for /setup and /login. */
export function AuthLayout({ title, subtitle, children, footer }: { title: string; subtitle?: React.ReactNode; children: React.ReactNode; footer?: React.ReactNode }) {
  useDocumentTitle(title)
  return (
    <div className="relative flex min-h-dvh flex-col overflow-hidden px-4 pt-[var(--safe-top)] pb-[var(--safe-bottom)]">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(60rem_30rem_at_50%_-10%,color-mix(in_oklch,var(--primary)_14%,transparent),transparent_70%)]"
      />
      <div aria-hidden className="pointer-events-none absolute inset-0 [background-image:radial-gradient(var(--color-border)_1px,transparent_1px)] [background-size:24px_24px] [mask-image:radial-gradient(ellipse_at_top,black,transparent_70%)]" />
      <header className="relative flex h-14 items-center justify-end">
        <LanguageMenu />
      </header>
      <main className="relative flex flex-1 items-start justify-center pt-[6vh] md:items-center md:pt-0">
        <div className="w-full max-w-[400px] animate-in">
          <div className="mb-6 flex flex-col items-center gap-4 text-center">
            <LogoMark className="size-11" />
            <div className="grid gap-1.5">
              <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
              {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
            </div>
          </div>
          <div className="rounded-xl border bg-card p-6 shadow-xs">{children}</div>
          {footer && <div className="mt-5 text-center text-[13px] text-muted-foreground">{footer}</div>}
        </div>
      </main>
    </div>
  )
}
