import * as React from 'react'
import { Check, CheckCircle2, Compass, Download, GraduationCap, Monitor, Moon, Sun } from 'lucide-react'
import { useSaveSettings, useSettings } from '@/lib/queries'
import { ACCENTS, useUI, type Accent, type Density, type Layout, type Theme, type Tint, type TouchHome } from '@/stores/ui'
import { cn } from '@/lib/utils'
import { FONT_GROUPS, loadFontPreview, MONO_FONTS, SANS_FONTS, type FontGroup } from '@/lib/fonts'
import { useT, type TKey } from '@/i18n'
import type { Language } from '@/lib/types'
import { Button, FormField, Input, Segmented, Skeleton, Tooltip, toast } from '@/components/ui'
import { QRCode } from '@/components/ui/qr-code'
import { Checkbox } from '@/components/ui/checkbox'
import { RegionFields } from '@/features/general/RegionFields'
import { SettingRow } from '@/features/common'
import { RESULT_FIELDS, useResultLine } from '@/pages/sessions/resultLine'
import { SettingsCard, SectionStack } from './ui'
import { useNavigate } from 'react-router'
import { startTour, useTutorialHref } from '@/tour/store'
import { installApp, isStandalone, useInstallMode, usePWA } from '@/pwa'
import { InstallGuide, InstallSteps } from '@/pwa/InstallSteps'

function HelpCard() {
  const t = useT()
  const navigate = useNavigate()
  const tutorial = useTutorialHref()
  return (
    <SettingsCard title={t('help.settingsTitle')} description={t('help.settingsDesc')}>
      <div className="divide-y">
        <SettingRow label={t('tour.take')} description={t('tour.takeDesc')}>
          <Button variant="outline" size="sm" onClick={startTour}>
            <Compass /> {t('tour.take')}
          </Button>
        </SettingRow>
        {tutorial && (
          <SettingRow label={t('tour.tutorial')} description={t('tour.tutorialDesc')}>
            <Button variant="outline" size="sm" onClick={() => navigate(tutorial!)}>
              <GraduationCap /> {t('tour.tutorial')}
            </Button>
          </SettingRow>
        )}
      </div>
    </SettingsCard>
  )
}

/** Settings -> General -> App: install on this computer (one click when the browser offers it, else its steps),
 *  and how to add it to a phone's home screen (with a QR code to open this address there). */
function AppCard() {
  const t = useT()
  const install = useInstallMode()
  const installed = usePWA((s) => s.installed) || isStandalone()
  const [guide, setGuide] = React.useState(false)
  return (
    <SettingsCard title={t('pwa.card.title')} description={t('pwa.installDesc')}>
      <div className="divide-y">
        <SettingRow label={t('pwa.card.here')} description={installed ? t('pwa.card.installed') : t('pwa.card.hereDesc')}>
          {installed ? (
            <span className="inline-flex items-center gap-1.5 text-sm font-medium text-success"><CheckCircle2 className="size-4" /> {t('pwa.card.done')}</span>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => void installApp()} data-testid="install-app">
                <Download /> {t('pwa.install')}
              </Button>
              {install === 'prompt' && (
                <Button variant="ghost" size="sm" onClick={() => setGuide((g) => !g)}>
                  {t('pwa.card.how')}
                </Button>
              )}
            </div>
          )}
        </SettingRow>
        {guide && (
          <div className="py-4">
            <InstallGuide />
          </div>
        )}
        <div className="grid gap-4 py-4">
          <div className="grid gap-1">
            <div className="text-sm font-medium">{t('pwa.card.phone')}</div>
            <p className="text-[13px] text-muted-foreground">{t('pwa.card.phoneDesc')}</p>
          </div>
          <div className="grid gap-4 md:grid-cols-[auto_1fr_1fr]">
            <div className="flex flex-col items-center gap-2 max-md:hidden">
              <QRCode value={window.location.origin} className="size-36 p-1" label={t('pwa.card.qr')} />
              <span className="max-w-36 text-center text-xs text-muted-foreground">{t('pwa.card.qr')}</span>
            </div>
            <div className="grid content-start gap-2">
              <div className="text-[13px] font-medium">{t('pwa.p.ios')}</div>
              <InstallSteps platform="ios" compact />
            </div>
            <div className="grid content-start gap-2">
              <div className="text-[13px] font-medium">{t('pwa.p.android')}</div>
              <InstallSteps platform="android" compact />
            </div>
          </div>
        </div>
      </div>
    </SettingsCard>
  )
}

const ACCENT_SWATCH: Record<Accent, string> = {
  blue: 'oklch(0.62 0.2 256)',
  clay: 'oklch(0.73 0.17 58)',
  violet: 'oklch(0.6 0.25 312)',
  green: 'oklch(0.67 0.18 142)',
  amber: 'oklch(0.83 0.17 95)',
  rose: 'oklch(0.64 0.22 30)',
}

