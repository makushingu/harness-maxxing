// Settings -> Appearance (2.0.0a132, was the first card of General): how the interface looks in this browser, in
// three cards - colors, layout, fonts. Everything here is saved in this browser (the last choice also colors the sign-in page).
import * as React from 'react'
import { Check, Monitor, Moon, Sun } from 'lucide-react'
import { ACCENTS, useUI, type Accent, type Density, type Layout, type Theme, type Tint, type Material, type TouchHome } from '@/stores/ui'
import { cn } from '@/lib/utils'
import { FONT_GROUPS, loadFontPreview, MONO_FONTS, SANS_FONTS, type FontGroup } from '@/lib/fonts'
import { useT, type TKey } from '@/i18n'
import { Segmented, Tooltip } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { SettingsCard, SectionStack } from './ui'

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

export function AppearanceSection() {
  const t = useT()
  const ui = useUI()
  return (
    <SectionStack>
      <SettingsCard title={t('appearance.colors')} description={t('appearance.colorsDesc')}>
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
          <SettingRow label={t('settings.material')} description={t('settings.materialDesc')}>
            <Segmented<Material>
              value={ui.material}
              onChange={ui.setMaterial}
              aria-label={t('settings.material')}
              options={[
                { value: 'solid', label: t('material.solid') },
                { value: 'glass', label: t('material.glass') },
              ]}
            />
          </SettingRow>
        </div>
      </SettingsCard>

      <SettingsCard title={t('appearance.layout')} description={t('appearance.layoutDesc')}>
        <div className="divide-y">
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
        </div>
      </SettingsCard>

      <SettingsCard title={t('appearance.fonts')}>
        <div className="divide-y">
          <div className="grid gap-3 pb-4">
            <div className="grid gap-0.5">
              <span className="text-sm font-medium">{t('settings.font')}</span>
              <p className="text-[13px] text-muted-foreground">{t('settings.fontDesc')}</p>
            </div>
            <SansFontPicker value={ui.font} onChange={ui.setFont} label={t('settings.font')} />
          </div>
          <div className="grid gap-3 pt-4">
            <div className="grid gap-0.5">
              <span className="text-sm font-medium">{t('settings.monoFont')}</span>
              <p className="text-[13px] text-muted-foreground">{t('settings.monoFontDesc')}</p>
            </div>
            <MonoFontPicker value={ui.monoFont} onChange={ui.setMonoFont} label={t('settings.monoFont')} />
          </div>
        </div>
      </SettingsCard>
    </SectionStack>
  )
}
