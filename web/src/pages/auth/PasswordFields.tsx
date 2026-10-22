import { cn } from '@/lib/utils'
import { useT, type TKey } from '@/i18n'
import { FormField, SecretInput } from '@/components/ui'
import { MIN_PASSWORD, passwordScore } from './strength'

const LABELS: TKey[] = ['pw.strength.0', 'pw.strength.1', 'pw.strength.2', 'pw.strength.3', 'pw.strength.4']

export function StrengthMeter({ password }: { password: string }) {
  const t = useT()
  const s = passwordScore(password)
  const color = s <= 1 ? 'bg-destructive' : s === 2 ? 'bg-warning' : 'bg-success'
  return (
    <div className="grid gap-1.5" aria-live="polite">
      <div className="grid grid-cols-4 gap-1">
        {[1, 2, 3, 4].map((i) => (
          <span key={i} className={cn('h-1 rounded-full bg-muted transition-colors', password && i <= s && color)} />
        ))}
      </div>
      <span className="text-xs text-muted-foreground">{password ? t(LABELS[s]) : t('pw.hint')}</span>
    </div>
  )
}

/** New password + confirmation, with strength hint. Validation errors are returned by validatePasswords(). */
export function NewPasswordFields({
  password,
  confirm,
  onPassword,
  onConfirm,
  errors,
  autoFocus,
}: {
  password: string
  confirm: string
  onPassword: (v: string) => void
  onConfirm: (v: string) => void
  errors: { password?: string; confirm?: string }
  autoFocus?: boolean
}) {
  const t = useT()
  return (
    <>
      <div className="grid gap-2">
        <FormField label={t('pw.new')} error={errors.password}>
          <SecretInput value={password} onChange={(e) => onPassword(e.target.value)} autoComplete="new-password" autoFocus={autoFocus} />
        </FormField>
        <StrengthMeter password={password} />
      </div>
      <FormField label={t('pw.confirm')} error={errors.confirm}>
        <SecretInput value={confirm} onChange={(e) => onConfirm(e.target.value)} autoComplete="new-password" />
      </FormField>
    </>
  )
}

export function validatePasswords(t: (k: TKey) => string, password: string, confirm: string) {
  const e: { password?: string; confirm?: string } = {}
  if (password.length < MIN_PASSWORD) e.password = t('pw.tooShort')
  else if (confirm !== password) e.confirm = t('pw.mismatch')
  return e
}