/** Pick a font: each choice is written in its own font; interface fonts are grouped by style. */
function FontButton({ label, stack, active, onClick }: { label: string; stack: string; active: boolean; onClick: () => void }) {
  React.useEffect(() => loadFontPreview(stack), [stack]) // the preview needs the font's @font-face rules
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onClick}
      style={{ fontFamily: stack }}
      className={cn(
        'h-8 rounded-md border px-3 text-[13px] outline-none transition focus-visible:ring-2 focus-visible:ring-ring max-md:h-10',
        active ? 'border-primary bg-primary/10 text-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground',
      )}
    >
      {label}
    </button>
  )
}

function SansFontPicker({ value, onChange, label }: { value: keyof typeof SANS_FONTS; onChange: (k: keyof typeof SANS_FONTS) => void; label: string }) {
  const t = useT()
  const keys = Object.keys(SANS_FONTS) as (keyof typeof SANS_FONTS)[]
  return (
    <div role="radiogroup" aria-label={label} className="grid w-full gap-2.5">
      {FONT_GROUPS.map((g: FontGroup) => (
        <div key={g} className="flex flex-wrap items-center gap-1.5">
          <span className="w-28 shrink-0 text-xs text-muted-foreground max-md:w-full">{t(`fonts.group.${g}` as TKey)}</span>
          {keys.filter((k) => SANS_FONTS[k].group === g).map((k) => (
            <FontButton key={k} label={SANS_FONTS[k].label} stack={SANS_FONTS[k].stack} active={value === k} onClick={() => onChange(k)} />
          ))}
        </div>
      ))}
    </div>
  )
}

function MonoFontPicker({ value, onChange, label }: { value: keyof typeof MONO_FONTS; onChange: (k: keyof typeof MONO_FONTS) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="flex w-full flex-wrap gap-1.5">
      {(Object.keys(MONO_FONTS) as (keyof typeof MONO_FONTS)[]).map((k) => (
        <FontButton key={k} label={`{ } ${MONO_FONTS[k].label}`} stack={MONO_FONTS[k].stack} active={value === k} onClick={() => onChange(k)} />
      ))}
    </div>
  )
}

export function AccentPicker() {
  const t = useT()
  const accent = useUI((s) => s.accent)
  const setAccent = useUI((s) => s.setAccent)
  return (
    <div role="radiogroup" aria-label={t('settings.accent')} data-tour="accent" className="flex flex-wrap gap-2">
      {ACCENTS.map((a) => (
        <Tooltip key={a} content={t(`accent.${a}` as TKey)}>
          <button
            type="button"
            role="radio"
            aria-checked={accent === a}
            aria-label={t(`accent.${a}` as TKey)}
            onClick={() => setAccent(a)}
            className={cn(
              'flex size-8 items-center justify-center rounded-full ring-offset-2 ring-offset-background outline-none transition focus-visible:ring-2 focus-visible:ring-ring max-md:size-10',
              accent === a && 'ring-2 ring-foreground/70',
            )}
            style={{ background: ACCENT_SWATCH[a] }}
          >
            {accent === a && <Check className="size-4 text-white drop-shadow" strokeWidth={3} />}
          </button>
        </Tooltip>
      ))}
    </div>
  )
}

function ResultLinePicker() {
  const t = useT()
  const { hidden, toggle } = useResultLine()
  return (
    <div className="flex flex-wrap gap-x-5 gap-y-2" data-testid="result-line-picker">
      {RESULT_FIELDS.map((f) => (
        <label key={f.id} className="flex cursor-pointer items-center gap-2 text-sm">
          <Checkbox checked={!hidden.includes(f.id)} onCheckedChange={(c) => toggle(f.id, !!c)} />
          {t(f.label)}
        </label>
      ))}
    </div>
  )
}

