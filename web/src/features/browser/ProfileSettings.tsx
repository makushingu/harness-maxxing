// The settings of a profile (bottom of its page, ProfilePage): what happens when its connection goes down (it opens any
// public site: only a sandboxed agent is held to its domains, on the agent's page), its memory, forget its sign-ins, delete it (not a project's while its project exists). Its name and its
// connection are at the top of the page.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Eraser, Moon, Trash2 } from 'lucide-react'
import { useT } from '@/i18n'
import { useBrowserProfile, useProfileAction, useSaveBrowserProfile } from '@/lib/queries'
import type { BrowserProfile } from '@/lib/types'
import { fmtBytes } from '@/lib/format'
import { Button, confirm, Label, Select, Skeleton } from '@/components/ui'
import { profileName } from './profiles'

export function ProfileSettings({ pid }: { pid: string }) {
  const t = useT()
  const nav = useNavigate()
  const { data: v } = useBrowserProfile(pid)
  const save = useSaveBrowserProfile()
  const action = useProfileAction()
  const [err, setErr] = React.useState<string | null>(null)
  if (!v) return <Skeleton className="h-64" />
  const p = v.profile
  const set = (patch: Partial<BrowserProfile>, done?: () => void) =>
    save.mutate({ id: p.id, ...patch }, { onSuccess: () => (setErr(null), done?.()), onError: (e) => setErr(e instanceof Error ? e.message : String(e)) })
  const b = v.browser
  const deletable = p.id !== 'main' && (!p.project || v.gone)
  const forget = async () => {
    if (!(await confirm({ title: t('browser.forgetTitle'), description: t('browser.forgetConfirm'), destructive: true }))) return
    action.mutate({ profile: p.id, action: 'forget' })
  }
  const remove = async () => {
    if (!(await confirm({ title: t('browser.profile.deleteTitle', { name: profileName(p, t) }), description: t('browser.profile.deleteDesc'), destructive: true }))) return
    save.mutate({ id: p.id, remove: true }, { onSuccess: () => nav('/settings/browser') })
  }
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]" data-testid="browser-profile-settings">
      <div className="grid content-start gap-5">
        <div className="grid gap-1.5">
          <Label htmlFor="pr-down">{t('browser.profile.down')}</Label>
          <Select
            id="pr-down"
            value={p.on_exit_down}
            disabled={p.exit === 'direct'}
            onValueChange={(x) => set({ on_exit_down: x as 'wait' | 'vps' })}
            options={[
              { value: 'wait', label: t('browser.profile.downWait') },
              { value: 'vps', label: t('browser.profile.downVps') },
            ]}
          />
          <p className="text-[12px] text-muted-foreground">{t(p.on_exit_down === 'vps' ? 'browser.profile.downVpsHint' : 'browser.profile.downWaitHint')}</p>
          {err && <p className="text-[12px] text-destructive">{err}</p>}
        </div>
        <p className="text-[12px] text-muted-foreground" data-testid="browser-profile-web">{t('browser.profile.web')}</p>
      </div>

      <div className="grid content-start gap-5">
        <section className="grid gap-2">
          <h3 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('browser.profile.memory')}</h3>
          <div className="flex items-center gap-3 text-[13px]">
            <span className="min-w-0 flex-1">
              {b.state === 'running'
                ? t('browser.profile.on', { tabs: b.tabs.filter((x) => !x.asleep).length, mem: b.mem ? fmtBytes(b.mem) : '—' })
                : t('browser.profile.off', { tabs: b.tabs.length })}
            </span>
            {b.state === 'running' && (
              <Button size="sm" variant="outline" onClick={() => action.mutate({ profile: p.id, action: 'stop' })}>
                <Moon /> {t('browser.profile.sleep')}
              </Button>
            )}
          </div>
        </section>
        <section className="grid gap-2">
          <h3 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('browser.profile.danger')}</h3>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={forget} data-testid="browser-forget">
              <Eraser /> {t('browser.forget')}
            </Button>
            {deletable && (
              <Button size="sm" variant="outline" className="text-destructive" onClick={remove} data-testid="browser-profile-delete">
                <Trash2 /> {t('browser.profile.delete')}
              </Button>
            )}
          </div>
          <p className="text-[12px] text-muted-foreground">{t('browser.forgetDesc')}</p>
          {p.project && !v.gone && <p className="text-[12px] text-muted-foreground">{t('browser.profile.projectKeep')}</p>}
        </section>
      </div>
    </div>
  )
}
