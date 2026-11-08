// The optional pages (Settings -> Features, and the "What will you use?" step of the first-run wizard): one row
// per page in its sidebar order, with its icon, one sentence, what it needs and its switch (saved on the server).
import { Link } from 'react-router'
import { useT, type TKey } from '@/i18n'
import { cn } from '@/lib/utils'
import { useSaveSettings, useSettings } from '@/lib/queries'
import { NAV, orderNav, type NavItem } from '@/components/shell/nav'
import { Skeleton, Switch } from '@/components/ui'

type PageSetting = NonNullable<NavItem['setting']>

/** What a page needs before it is useful (shown under its sentence), and where to set it. */
const NEEDS: Partial<Record<PageSetting, { text: TKey; to?: string; link?: TKey }>> = {
  team_page: { text: 'features.need.team' },
  mail_page: { text: 'features.need.mail' },
  infra_page: { text: 'features.need.infra', to: '/settings/keys', link: 'settings.keys' },
  git_page: { text: 'features.need.git', to: '/settings/keys', link: 'settings.keys' },
}

const DESC: Record<PageSetting, TKey> = {
  agents_page: 'features.page.agents',
  tasks_page: 'features.page.tasks',
  team_page: 'features.page.team',
  mail_page: 'features.page.mail',
  infra_page: 'features.page.infra',
  git_page: 'features.page.git',
}

/** A small "This browser" mark for the settings kept in this browser only. */
export function BrowserBadge() {
  const t = useT()
  return <span className="ml-2 inline-flex h-5 items-center rounded-full border px-2 align-[1px] text-[11px] font-normal text-muted-foreground">{t('features.thisBrowser')}</span>
}

export function FeaturePages({ compact }: { compact?: boolean }) {
  const t = useT()
  const { data: s } = useSettings()
  const save = useSaveSettings()
  if (!s) return <Skeleton className="h-72" />
  const pages = orderNav(NAV, s.sidebar_order).filter((n): n is NavItem & { setting: PageSetting } => !!n.setting)
  return (
    <ul className="divide-y">
      {pages.map((n) => {
        const on = !!s[n.setting]
        const need = NEEDS[n.setting]
        const id = `ft-${n.setting}`
        return (
          <li key={n.setting} className={cn('flex items-center gap-4 py-3.5 first:pt-0 last:pb-0', compact && 'py-3')}>
            <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-lg border transition-colors max-sm:hidden', on ? 'border-primary/30 bg-primary/10 text-primary' : 'text-muted-foreground')}>
              <n.icon className="size-[18px]" strokeWidth={1.8} />
            </span>
            <div className="grid min-w-0 flex-1 gap-0.5">
              <label htmlFor={id} className="text-sm font-medium">
                {t(n.label)}
              </label>
              <p className="text-[13px] text-muted-foreground">{t(DESC[n.setting])}</p>
              {need && (
                <p className="text-xs text-muted-foreground/80">
                  {t(need.text)}
                  {need.to && need.link && !compact && (
                    <>
                      {' '}
                      <Link to={need.to} className="text-primary hover:underline">
                        {t(need.link)}
                      </Link>
                    </>
                  )}
                </p>
              )}
            </div>
            <Switch id={id} checked={on} onCheckedChange={(v) => save.mutate({ [n.setting]: v })} />
          </li>
        )
      })}
    </ul>
  )
}
