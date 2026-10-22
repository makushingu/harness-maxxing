// Optional Enterprise key: Settings -> License and the onboarding step "About you" (docs/user/23-license.md).
import { Button, Input, Label } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { useSaveLicense } from '@/lib/queries'
import { useT } from '@/i18n'

export const ENTERPRISE_URL = 'https://harness-maxxing.com/#enterprise'
export const LICENSE_URL = 'https://github.com/makushingu/harness-maxxing/blob/main/LICENSE'
export const validKey = (k: string) => /^HM(-[A-Z0-9]{4}){4}$/i.test(k.trim())

/** The key field. `withButton`: saves on its own (Settings); without, the caller saves it (onboarding). */
export function LicenseKeyField({ value, onChange, error, withButton }: { value: string; onChange: (v: string) => void; error?: string; withButton?: boolean }) {
  const t = useT()
  const save = useSaveLicense()
  const bad = !!value.trim() && !validKey(value)
  const shown = error || (save.error ? errorMessage(save.error) : '')
  const submit = () => validKey(value) && save.mutate(value.trim(), { onSuccess: () => onChange('') })
  return (
    <div className="grid gap-1.5">
      <Label htmlFor="license-key">{t('license.key')}</Label>
      <div className="flex flex-wrap gap-2">
        <Input
          id="license-key"
          value={value}
          autoComplete="off"
          spellCheck={false}
          placeholder="HM-XXXX-XXXX-XXXX-XXXX"
          aria-invalid={bad || !!shown || undefined}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          onKeyDown={(e) => withButton && e.key === 'Enter' && submit()}
          className="max-w-sm font-mono"
        />
        {withButton && (
          <Button onClick={submit} disabled={!validKey(value)} loading={save.isPending}>
            {t('license.save')}
          </Button>
        )}
      </div>
      <p className={bad || shown ? 'text-xs text-destructive' : 'text-xs text-muted-foreground'}>
        {bad ? t('license.invalid') : shown || t('license.keyDesc')}
      </p>
    </div>
  )
}

export function WhoNeedsAKey() {
  const t = useT()
  return (
    <div className="grid gap-2 text-sm">
      <p className="font-medium">{t('license.whoTitle')}</p>
      <ul className="grid list-disc gap-1 pl-5 text-muted-foreground">
        <li>{t('license.who1')}</li>
        <li>{t('license.who2')}</li>
      </ul>
      <p className="text-muted-foreground">{t('license.whoNot')}</p>
    </div>
  )
}
