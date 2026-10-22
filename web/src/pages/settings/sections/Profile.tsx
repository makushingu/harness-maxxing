import * as React from 'react'
import { Check } from 'lucide-react'
import { useProfile, useRegister, useSaveProfile, useSaveRegister } from '@/lib/queries'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'
import type { Profile, ProfileColor } from '@/lib/types'
import { Button, Input, Skeleton, Tooltip } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { Avatar, PROFILE_COLORS } from '@/features/profile/Avatar'
import { RegisterFields, validEmail, type RegisterValues } from '@/features/profile/Register'
import { projectColor } from '@/features/tasks/model'
import { SettingsCard, SectionStack } from './ui'

export function ProfileSection() {
  const t = useT()
  const { data: p } = useProfile()
  const save = useSaveProfile()
  const [name, setName] = React.useState('')
  const [emoji, setEmoji] = React.useState('')
  React.useEffect(() => {
    if (p) {
      setName(p.name)
      setEmoji(p.emoji)
    }
  }, [p])
  if (!p) return <Skeleton className="h-72 rounded-xl" />
  const put = (patch: Partial<Profile>) => save.mutate({ ...p, ...patch })
  const commitName = () => name.trim() !== p.name && put({ name: name.trim() })
  const commitEmoji = () => emoji.trim() !== p.emoji && put({ emoji: emoji.trim() })
  const preview: Profile = { ...p, name: name.trim(), emoji: emoji.trim() }
  return (
    <SectionStack>
      <SettingsCard title={t('profile.title')} description={t('profile.desc')}>
        <div className="divide-y">
          <SettingRow label={t('profile.name')} description={t('profile.nameDesc')} htmlFor="profile-name">
            <Input
              id="profile-name"
              value={name}
              maxLength={32}
              placeholder={t('profile.namePlaceholder')}
              onChange={(e) => setName(e.target.value)}
              onBlur={commitName}
              onKeyDown={(e) => e.key === 'Enter' && (e.currentTarget.blur(), undefined)}
              className="w-56"
            />
          </SettingRow>
          <SettingRow label={t('profile.color')} description={t('profile.colorDesc')}>
            <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={t('profile.color')}>
              {PROFILE_COLORS.map((c) => {
                const on = (p.color || 'zinc') === c
                return (
                  <button
                    key={c}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    aria-label={c}
                    onClick={() => put({ color: c as ProfileColor })}
                    className={cn(
                      'inline-flex size-7 items-center justify-center rounded-full text-white ring-offset-2 ring-offset-background transition-transform duration-150 hover:scale-110 active:scale-95',
                      on && 'ring-2 ring-foreground/60',
                    )}
                    style={{ background: projectColor(c) }}
                  >
                    {on && <Check className="mx-pop size-3.5" />}
                  </button>
                )
              })}
            </div>
          </SettingRow>
          <SettingRow label={t('profile.emoji')} description={t('profile.emojiDesc')} htmlFor="profile-emoji">
            <Input
              id="profile-emoji"
              value={emoji}
              maxLength={8}
              placeholder="🔥"
              onChange={(e) => setEmoji(e.target.value.replace(/\s/g, ''))}
              onBlur={commitEmoji}
              onKeyDown={(e) => e.key === 'Enter' && (e.currentTarget.blur(), undefined)}
              className="w-24 text-center"
            />
          </SettingRow>
        </div>
      </SettingsCard>
      <SettingsCard title={t('profile.preview')}>
        <div className="flex items-end justify-end gap-2">
          <div className="grid justify-items-end gap-1">
            <div className="rounded-2xl rounded-br-md bg-secondary px-3.5 py-2 text-[14px] text-secondary-foreground">{t('profile.previewText')}</div>
            <span className="text-[11px] text-muted-foreground">{preview.name || t('profile.you')}</span>
          </div>
          <Tooltip content={preview.name || t('profile.you')}>
            <span>
              <Avatar profile={preview} />
            </span>
          </Tooltip>
        </div>
      </SettingsCard>
      <RegisterCard />
    </SectionStack>
  )
}

function RegisterCard() {
  const t = useT()
  const { data: reg } = useRegister()
  const save = useSaveRegister()
  const [v, setV] = React.useState<RegisterValues | null>(null)
  React.useEffect(() => {
    if (reg) setV({ email: reg.email, news: reg.news, count: reg.count })
  }, [reg])
  if (!reg || !v) return <Skeleton className="h-48 rounded-xl" />
  const put = (n: RegisterValues) => validEmail(n.email) && save.mutate({ ...n, email: n.email.trim(), asked: true })
  const change = (n: RegisterValues) => {
    setV(n)
    if (n.news !== v.news || n.count !== v.count) put(n)        // checkboxes save at once, the email on blur
  }
  const on = (reg.count && !reg.count_blocked) || !!reg.email
  return (
    <SettingsCard title={t('register.title')} description={t('register.desc')}>
      <RegisterFields v={v} onChange={change} onEmailBlur={() => v.email.trim() !== reg.email && put(v)} counterBlocked={reg.count_blocked} />
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t pt-4 text-xs text-muted-foreground">
        <span>
          {!on ? t('register.statusOff') : reg.registered ? t('register.statusOn') : reg.error ? t('register.statusError', { error: reg.error }) : t('register.statusPending')}
        </span>
        {on && (
          <Button variant="outline" size="sm" disabled={save.isPending} onClick={() => save.mutate({ count: false, email: '', news: false, asked: true })}>
            {t('register.stop')}
          </Button>
        )}
      </div>
      <p className="mt-3 text-xs text-muted-foreground">{t('register.privacy')}</p>
    </SettingsCard>
  )
}
