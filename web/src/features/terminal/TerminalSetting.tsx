// Settings -> Features, under Sessions: "Code mode" (the terminal). Turning it on asks for the password again (a terminal runs
// any command on the server); off closes every terminal.
import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Input, Switch, toast } from '@/components/ui'
import { SettingRow } from '@/features/common'
import { errorMessage, isApiError } from '@/lib/api'
import { qk } from '@/lib/queries/keys'
import { useT } from '@/i18n'
import { termApi, termKey } from './api'

export function TerminalSetting({ on }: { on: boolean }) {
  const t = useT()
  const qc = useQueryClient()
  const [asking, setAsking] = React.useState(false)
  const [pw, setPw] = React.useState('')
  const [err, setErr] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: qk.settings })
    void qc.invalidateQueries({ queryKey: termKey })
  }
  const enable = async () => {
    setBusy(true)
    setErr('')
    try {
      await termApi.enable(pw)
      setAsking(false)
      setPw('')
      refresh()
    } catch (e) {
      setErr(isApiError(e, 'bad_password') ? t('term.badPassword') : errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <SettingRow label={t('term.setting')} description={t('term.settingDesc')} htmlFor="ft-terminal">
        <Switch
          id="ft-terminal"
          checked={on}
          onCheckedChange={(v) => {
            if (v) return setAsking(true)
            termApi.disable().then(refresh, (e) => toast.error(errorMessage(e)))
          }}
        />
      </SettingRow>
      <Dialog open={asking} onOpenChange={(o) => !o && setAsking(false)}>
        <DialogContent className="sm:max-w-sm">
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void enable()
            }}
            className="grid gap-4"
          >
            <DialogHeader>
              <DialogTitle>{t('term.enableTitle')}</DialogTitle>
              <DialogDescription>{t('term.enableDesc')}</DialogDescription>
            </DialogHeader>
            <Input type="password" autoFocus autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder={t('term.password')} aria-invalid={!!err} />
            {err && <p className="text-xs text-destructive">{err}</p>}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setAsking(false)}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" loading={busy} disabled={!pw}>
                {t('term.enable')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
