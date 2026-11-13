// A topic's sessions or an agent and the Harness Browser: one switch (may its turns use it), the tabs it sees (its
// topic's and its project's), "Open the browser" (BrowserWindow, its tabs first). The browser's own settings (sites,
// sign-ins, sleep) are in Settings -> Features: one browser for the server.
import * as React from 'react'
import { Link } from 'react-router'
import { Globe, Moon } from 'lucide-react'
import { useT } from '@/i18n'
import { useBrowserOwner, useBrowserSwitch, useBrowserTab } from '@/lib/queries'
import { Button, Skeleton, Switch } from '@/components/ui'
import { Callout, SettingRow } from '@/features/common'
import { BrowserWindow } from './BrowserWindow'
import { ScopeIcon, scopeKind, scopeName, scopeTopic } from './scope'

export function BrowserPanel({ path, live = true, who }: { path: string; live?: boolean; who?: string }) {
  const t = useT()
  const { data: o, isLoading } = useBrowserOwner(path)
  const save = useBrowserSwitch()
  const tabOp = useBrowserTab()
  const [win, setWin] = React.useState(false)
  if (isLoading || !o) return <Skeleton className="h-24" />

  return (
    <div className="grid min-w-0 gap-4" data-testid="browser-panel">
      {!o.feature && (
        <Callout tone="info">
          {t('browser.featureOff')}{' '}
          <Link to="/settings/features" className="text-primary underline">
            {t('browser.openFeatures')}
          </Link>
        </Callout>
      )}
      <div className="divide-y">
        <SettingRow label={t('browser.enable')} description={t('browser.enableDesc')} htmlFor="br-enabled">
          <Switch id="br-enabled" checked={o.settings.enabled} onCheckedChange={(v) => save.mutate({ path, enabled: v })} data-testid="browser-enabled" />
        </SettingRow>
      </div>

      {o.settings.enabled && live && (
        <div className="grid gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => setWin(true)} data-testid="browser-open-window">
              {t('browser.open')}
            </Button>
            <Link to="/settings/features" className="text-[12px] text-muted-foreground underline-offset-2 hover:underline">
              {t('browser.settingsLink')}
            </Link>
          </div>
          <p className="text-[12px] text-muted-foreground">{scopeKind(o.scope) === 'agent' ? t('browser.panelHintAgent') : t('browser.panelHint', { name: scopeName(o.scope) })}</p>
          {o.tabs.length > 0 && (
            <div className="grid gap-1" data-testid="browser-owner-tabs">
              {o.tabs.map((tab) => {
                const Icon = ScopeIcon(tab.scope)
                return (
                  <button
                    key={tab.key}
                    type="button"
                    onClick={() => (tabOp.mutate({ op: 'show', key: tab.key }), setWin(true))}
                    className="flex min-w-0 items-center gap-2 rounded-md border bg-card/60 px-2.5 py-1.5 text-left text-[13px] hover:bg-accent"
                  >
                    {tab.asleep ? <Moon className="size-3.5 shrink-0 text-muted-foreground" /> : <Globe className="size-3.5 shrink-0 text-primary" />}
                    <span className="min-w-0 flex-1 truncate">{tab.title || tab.url || t('browser.newTab')}</span>
                    <span className="inline-flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground">
                      <Icon className="size-3" /> {t(`browser.scope.${scopeKind(tab.scope)}`, { name: scopeName(tab.scope), topic: scopeTopic(tab.scope) })}
                    </span>
                  </button>
                )
              })}
            </div>
          )}
          <BrowserWindow context={path} who={who} open={win} onOpenChange={setWin} start />
        </div>
      )}
    </div>
  )
}
