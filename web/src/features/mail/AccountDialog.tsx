// Add or edit a mailbox: address + password, server settings detected from the address (known providers, MX,
// Thunderbird's autoconfig), then a real sign-in to IMAP and SMTP before saving.
import * as React from 'react'
import { ChevronDown, ChevronRight, Trash2 } from 'lucide-react'
import {
  Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, FormField, Input, SecretInput, Select, Textarea,
} from '@/components/ui'
import { toast } from '@/components/ui/toast'
import { errorMessage } from '@/lib/api'
import type { MailAccount, MailDetect, MailTls } from '@/lib/types'
import { useMailAddAccount, useMailDeleteAccount, useMailDetect, useMailUpdateAccount } from '@/lib/queries'
import { useT } from '@/i18n'

type Form = {
  address: string
  password: string
  label: string
  name: string
  username: string
  imap_host: string
  imap_port: string
  imap_tls: MailTls
  smtp_host: string
  smtp_port: string
  smtp_tls: MailTls
  signature: string
}

const empty: Form = {
  address: '', password: '', label: '', name: '', username: '', imap_host: '', imap_port: '993', imap_tls: 'ssl',
  smtp_host: '', smtp_port: '465', smtp_tls: 'ssl', signature: '',
}

function fromAccount(a: MailAccount): Form {
  return {
    address: a.address, password: '', label: a.label || '', name: a.name || '', username: a.username || '',
    imap_host: a.imap_host, imap_port: String(a.imap_port), imap_tls: a.imap_tls,
    smtp_host: a.smtp_host, smtp_port: String(a.smtp_port), smtp_tls: a.smtp_tls, signature: a.signature || '',
  }
}

