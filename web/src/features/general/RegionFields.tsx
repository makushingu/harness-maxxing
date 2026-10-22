import { LANGUAGES, useT } from '@/i18n'
import { timezoneLabel, timezoneOptions, browserTimezone } from '@/lib/timezones'
import { Button, FormField, Segmented } from '@/components/ui'
import { Combobox } from '@/components/ui/combobox'
import type { Language } from '@/lib/types'

/** Language + time zone (onboarding step 1, settings › General). Controlled. */
export function RegionFields({ language, timezone, onLanguage, onTimezone }: { language: Language; timezone: string; onLanguage: (l: Language) => void; onTimezone: (tz: string) => void }) {
  const t = useT()
  const detected = browserTimezone()
  return (
    <div className="grid gap-5">
      <FormField label={t('settings.language')} hint={t('settings.languageHint')}>
        <Segmented<Language> value={language} onChange={onLanguage} options={LANGUAGES.map((l) => ({ value: l.id, label: l.label }))} aria-label={t('settings.language')} />
      </FormField>
      <FormField
        label={t('settings.timezone')}
        hint={t('settings.timezoneHint')}
        aside={
          timezone !== detected ? (
            <Button variant="link" size="sm" className="h-auto text-[13px]" onClick={() => onTimezone(detected)}>
              {t('settings.useBrowserTz', { tz: detected })}
            </Button>
          ) : undefined
        }
      >
        <Combobox value={timezone} onChange={onTimezone} options={timezoneOptions} labelOf={timezoneLabel} searchPlaceholder={t('settings.searchTimezone')} />
      </FormField>
    </div>
  )
}
