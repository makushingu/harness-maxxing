// Settings -> Appearance (2.0.0a132, was the first card of General): how the interface looks in this browser, in
// three cards - the theme (Solid, the default, or Glass), the options of that theme (mode, accent, background, fonts),
// the layout of this device. Everything here is saved in this browser (the last choice also colors the sign-in page).
import * as React from 'react'
import { Check, Monitor, Moon, Sun } from 'lucide-react'
import { useNavigate } from 'react-router'
import { label, useInstalledThemes } from '@/lib/themes'
import { draftUrl } from '@/features/agents/EditWithClaude'
import { useHarnessTopic } from './harnessTopic'
import { ACCENTS, shownMode, useUI, type Accent, type Density, type Layout, type Theme, type Tint, type Material, type TouchHome } from '@/stores/ui'
import { cn } from '@/lib/utils'
import { FONT_GROUPS, loadFontPreview, MONO_FONTS, SANS_FONTS, type FontGroup } from '@/lib/fonts'
import { useT, type TKey } from '@/i18n'
import { Button, Segmented, Switch, Tooltip } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { SettingsCard, SectionStack } from './ui'

export const ACCENT_SWATCH: Record<Accent, string> = {
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

function AccentPicker() {
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

/** The look of a theme card: a tiny window drawn with the theme's own colors (sidebar, card, a button in the accent),
 *  the same drawing for every theme. `vars` = an installed theme's values for this mode (what it leaves out keeps the
 *  built-in look). No picture: a theme's preview.png is for its Community listing, its wallpaper (often 1 MB) would be
 *  downloaded for an 80 px tile, so a glass theme shows its two wallpaper colors instead. */
export function ThemePreview({ glass, accent, dark, vars }: { glass: boolean; accent: string; dark: boolean; vars?: Record<string, string> }) {
  const v = vars ?? {}
  const base = v.background || (dark ? 'oklch(0.2 0.006 286)' : 'oklch(0.98 0 0)')
  const side = v.sidebar || base
  const panel = v.card || (dark ? 'oklch(0.27 0.006 286)' : 'oklch(1 0 0)')
  const line = v.border || (dark ? 'oklch(1 0 0 / 0.1)' : 'oklch(0 0 0 / 0.08)')
  const fg = v.foreground || (dark ? 'oklch(1 0 0)' : 'oklch(0 0 0)')
  const btn = v.primary || accent
  const radius = v.radius ? `min(${v.radius}, 0.5rem)` : undefined
  const soft = `color-mix(in oklch, ${btn} ${dark ? 45 : 35}%, transparent)`
  const wall = glass
    ? `radial-gradient(120% 90% at 15% 10%, ${v['wall-a'] || soft} 0%, transparent 60%), radial-gradient(90% 80% at 95% 100%, ${v['wall-b'] || soft} 0%, transparent 55%), ${side}`
    : side
  const pane = (c: string) => (glass ? `color-mix(in oklch, ${c} 55%, transparent)` : c)
  const blur = glass ? 'blur(6px)' : undefined
  return (
    <div aria-hidden className="relative h-20 overflow-hidden rounded-md border" style={{ background: wall, borderColor: line }}>
      <div className="absolute inset-y-0 left-0 w-1/4 border-r" style={{ background: glass ? 'transparent' : side, borderColor: line }} />
      <div className="absolute inset-y-1.5 right-1.5 left-1/4 rounded" style={{ background: pane(base), backdropFilter: blur }} />
      <div className="absolute top-3 right-3 left-[calc(25%+0.75rem)] grid gap-1.5 rounded border p-2" style={{ background: pane(panel), borderColor: line, backdropFilter: blur, borderRadius: radius }}>
        <div className="h-1.5 w-3/4 rounded-full" style={{ background: `color-mix(in oklch, ${fg} 45%, transparent)` }} />
        <div className="h-1.5 w-1/2 rounded-full" style={{ background: `color-mix(in oklch, ${fg} 22%, transparent)` }} />
        <div className="mt-0.5 h-3 w-10 rounded-sm" style={{ background: btn }} />
      </div>
    </div>
  )
}

function ThemeTile({ active, onClick, preview, name, note, desc }: { active: boolean; onClick: () => void; preview: React.ReactNode; name: string; note?: string; desc: string }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onClick}
      className={cn(
        'grid content-start gap-2 rounded-lg border p-2 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-ring',
        active ? 'border-primary ring-1 ring-primary' : 'hover:bg-accent',
      )}
    >
      {preview}
      <div className="flex items-start gap-2 px-1 pb-0.5">
        <div className="grid min-w-0 flex-1 gap-0.5">
          <span className="truncate text-sm font-medium">
            {name}
            {note && <span className="ml-1.5 text-xs font-normal text-muted-foreground">{note}</span>}
          </span>
          <span className="line-clamp-2 text-xs text-muted-foreground">{desc}</span>
        </div>
        {active && <Check className="mt-0.5 size-4 shrink-0 text-primary" strokeWidth={3} />}
      </div>
    </button>
  )
}

