// Donation links (docs/user/23-license.md): Harness Maxxing is free, donations fund its development. Only links to
// the donation page of the website (new tab); the app never talks to a payment service. Settings -> Support shows
// the card; the other mentions (sidebar / touch menu, What's new, Feedback sent, License) disappear with the setting
// `donation_hidden`.
import { ExternalLink, Heart } from 'lucide-react'
import { useLang, useT, type TKey } from '@/i18n'
import { useSettings } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { Language } from '@/lib/types'

export const DONATION_URL = 'https://harness-maxxing.com/donation'

/** The donation page in the UI language (the site speaks en, fr, es, de, it, pt; English needs no parameter). */
export function donationUrl(lang: Language): string {
  return lang === 'en' ? DONATION_URL : `${DONATION_URL}?lang=${lang}`
}

/** False until the settings are known, then false when the user hid the mentions (never a flash of the link). */
export function useDonationShown(): boolean {
  const { data } = useSettings()
  return !!data && !data.donation_hidden
}

/** Tinted classes shared by the donate buttons: visible on every theme and accent, never the primary action. */
export const DONATE_TONE = 'border border-pink-500/35 bg-pink-500/10 text-pink-700 hover:bg-pink-500/20 dark:text-pink-300'

/** The "Donate" button: a link to the donation page (new tab). Renders nothing when the mentions are hidden. */
export function DonateButton({ label = 'donation.donate', className }: { label?: TKey; className?: string }) {
  const t = useT()
  const lang = useLang()
  if (!useDonationShown()) return null
  return (
    <a
      href={donationUrl(lang)}
      target="_blank"
      rel="noopener"
      data-testid="donate-button"
      className={cn('inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md px-3 text-[13px] font-semibold outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring', DONATE_TONE, className)}
    >
      <Heart className="size-3.5 fill-current" aria-hidden />
      {t(label)}
      <ExternalLink className="size-3 opacity-70" aria-hidden />
    </a>
  )
}

/** A short sentence and the Donate button next to it. Renders nothing when the mentions are hidden. */
export function DonationLine({ text, className }: { text?: TKey; className?: string }) {
  const t = useT()
  if (!useDonationShown()) return null
  return (
    <div className={cn('flex flex-wrap items-center gap-x-3 gap-y-2', className)} data-testid="donation-line">
      {text && <span className="text-[13px] text-muted-foreground">{t(text)}</span>}
      <DonateButton />
    </div>
  )
}
