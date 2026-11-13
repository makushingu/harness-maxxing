// Settings -> Features: the Harness Browser. Off by default; once on, each topic (its menu -> Browser) and each agent
// (its settings -> Browser) may be let use it. Here: what this server lacks (Set up) and the browser's own settings
// (one browser for the server): which sites, sign-ins kept, asking the user, downloads, when tabs / the browser sleep.
import * as React from 'react'
import { Link } from 'react-router'
import { ChevronDown, Eraser, MonitorPlay, Wrench } from 'lucide-react'
import { useT } from '@/i18n'
import { useBrowserAction, useBrowserSetup, useBrowserStatus, useSaveBrowserSettings, useSaveSettings, useSettings } from '@/lib/queries'
import type { BrowserSettings } from '@/lib/types'
import { Button, confirm, Segmented, Select, Switch } from '@/components/ui'
import { Callout, SettingRow } from '@/features/common'
import { ListEditor } from '@/features/agents/AgentSettings'
import { SettingsCard } from '@/pages/settings/sections/ui'

const WAITS = [10, 30, 60, 120, 240, 1440]
const CHOICES = { idle_min: [15, 30, 60, 120, 240], tab_sleep_min: [10, 20, 30, 60, 120], max_tabs: [4, 8, 12, 20] }

export function BrowserFeature() {
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
        {on && st && <BrowserSettingsForm />}
      </div>
    </SettingsCard>
  )
}

/** The browser's own settings; every change saves at once (the server restarts it when nobody uses it if needed). */
export function BrowserSettingsForm() {
  const t = useT()
  const { data: st } = useBrowserStatus()
  const save = useSaveBrowserSettings()
  const action = useBrowserAction()
  const [more, setMore] = React.useState(false)
  const [siteError, setSiteError] = React.useState<string | null>(null)
  if (!st) return null
  const s = st.settings
  const set = (v: Partial<BrowserSettings>, done?: () => void) =>
    save.mutate(v, { onSuccess: () => (setSiteError(null), done?.()), onError: (e) => setSiteError(String((e as Error).message)) })
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
    <div className="grid gap-4 py-3" data-testid="browser-settings">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" asChild>
          <Link to="/browser" data-testid="browser-open-page">
            <MonitorPlay /> {t('browser.openPage')}
          </Link>
        </Button>
        <span className="text-[12px] text-muted-foreground">{t('browser.openPageHint')}</span>
      </div>
      <div className="grid gap-2">
        <p className="text-sm font-medium">{t('browser.sites')}</p>
        <Segmented
          aria-label={t('browser.sites')}
          value={s.web}
          onChange={(v) => set({ web: v })}
          options={[
            { value: 'list', label: t('browser.web.list') },
            { value: 'public', label: t('browser.web.public') },
          ]}
        />
        {s.web === 'list' ? (
          <ListEditor value={s.sites} onChange={(l, saved) => set({ sites: l }, saved)} placeholder={t('browser.sitesPlaceholder')} empty={t('browser.sitesEmpty')} error={siteError} testid="browser-sites" />
        ) : (
          <p className="text-[13px] text-muted-foreground">{t('browser.web.publicDesc')}</p>
        )}
      </div>
      <div className="divide-y">
        <SettingRow label={t('browser.keep')} description={t('browser.keepDesc')} htmlFor="br-keep">
          <Switch id="br-keep" checked={s.profile === 'keep'} onCheckedChange={(v) => set({ profile: v ? 'keep' : 'fresh' })} />
        </SettingRow>
        <SettingRow label={t('browser.ask')} description={t('browser.askDesc')} htmlFor="br-ask">
          <Switch id="br-ask" checked={s.ask} onCheckedChange={(v) => set({ ask: v })} />
        </SettingRow>
      </div>
      <div>
        <button type="button" className="inline-flex items-center gap-1 text-[13px] font-medium text-muted-foreground hover:text-foreground" onClick={() => setMore(!more)} aria-expanded={more} data-testid="browser-more">
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
            <SettingRow label={t('browser.feature.tab_sleep_min')} description={t('browser.feature.tabSleepDesc')}>
              {pick('tab_sleep_min', minutes)}
            </SettingRow>
            <SettingRow label={t('browser.feature.idle_min')} description={t('browser.feature.idleDesc')}>
              {pick('idle_min', minutes)}
            </SettingRow>
            <SettingRow label={t('browser.feature.max_tabs')} description={t('browser.feature.maxTabsDesc')}>
              {pick('max_tabs', (n) => String(n))}
            </SettingRow>
            <SettingRow label={t('browser.downloads')} description={t('browser.downloadsDesc')} htmlFor="br-dl">
              <Switch id="br-dl" checked={s.downloads} onCheckedChange={(v) => set({ downloads: v })} />
            </SettingRow>
            <SettingRow label={t('browser.forget')} description={t('browser.forgetDesc')}>
              <Button
                size="sm"
                variant="outline"
                disabled={!st.profile && !st.browser.tabs.length}
                loading={action.isPending && action.variables?.action === 'forget'}
                onClick={async () => {
                  if (await confirm({ title: t('browser.forgetTitle'), description: t('browser.forgetConfirm'), destructive: true, confirmText: t('browser.forget') }))
                    action.mutate({ action: 'forget' })
                }}
                data-testid="browser-forget"
              >
                <Eraser /> {t('browser.forget')}
              </Button>
            </SettingRow>
          </div>
        )}
      </div>
    </div>
  )
}