/** The built-in themes: Solid (the default) and Glass. Installed themes sit next to them. */
const BUILT_IN: { id: Material; name: TKey; desc: TKey }[] = [
  { id: 'solid', name: 'material.solid', desc: 'appearance.solidDesc' },
  { id: 'glass', name: 'material.glass', desc: 'appearance.glassDesc' },
]

function ThemePicker() {
  const t = useT()
  const lang = useUI((s) => s.language)
  const material = useUI((s) => s.material)
  const custom = useUI((s) => s.customTheme?.id ?? null)
  const setMaterial = useUI((s) => s.setMaterial)
  const pickTheme = useUI((s) => s.pickTheme)
  const accent = ACCENT_SWATCH[useUI((s) => s.accent)]
  const dark = shownMode(useUI((s) => s.theme), useUI((s) => s.customTheme)) === 'dark'
  const { data } = useInstalledThemes()
  const ask = useAskHarness()
  return (
    <div className="grid gap-3">
      <div role="radiogroup" aria-label={t('appearance.theme')} data-tour="themes" className="grid grid-cols-2 gap-3 max-sm:grid-cols-1 lg:grid-cols-3">
        {BUILT_IN.map((th) => (
          <ThemeTile
            key={th.id}
            active={!custom && material === th.id}
            onClick={() => setMaterial(th.id)}
            preview={<ThemePreview glass={th.id === 'glass'} accent={accent} dark={dark} />}
            name={t(th.name)}
            note={th.id === 'solid' ? t('appearance.default') : undefined}
            desc={t(th.desc)}
          />
        ))}
        {(data?.themes ?? []).map((th) => {
          const mode = th.modes.length === 1 ? th.modes[0] === 'dark' : dark
          const by = [th.author && t('appearance.by', { name: th.author }), t(th.base === 'glass' ? 'appearance.onGlass' : 'appearance.onSolid')].filter(Boolean).join(' · ')
          return (
            <ThemeTile
              key={th.id}
              active={custom === th.id}
              onClick={() => pickTheme(th)}
              preview={<ThemePreview glass={th.base === 'glass'} accent={accent} dark={mode} vars={mode ? th.dark : th.light} />}
              name={label(th.name, lang)}
              note={by}
              desc={label(th.description, lang) || t('appearance.installedDesc')}
            />
          )
        })}
      </div>
      {!!data?.errors.length && (
        <p className="text-xs text-muted-foreground">
          {t('appearance.unusable')} {data.errors.map((e) => `${e.id} (${e.error})`).join(' · ')}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>{t('appearance.moreThemes')}</span>
        <button type="button" onClick={() => ask(t('appearance.askPrompt'))} className="font-medium text-primary underline-offset-4 outline-none hover:underline focus-visible:underline pointer-coarse:py-1">
          {t('appearance.ask')}
        </button>
      </div>
    </div>
  )
}

/** Opens a new session draft in the Harness topic with `prompt` written (the user reads it and sends). */
export function useAskHarness() {
  const navigate = useNavigate()
  const topic = useHarnessTopic()
  return (prompt: string) => navigate(draftUrl(topic, prompt))
}

export function AppearanceSection() {
  const t = useT()
  const ui = useUI()
  const ct = ui.customTheme
  const { data } = useInstalledThemes(!!ct)
  const installed = ct ? data?.themes.find((x) => x.id === ct.id) : undefined
  const ask = useAskHarness()
  const themeName = ct ? (installed ? label(installed.name, ui.language) : ct.id) : t(ui.material === 'glass' ? 'material.glass' : 'material.solid')
  return (
    <SectionStack>
      <SettingsCard title={t('appearance.theme')} description={t('appearance.themeDesc')}>
        <ThemePicker />
      </SettingsCard>

      <SettingsCard title={t('appearance.options', { name: themeName })} description={t('appearance.optionsDesc')}>
        <div className="divide-y">
          {ct?.mode ? (
            <SettingRow label={t('shell.theme')} description={t('appearance.fixedMode')}>
              <span className="text-sm text-muted-foreground">{t(ct.mode === 'dark' ? 'theme.dark' : 'theme.light')}</span>
            </SettingRow>
          ) : (
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
          )}
          {ct?.ownAccent ? (
            <SettingRow label={t('settings.accent')} description={t('appearance.ownAccent')}>{null}</SettingRow>
          ) : (
            <SettingRow label={t('settings.accent')} description={t('settings.accentDesc')}>
              <AccentPicker />
            </SettingRow>
          )}
          {!ct?.ownSurfaces && (
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
          )}
          {ct && ct.cssState !== 'none' && (
            <SettingRow label={t('appearance.css')} description={t(ct.cssState === 'stale' ? 'appearance.cssStale' : 'appearance.cssDesc')}>
              {ct.cssState === 'stale' ? (
                <Button size="sm" variant="outline" onClick={() => ask(t('appearance.cssVerifyPrompt', { id: ct.id }))}>{t('appearance.cssVerify')}</Button>
              ) : (
                <Switch checked={!ui.themeCssOff} onCheckedChange={(on) => ui.setThemeCssOff(!on)} aria-label={t('appearance.css')} />
              )}
            </SettingRow>
          )}
          <div className="grid gap-3 py-4">
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
    </SectionStack>
  )
}
