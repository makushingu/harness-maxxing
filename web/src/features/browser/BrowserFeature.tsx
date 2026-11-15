// The Harness Browser's switch: off by default; once on, every session has it (a project or a topic can say no: its
// menu -> Browser) and an agent once turned on (its settings -> Browser). Here: the switch and what this server lacks
// (Set up), at the top of Settings -> Browser and in Settings -> Features (with a link to Settings -> Browser).
// BrowserSettingsForm: the settings shared by every profile (asking the user, downloads, sleep, profiles at once,
// waiting for a connection), a card of Settings -> Browser.
import * as React from 'react'
import { Link } from 'react-router'
import { ChevronDown, MonitorPlay, Wrench } from 'lucide-react'
import { useT } from '@/i18n'
import { useBrowserSetup, useBrowserStatus, useSaveBrowserSettings, useSaveSettings, useSettings } from '@/lib/queries'
import type { BrowserSettings } from '@/lib/types'
import { Button, Select, Switch } from '@/components/ui'
import { Callout, SettingRow } from '@/features/common'
import { SettingsCard } from '@/pages/settings/sections/ui'

const WAITS = [10, 30, 60, 120, 240, 1440]
const CHOICES = { idle_min: [15, 30, 60, 120, 240], tab_sleep_min: [10, 20, 30, 60, 120], max_tabs: [4, 8, 12, 20], max_active_profiles: [1, 2, 3, 4, 6], exit_wait_s: [60, 180, 300, 600] }

export function BrowserFeature({ link }: { link?: boolean }) {
  const t = useT()
  const { data: s } = useSettings()
  const save = useSaveSettings()
  const on = !!s?.browser_feature
  const { data: st } = useBrowserStatus(on)
  const setup = useBrowserSetup()
  return (
    <SettingsCard title={t('browser.feature.title')} description={t('browser.feature.desc')}>
      <div className="divide-y" data-testid="browser-feature" data-tour="browser-feature">
        <SettingRow label={t('browser.feature.enable')} description={t('browser.feature.enableDesc')} htmlFor="ft-browser">
          <Switch id="ft-browser" checked={on} onCheckedChange={(v) => save.mutate({ browser_feature: v })} />
        </SettingRow>
        {on && st && !st.available.ok && (
          <div className="py-3">
            <Callout
              tone="warning"
              title={t('browser.notReady')}
              action={
                <Button size="sm" variant="outline" loading={setup.isPending || st.setup.running} onClick={() => setup.mutate()}>
                  <Wrench /> {t('browser.setup')}
                </Button>
              }
            >
              {t('browser.notReadyDesc', { missing: st.available.missing.join(', ') })}
              {(st.setup.running || st.setup.error) && (
                <pre className="mt-2 max-h-32 overflow-auto rounded bg-muted p-2 text-[11px] whitespace-pre-wrap">{[...st.setup.log.slice(-6), st.setup.error || ''].join('\n')}</pre>
              )}
            </Callout>
          </div>
        )}
        {on && link && (
          <div className="flex flex-wrap items-center gap-2 py-3">
            <Button size="sm" variant="outline" asChild>
              <Link to="/settings/browser" data-testid="browser-open-page">
                <MonitorPlay /> {t('browser.openPage')}
              </Link>
            </Button>
            <span className="text-[12px] text-muted-foreground">{t('browser.openPageHint')}</span>
          </div>
        )}
      </div>
    </SettingsCard>
  )
}

/** Settings shared by every profile; every change saves at once. */
export function BrowserSettingsForm() {
  const t = useT()
  const { data: st } = useBrowserStatus()
  const save = useSaveBrowserSettings()
  const [more, setMore] = React.useState(false)
  if (!st) return null
  const s = st.settings
  const set = (v: Partial<BrowserSettings>) => save.mutate(v)
  const pick = (k: keyof typeof CHOICES, label: (n: number) => string) => (
    <Select
      className="h-8 w-36"
      value={String(s[k])}
      onValueChange={(v) => set({ [k]: Number(v) })}
      aria-label={t(`browser.feature.${k}` as 'browser.feature.idle_min')}
      options={[...new Set([...CHOICES[k], s[k]])].sort((a, b) => a - b).map((n) => ({ value: String(n), label: label(n) }))}
    />
  )
  const minutes = (n: number) => (n >= 60 ? t('browser.hours', { count: n / 60 }) : t('browser.minutes', { count: n }))
  return (
    <div className="grid gap-4" data-testid="browser-settings">
      <div className="divide-y">
        <SettingRow label={t('browser.ask')} description={t('browser.askDesc')} htmlFor="br-ask">
          <Switch id="br-ask" checked={s.ask} onCheckedChange={(v) => set({ ask: v })} />
        </SettingRow>
        <SettingRow label={t('browser.feature.exit_wait_s')} description={t('browser.feature.exitWaitDesc')}>
          {pick('exit_wait_s', (n) => minutes(Math.round(n / 60)))}
        </SettingRow>
      </div>
      <div>
        <button type="button" className="inline-flex items-center gap-1 text-[13px] font-medium text-muted-foreground hover:text-foreground pointer-coarse:min-h-10" onClick={() => setMore(!more)} aria-expanded={more} data-testid="browser-more">
          <ChevronDown className={more ? 'size-4 rotate-180 transition-transform' : 'size-4 transition-transform'} /> {t('browser.more')}
        </button>
        {more && (
          <div className="mt-2 divide-y">
            {s.ask && (
              <SettingRow label={t('browser.wait')} description={t('browser.waitDesc')}>
                <Select
                  className="h-8 w-36"
                  value={String(s.wait_min)}
                  onValueChange={(v) => set({ wait_min: Number(v) })}
                  aria-label={t('browser.wait')}
                  options={[...new Set([...WAITS, s.wait_min])].sort((a, b) => a - b).map((m) => ({ value: String(m), label: minutes(m) }))}
                />
              </SettingRow>
            )}
            <SettingRow label={t('browser.feature.max_active_profiles')} description={t('browser.feature.maxProfilesDesc')}>
              {pick('max_active_profiles', (n) => String(n))}
            </SettingRow>
            <SettingRow label={t('browser.feature.tab_sleep_min')} description={t('browser.feature.tabSleepDesc')}>
              {pick('tab_sleep_min', minutes)}
            </SettingRow>
            <SettingRow label={t('browser.feature.idle_min')} description={t('browser.feature.idleDesc')}>
              {pick('idle_min', minutes)}
            </SettingRow>
            <SettingRow label={t('browser.feature.max_tabs')} description={t('browser.feature.maxTabsDesc')}>
              {pick('max_tabs', (n) => String(n))}
            </SettingRow>
            <SettingRow label={t('browser.feature.search')} description={t('browser.feature.searchDesc')} htmlFor="br-search">
              <Select
                id="br-search"
                className="w-40"
                value={s.search}
                onValueChange={(v) => set({ search: v as typeof s.search })}
                options={[
                  { value: 'google', label: 'Google' },
                  { value: 'duckduckgo', label: 'DuckDuckGo' },
                  { value: 'bing', label: 'Bing' },
                ]}
              />
            </SettingRow>
            <SettingRow label={t('browser.downloads')} description={t('browser.downloadsDesc')} htmlFor="br-dl">
              <Switch id="br-dl" checked={s.downloads} onCheckedChange={(v) => set({ downloads: v })} />
            </SettingRow>
          </div>
        )}
      </div>
    </div>
  )
}
