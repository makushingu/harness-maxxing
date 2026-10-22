// Saying hello to the authors: all optional. Used by the onboarding step "Profile" and Settings -> Profile.
import { Checkbox, Input, Label } from '@/components/ui'
import { useT } from '@/i18n'

export type RegisterValues = { email: string; news: boolean; count: boolean }

export const validEmail = (e: string) => !e.trim() || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e.trim())

export function RegisterFields({ v, onChange, onEmailBlur }: { v: RegisterValues; onChange: (v: RegisterValues) => void; onEmailBlur?: () => void }) {
  const t = useT()
  const bad = !validEmail(v.email)
  return (
    <div className="grid gap-4">
      <div className="grid gap-1.5">
        <Label htmlFor="register-email">{t('register.email')}</Label>
        <Input
          id="register-email"
          type="email"
          inputMode="email"
          autoComplete="email"
          value={v.email}
          placeholder={t('register.emailPlaceholder')}
          aria-invalid={bad || undefined}
          onChange={(e) => onChange({ ...v, email: e.target.value, news: e.target.value.trim() ? v.news : false })}
          onBlur={onEmailBlur}
          onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
          className="max-w-sm"
        />
        <p className={bad ? 'text-xs text-destructive' : 'text-xs text-muted-foreground'}>{t(bad ? 'register.emailInvalid' : 'register.emailDesc')}</p>
      </div>
      <label className="flex items-start gap-2.5 text-sm">
        <Checkbox className="mt-0.5" checked={v.news} disabled={!v.email.trim() || bad} onCheckedChange={(c) => onChange({ ...v, news: c === true })} />
        <span>
          {t('register.news')}
          <span className="block text-xs text-muted-foreground">{t('register.newsDesc')}</span>
        </span>
      </label>
      <label className="flex items-start gap-2.5 text-sm">
        <Checkbox className="mt-0.5" checked={v.count} onCheckedChange={(c) => onChange({ ...v, count: c === true })} />
        <span>
          {t('register.count')}
          <span className="block text-xs text-muted-foreground">{t('register.countDesc')}</span>
        </span>
      </label>
    </div>
  )
}