export function GeneralSection() {
  const t = useT()
  const { data: s } = useSettings()
  const save = useSaveSettings()
  const ui = useUI()
  const [server, setServer] = React.useState<{ public_url: string; files_root: string } | null>(null)
  React.useEffect(() => {
    if (s && !server) setServer({ public_url: s.public_url || '', files_root: s.files_root || '' })
  }, [s, server])

  return (
    <SectionStack>
      <SettingsCard title={t('settings.appearance')} description={t('settings.appearanceDesc')}>
        <div className="divide-y">
          <SettingRow label={t('shell.theme')}>
            <Segmented<Theme>
              value={ui.theme}
              onChange={ui.setTheme}
              aria-label={t('shell.theme')}
              options={[
                { value: 'dark', label: t('theme.dark'), icon: <Moon /> },
                { value: 'light', label: t('theme.light'), icon: <Sun /> },
                { value: 'system', label: t('theme.system'), icon: <Monitor /> },
              ]}
            />
          </SettingRow>
          <SettingRow label={t('settings.accent')} description={t('settings.accentDesc')}>
            <AccentPicker />
          </SettingRow>
          <SettingRow label={t('settings.density')} description={t('settings.densityDesc')}>
            <Segmented<Density>
              value={ui.density}
              onChange={ui.setDensity}
              aria-label={t('settings.density')}
              options={[
                { value: 'comfortable', label: t('density.comfortable') },
                { value: 'compact', label: t('density.compact') },
              ]}
            />
          </SettingRow>
          <SettingRow label={t('settings.layout')} description={t('settings.layoutDesc')}>
            <Segmented<Layout>
              value={ui.layout}
              onChange={ui.setLayout}
              aria-label={t('settings.layout')}
              options={[
                { value: 'auto', label: t('layout.auto') },
                { value: 'touch', label: t('layout.touch') },
                { value: 'desktop', label: t('layout.desktop') },
              ]}
            />
          </SettingRow>
          <SettingRow label={t('settings.touchHome')} description={t('settings.touchHomeDesc')}>
            <Segmented<TouchHome>
              value={ui.touchHome}
              onChange={ui.setTouchHome}
              aria-label={t('settings.touchHome')}
              options={[
                { value: 'session', label: t('touchHome.session') },
                { value: 'dashboard', label: t('touchHome.dashboard') },
              ]}
            />
          </SettingRow>
          <div className="grid gap-3 py-4">
            <div className="grid gap-0.5">
              <span className="text-sm font-medium">{t('settings.resultLine')}</span>
              <p className="text-[13px] text-muted-foreground">{t('settings.resultLineDesc')}</p>
            </div>
            <ResultLinePicker />
          </div>
          <SettingRow label={t('settings.tint')} description={t('settings.tintDesc')}>
            <Segmented<Tint>
              value={ui.tint}
              onChange={ui.setTint}
              aria-label={t('settings.tint')}
              options={[
                { value: 'neutral', label: t('tint.neutral') },
                { value: 'tinted', label: t('tint.tinted') },
              ]}
            />
          </SettingRow>
          <div className="grid gap-3 py-4">
            <div className="grid gap-0.5">
              <span className="text-sm font-medium">{t('settings.font')}</span>
              <p className="text-[13px] text-muted-foreground">{t('settings.fontDesc')}</p>
            </div>
            <SansFontPicker value={ui.font} onChange={ui.setFont} label={t('settings.font')} />
          </div>
          <div className="grid gap-3 py-4 last:pb-0">
            <div className="grid gap-0.5">
              <span className="text-sm font-medium">{t('settings.monoFont')}</span>
              <p className="text-[13px] text-muted-foreground">{t('settings.monoFontDesc')}</p>
            </div>
            <MonoFontPicker value={ui.monoFont} onChange={ui.setMonoFont} label={t('settings.monoFont')} />
          </div>
        </div>
      </SettingsCard>


      <SettingsCard title={t('settings.region')} description={t('settings.regionDesc')}>
        {!s ? (
          <Skeleton className="h-36" />
        ) : (
          <div className="max-w-lg">
            <RegionFields
              language={s.language}
              timezone={s.timezone}
              onLanguage={(l: Language) => {
                ui.setLanguage(l)
                save.mutate({ language: l })
              }}
              onTimezone={(tz) => save.mutate({ timezone: tz }, { onSuccess: () => toast.success(t('common.saved')) })}
            />
          </div>
        )}
      </SettingsCard>

      <SettingsCard title={t('settings.server')} description={t('settings.serverDesc')}>
        {!s || !server ? (
          <Skeleton className="h-44" />
        ) : (
          <form
            className="grid max-w-lg gap-5"
            onSubmit={(e) => {
              e.preventDefault()
              save.mutate({ public_url: server.public_url.trim(), files_root: server.files_root.trim() }, { onSuccess: () => toast.success(t('common.saved')) })
            }}
          >
            <FormField label={t('settings.publicUrl')} hint={t('settings.publicUrlHint')}>
              <Input value={server.public_url} onChange={(e) => setServer({ ...server, public_url: e.target.value })} placeholder="https://ui.example.com" inputMode="url" />
            </FormField>
            <FormField label={t('settings.filesRoot')} hint={t('settings.filesRootHint')}>
              <Input value={server.files_root} onChange={(e) => setServer({ ...server, files_root: e.target.value })} className="font-mono" spellCheck={false} />
            </FormField>
            <div>
              <Button type="submit" loading={save.isPending} disabled={server.public_url === s.public_url && server.files_root === s.files_root}>
                {t('common.save')}
              </Button>
            </div>
          </form>
        )}
      </SettingsCard>

      <AppCard />
      <HelpCard />

    </SectionStack>
  )
}
