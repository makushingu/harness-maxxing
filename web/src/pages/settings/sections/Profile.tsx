import * as React from 'react'
import { Check, ImagePlus } from 'lucide-react'
import { useProfile, useRegister, useRemoveProfilePhoto, useSaveProfile, useSaveProfilePhoto, useSaveRegister } from '@/lib/queries'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'
import type { Profile, ProfileColor } from '@/lib/types'
import { Button, Input, Skeleton, Tooltip } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { Avatar, PROFILE_COLORS } from '@/features/profile/Avatar'
import { EmojiPicker } from '@/features/profile/EmojiPicker'
import { RegisterFields, validEmail, type RegisterValues } from '@/features/profile/Register'
import { projectColor } from '@/features/tasks/model'
import { SettingsCard, SectionStack } from './ui'

const PHOTO_PX = 256

/** The chosen image as a 256 px square (centered crop), WebP where the browser can write it, else JPEG. */
async function squarePhoto(file: File): Promise<Blob> {
  const img = await createImageBitmap(file)
  const side = Math.min(img.width, img.height)
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = PHOTO_PX
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('canvas')
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, PHOTO_PX, PHOTO_PX)
  img.close()
  const blob = (type: string) => new Promise<Blob | null>((ok) => canvas.toBlob(ok, type, 0.86))
  const webp = await blob('image/webp')
  const out = webp?.type === 'image/webp' ? webp : await blob('image/jpeg')
  if (!out) throw new Error('encode')
  return out
}

export function ProfileSection() {
  const t = useT()
  const { data: p } = useProfile()
  const save = useSaveProfile()
  const savePhoto = useSaveProfilePhoto()
  const removePhoto = useRemoveProfilePhoto()
  const fileRef = React.useRef<HTMLInputElement>(null)
  const [photoError, setPhotoError] = React.useState(false)
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
  const pickEmoji = (e: string) => {
    setEmoji(e)
    if (e !== p.emoji) put({ emoji: e })
  }
  const onFile = async (file: File | undefined) => {
    if (!file) return
    setPhotoError(false)
    try {
      savePhoto.mutate(await squarePhoto(file))
    } catch {
      setPhotoError(true)              // not an image the browser can read (HEIC on a desktop, a broken file...)
    }
  }
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
          <SettingRow label={t('profile.photo')} description={photoError ? t('profile.photoError') : t('profile.photoDesc')}>
            <div className="flex items-center gap-2">
              <Avatar profile={p} size="lg" />
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif,image/avif,image/heic"
                className="hidden"
                onChange={(e) => {
                  void onFile(e.target.files?.[0])
                  e.target.value = ''
                }}
              />
              <Button variant="outline" size="sm" loading={savePhoto.isPending} onClick={() => fileRef.current?.click()}>
                <ImagePlus /> {p.photo ? t('profile.photoChange') : t('profile.photoAdd')}
              </Button>
              {p.photo && (
                <Button variant="ghost" size="sm" loading={removePhoto.isPending} onClick={() => removePhoto.mutate()}>
                  {t('profile.photoRemove')}
                </Button>
              )}
            </div>
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
                      'inline-flex size-7 pointer-coarse:size-10 items-center justify-center rounded-full text-white ring-offset-2 ring-offset-background transition-transform duration-150 hover:scale-110 active:scale-95',
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
          <SettingRow label={t('profile.emoji')} description={t('profile.emojiDesc')}>
            <EmojiPicker value={emoji} onChange={pickEmoji} />
          </SettingRow>
          <div className="grid gap-2 pt-4">
            <span className="text-[13px] text-muted-foreground">{t('profile.preview')}</span>
            <div className="flex items-end justify-end gap-2 rounded-lg bg-muted/40 p-3">
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
          </div>
        </div>
      </SettingsCard>

      <RegisterCard />
    </SectionStack>
  )
}

/** Stay in touch (back here in 2.0.0a132): an optional e-mail for the news, and the anonymous counter. */
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
    <SettingsCard title={t('about.contact')} description={t('register.desc')}>
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
