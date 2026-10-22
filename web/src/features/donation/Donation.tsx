// Donation links (docs/user/23-license.md): Harness Maxxing is free, donations fund its development. Only links to
// the donation page of the website (new tab); the app never talks to a payment service. Settings -> Support shows
// the card; the other mentions (What's new, Feedback sent, License) disappear with the setting `donation_hidden`.
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

/** One discreet line: `text` then the link. Renders nothing when the mentions are hidden. */
export function DonationLine({ text, link = 'donation.link', className }: { text?: TKey; link?: TKey; className?: string }) {
  const t = useT()
  const lang = useLang()
  if (!useDonationShown()) return null
  return (
    <p className={cn('text-xs text-muted-foreground', className)} data-testid="donation-line">
      <Heart className="mr-1 inline size-3 align-[-1px]" aria-hidden />
      {text && <>{t(text)} </>}
      <a href={donationUrl(lang)} target="_blank" rel="noopener" className="font-medium text-primary hover:underline">
        {t(link)}
        <ExternalLink className="ml-0.5 inline size-3 align-[-1px]" aria-hidden />
      </a>
    </p>
  )
}