export function AccountDialog({ open, onOpenChange, account, onSaved }: {
  open: boolean
  onOpenChange: (o: boolean) => void
  account?: MailAccount | null
  onSaved?: (a: MailAccount) => void
}) {
  const t = useT()
  const editing = !!account
  const [f, setF] = React.useState<Form>(empty)
  const [servers, setServers] = React.useState(false)
  const [detected, setDetected] = React.useState<MailDetect | null>(null)
  const detect = useMailDetect()
  const add = useMailAddAccount()
  const update = useMailUpdateAccount()
  const del = useMailDeleteAccount()
  const [confirmDel, setConfirmDel] = React.useState(false)

  React.useEffect(() => {
    if (!open) return
    setF(account ? fromAccount(account) : empty)
    setServers(!!account)
    setDetected(null)
    setConfirmDel(false)
    add.reset()
    update.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, account?.id])

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }))

  const runDetect = () => {
    if (editing || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.address.trim())) return
    detect.mutate(f.address.trim(), {
      onSuccess: (d) => {
        setDetected(d)
        setF((x) => ({
          ...x, imap_host: d.imap_host, imap_port: String(d.imap_port), imap_tls: d.imap_tls,
          smtp_host: d.smtp_host, smtp_port: String(d.smtp_port), smtp_tls: d.smtp_tls,
        }))
        if (d.source === 'guess') setServers(true)
      },
    })
  }

  const err = (add.error || update.error) as Error | null
  const busy = add.isPending || update.isPending

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const body = {
      label: f.label.trim(), name: f.name.trim(), username: f.username.trim() || undefined,
      imap_host: f.imap_host.trim(), imap_port: Number(f.imap_port) || 993, imap_tls: f.imap_tls,
      smtp_host: f.smtp_host.trim(), smtp_port: Number(f.smtp_port) || 465, smtp_tls: f.smtp_tls, signature: f.signature,
    }
    const done = (a: MailAccount, test: { smtp: string; smtp_error?: string; smtp_changed?: boolean; smtp_port?: number } | null) => {
      if (test?.smtp === 'error') toast.error(t('mail.acc.smtpFailed', { error: test.smtp_error || '' }))
      else if (test?.smtp_changed) toast.success(t('mail.acc.smtpPort', { port: test.smtp_port || '' }))
      else toast.success(editing ? t('mail.acc.saved') : t('mail.acc.added', { address: a.address }))
      onSaved?.(a)
      onOpenChange(false)
    }
    if (editing && account) {
      update.mutate({ id: account.id, ...body, ...(f.password ? { password: f.password } : {}) }, { onSuccess: (r) => done(r.account, r.test) })
    } else {
      add.mutate({ address: f.address.trim(), password: f.password, ...body }, { onSuccess: (r) => done(r.account, r.test) })
    }
  }

  const tlsOptions = [
    { value: 'ssl', label: 'SSL/TLS' },
    { value: 'starttls', label: 'STARTTLS' },
    { value: 'none', label: t('mail.acc.tlsNone') },
  ]

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{editing ? t('mail.acc.editTitle') : t('mail.acc.addTitle')}</DialogTitle>
            <DialogDescription>{t('mail.acc.desc')}</DialogDescription>
          </DialogHeader>
          <FormField label={t('mail.acc.address')}>
            <Input
              type="email"
              value={f.address}
              disabled={editing}
              autoComplete="off"
              placeholder="contact@example.com"
              onChange={(e) => set('address', e.target.value)}
              onBlur={runDetect}
              required
            />
          </FormField>
          <FormField label={t('mail.acc.password')} hint={editing ? t('mail.acc.passwordKeep') : t('mail.acc.passwordHint')}>
            <SecretInput value={f.password} onChange={(e) => set('password', e.target.value)} onFocus={runDetect} required={!editing} />
          </FormField>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField label={t('mail.acc.name')} hint={t('mail.acc.nameHint')}>
              <Input value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="Alex Martin" />
            </FormField>
            <FormField label={t('mail.acc.label')} hint={t('mail.acc.labelHint')}>
              <Input value={f.label} onChange={(e) => set('label', e.target.value)} placeholder={t('mail.acc.labelPh')} />
            </FormField>
          </div>

          <button
            type="button"
            className="flex items-center gap-1.5 text-left text-sm font-medium text-muted-foreground hover:text-foreground"
            onClick={() => setServers((s) => !s)}
            aria-expanded={servers}
          >
            {servers ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
            {t('mail.acc.servers')}
            {!servers && f.imap_host && <span className="truncate font-mono text-xs font-normal">{f.imap_host}</span>}
            {detect.isPending && <span className="text-xs font-normal">{t('mail.acc.detecting')}</span>}
          </button>
          {detected && !servers && <p className="-mt-2 text-xs text-muted-foreground">{t(`mail.acc.src.${detected.source}`)}</p>}
          {servers && (
            <div className="grid gap-3 rounded-lg border p-3">
              <p className="text-xs font-medium text-muted-foreground">{t('mail.acc.incoming')}</p>
              <div className="grid grid-cols-[1fr_5.5rem_8rem] gap-2">
                <Input aria-label="IMAP" value={f.imap_host} onChange={(e) => set('imap_host', e.target.value)} placeholder="imap.example.com" required />
                <Input aria-label={t('mail.acc.port')} inputMode="numeric" value={f.imap_port} onChange={(e) => set('imap_port', e.target.value)} />
                <Select aria-label={t('mail.acc.security')} value={f.imap_tls} onValueChange={(v) => set('imap_tls', v as MailTls)} options={tlsOptions} />
              </div>
              <p className="text-xs font-medium text-muted-foreground">{t('mail.acc.outgoing')}</p>
              <div className="grid grid-cols-[1fr_5.5rem_8rem] gap-2">
                <Input aria-label="SMTP" value={f.smtp_host} onChange={(e) => set('smtp_host', e.target.value)} placeholder="smtp.example.com" required />
                <Input aria-label={t('mail.acc.port')} inputMode="numeric" value={f.smtp_port} onChange={(e) => set('smtp_port', e.target.value)} />
                <Select aria-label={t('mail.acc.security')} value={f.smtp_tls} onValueChange={(v) => set('smtp_tls', v as MailTls)} options={tlsOptions} />
              </div>
              <FormField label={t('mail.acc.username')} hint={t('mail.acc.usernameHint')}>
                <Input value={f.username} onChange={(e) => set('username', e.target.value)} placeholder={f.address || 'contact@example.com'} />
              </FormField>
              <p className="text-xs text-muted-foreground">{t('mail.acc.portsNote')}</p>
            </div>
          )}
          {editing && (
            <FormField label={t('mail.acc.signature')}>
              <Textarea rows={3} value={f.signature} onChange={(e) => set('signature', e.target.value)} />
            </FormField>
          )}
          {err && <p className="text-sm text-destructive">{errorMessage(err)}</p>}
          <DialogFooter className="gap-2 sm:justify-between">
            {editing && account ? (
              <Button
                type="button"
                variant={confirmDel ? 'destructive' : 'ghost'}
                loading={del.isPending}
                onClick={() => (confirmDel ? del.mutate(account.id, { onSuccess: () => onOpenChange(false) }) : setConfirmDel(true))}
              >
                <Trash2 /> {confirmDel ? t('mail.acc.deleteConfirm') : t('mail.acc.delete')}
              </Button>
            ) : (
              <span />
            )}
            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" loading={busy}>
                {busy ? t('mail.acc.testing') : editing ? t('common.save') : t('mail.acc.add')}
              </Button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
