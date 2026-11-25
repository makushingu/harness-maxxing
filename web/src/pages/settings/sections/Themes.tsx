// Settings -> Extensions -> Themes (2.0.0a169): the themes installed in <workspace>/themes (themes.py), as on
// Community. Picking one is in Appearance (with Solid and Glass); here: what is installed, its state (advanced CSS,
// warnings, folders that are not usable) and a draft to ask Harness for a new one. Installing and removing are done by
// Harness (skill maxxing-theme), never by a click.
import { AlertTriangle, Check, Paintbrush, Plus, RefreshCw } from 'lucide-react'
import { Link } from 'react-router'
import { label, useInstalledThemes } from '@/lib/themes'
import { shownMode, useUI } from '@/stores/ui'
import { useT } from '@/i18n'
import { Badge, Button, EmptyState, Skeleton } from '@/components/ui'
import { SettingsCard, SectionStack } from './ui'
import { CommunityLink } from './Extensions'
import { ACCENT_SWATCH, ThemePreview, useAskHarness } from './Appearance'

export function ThemesSection() {
  const t = useT()
  const ui = useUI()
  const { data, isLoading, refetch, isFetching } = useInstalledThemes()
  const ask = useAskHarness()
  const dark = shownMode(ui.theme, ui.customTheme) === 'dark'
  const accent = ACCENT_SWATCH[ui.accent]
  const themes = data?.themes ?? []
  return (
    <SectionStack>
      <SettingsCard
        title={t('themes.installedTitle')}
        description={t('themes.installedDesc')}
        actions={
          <>
            <Button variant="outline" size="sm" asChild>
              <Link to="/settings/appearance"><Paintbrush /> {t('themes.choose')}</Link>
            </Button>
            <Button variant="outline" size="sm" onClick={() => ask(t('appearance.askPrompt'))}>
              <Plus /> {t('themes.new')}
            </Button>
            <Button variant="outline" size="sm" loading={isFetching} onClick={() => refetch()}>
              <RefreshCw /> {t('ext.reload')}
            </Button>
          </>
        }
        className="[&>div:last-child]:p-0 [&>div:last-child]:pt-4"
      >
        {isLoading ? (
          <div className="grid gap-2 p-4">
            <Skeleton className="h-16" />
          </div>
        ) : !themes.length && !data?.errors.length ? (
          <EmptyState compact icon={Paintbrush} title={t('themes.empty')} description={t('themes.emptyDesc')} />
        ) : (
          <ul className="divide-y border-t">
            {themes.map((th) => {
              const mode = th.modes.length === 1 ? th.modes[0] === 'dark' : dark
              const inUse = ui.customTheme?.id === th.id
              return (
                <li key={th.id} className="flex items-start gap-3 px-4 py-3.5">
                  <div className="w-28 shrink-0 max-sm:w-20">
                    <ThemePreview glass={th.base === 'glass'} accent={accent} dark={mode} vars={mode ? th.dark : th.light} />
                  </div>
                  <div className="grid min-w-0 flex-1 gap-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{label(th.name, ui.language)}</span>
                      {inUse && (
                        <Badge variant="outline" className="gap-1"><Check className="size-3" /> {t('themes.inUse')}</Badge>
                      )}
                      <span className="font-mono text-xs text-muted-foreground">
                        {th.id}{th.version && ` · v${th.version}`}
                      </span>
                    </div>
                    <p className="text-[13px] text-muted-foreground">
                      {[th.author && t('appearance.by', { name: th.author }), t(th.base === 'glass' ? 'appearance.onGlass' : 'appearance.onSolid'), th.modes.length === 1 ? t(th.modes[0] === 'dark' ? 'theme.dark' : 'theme.light') : null].filter(Boolean).join(' · ')}
                      {label(th.description, ui.language) && ` · ${label(th.description, ui.language)}`}
                    </p>
                    {th.css_state !== 'none' && (
                      <p className="text-[13px] text-muted-foreground">
                        {t('appearance.css')}: {t(th.css_state === 'on' ? 'themes.cssOn' : 'themes.cssStale')}
                        {th.css_state === 'stale' && (
                          <button type="button" onClick={() => ask(t('appearance.cssVerifyPrompt', { id: th.id }))} className="ml-2 font-medium text-primary underline-offset-4 hover:underline pointer-coarse:py-1">
                            {t('appearance.cssVerify')}
                          </button>
                        )}
                      </p>
                    )}
                    {!!th.warnings.length && (
                      <p className="text-[13px] text-muted-foreground">{t('themes.warnings', { n: th.warnings.length })}</p>
                    )}
                  </div>
                </li>
              )
            })}
            {(data?.errors ?? []).map((e) => (
              <li key={e.id} className="flex items-start gap-3 px-4 py-3.5">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
                <div className="grid min-w-0 flex-1 gap-1">
                  <span className="font-mono text-sm">{e.id}</span>
                  <p className="text-[13px] break-words text-destructive">{t('themes.unusable')} {e.error}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </SettingsCard>
      <CommunityLink text={t('themes.community')} type="theme" />
    </SectionStack>
  )
}
