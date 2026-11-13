// Add or edit a mailbox: address + password, server settings detected from the address (known providers, MX,
// Thunderbird's autoconfig), then a real sign-in to IMAP and SMTP before saving. Editing also sets how often it is
// checked for new mail, shows the agents that may use it, and (folded) the servers whose sender checks are trusted.
import * as React from 'react'
import { Link } from 'react-router'
import { ChevronDown, ChevronRight, Trash2 } from 'lucide-react'
import {
  Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, FormField, Input, SecretInput, Select, Textarea,
} from '@/components/ui'
import { toast } from '@/components/ui/toast'
import { errorMessage } from '@/lib/api'
import type { MailAccount, MailDetect, MailPollMin, MailSenderCheck, MailTls } from '@/lib/types'
import { AGENT_PATH_RE, useMailAddAccount, useMailDeleteAccount, useMailDetect, useMailUpdateAccount } from '@/lib/queries'
import { AgentAvatarIcon } from '@/features/agents/Avatar'
import { useT } from '@/i18n'
import { rightsText } from './agents'

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
  poll_min: string
  /** one host per line or comma */
  auth_servers: string
}

const empty: Form = {
  address: '', password: '', label: '', name: '', username: '', imap_host: '', imap_port: '993', imap_tls: 'ssl',
  smtp_host: '', smtp_port: '465', smtp_tls: 'ssl', signature: '', poll_min: '10', auth_servers: '',
}
const POLL: MailPollMin[] = [5, 10, 30, 60]

function fromAccount(a: MailAccount): Form {
  return {
    address: a.address, password: '', label: a.label || '', name: a.name || '', username: a.username || '',
    imap_host: a.imap_host, imap_port: String(a.imap_port), imap_tls: a.imap_tls,
    smtp_host: a.smtp_host, smtp_port: String(a.smtp_port), smtp_tls: a.smtp_tls, signature: a.signature || '',
    poll_min: String(a.poll_min || 10), auth_servers: (a.auth_servers || []).join('\n'),
  }
}

// providers where a plain password is not enough: shown under the password field once the address is known
const PROTON = /@(proton\.me|protonmail\.(com|ch)|pm\.me)$/i
function providerNote(address: string, d: MailDetect | null, imapHost: string): 'gmail' | 'microsoft' | 'proton' | null {
  const host = (imapHost || d?.imap_host || '').toLowerCase()
  if (PROTON.test(address.trim()) || d?.mx.some((m) => /protonmail\.ch\.?$/i.test(m))) return 'proton'
  if (host === 'imap.gmail.com') return 'gmail'
  if (host === 'outlook.office365.com') return 'microsoft'
  return null
}

export function AccountDialog({ open, onOpenChange, account, onSaved, address }: {
  open: boolean
  onOpenChange: (o: boolean) => void
  account?: MailAccount | null
  onSaved?: (a: MailAccount) => void
  address?: string // a new mailbox prefilled with this address (Infra -> E-mail: "Add to the E-mail page")
}) {
  const t = useT()
  const editing = !!account
  const [f, setF] = React.useState<Form>(empty)
  const [servers, setServers] = React.useState(false)
  const [trust, setTrust] = React.useState(false)
  const [detected, setDetected] = React.useState<MailDetect | null>(null)
  const detect = useMailDetect()
  const add = useMailAddAccount()
  const update = useMailUpdateAccount()
  const del = useMailDeleteAccount()
  const [confirmDel, setConfirmDel] = React.useState(false)

  React.useEffect(() => {
    if (!open) return
    setF(account ? fromAccount(account) : { ...empty, address: address || '', username: address || '' })
    setServers(!!account)
    setTrust(!!account?.auth_servers?.length)
    setDetected(null)
    setConfirmDel(false)
    add.reset()
    update.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, account?.id, address])

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
  const note = editing ? null : providerNote(f.address, detected, f.imap_host)
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
      const extra = {
        poll_min: Number(f.poll_min) as MailPollMin,
        auth_servers: f.auth_servers.split(/[\s,]+/).map((x) => x.trim().toLowerCase()).filter(Boolean),
      }
      update.mutate({ id: account.id, ...body, ...extra, ...(f.password ? { password: f.password } : {}) }, { onSuccess: (r) => done(r.account, r.test) })
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
          {note && (
            <p className="rounded-md border border-border bg-muted px-3 py-2 text-sm text-muted-foreground">
              {t(`mail.acc.note.${note}`)}
              {note === 'gmail' && (
                <> <a className="text-primary underline" href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer">myaccount.google.com/apppasswords</a></>
              )}
            </p>
          )}
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
            className="flex items-center gap-1.5 text-left text-sm font-medium text-muted-foreground hover:text-foreground pointer-coarse:min-h-10"
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
              <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-2 sm:grid-cols-[minmax(0,1fr)_5.5rem_8rem]">
                <Input aria-label="IMAP" className="max-sm:col-span-2" value={f.imap_host} onChange={(e) => set('imap_host', e.target.value)} placeholder="imap.example.com" required />
                <Input aria-label={t('mail.acc.port')} inputMode="numeric" value={f.imap_port} onChange={(e) => set('imap_port', e.target.value)} />
                <Select aria-label={t('mail.acc.security')} value={f.imap_tls} onValueChange={(v) => set('imap_tls', v as MailTls)} options={tlsOptions} />
              </div>
              <p className="text-xs font-medium text-muted-foreground">{t('mail.acc.outgoing')}</p>
              <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-2 sm:grid-cols-[minmax(0,1fr)_5.5rem_8rem]">
                <Input aria-label="SMTP" className="max-sm:col-span-2" value={f.smtp_host} onChange={(e) => set('smtp_host', e.target.value)} placeholder="smtp.example.com" required />
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
          {editing && account && (
            <>
              <FormField label={t('mail.agents.poll')} hint={t('mail.agents.pollHint')}>
                <Select value={f.poll_min} onValueChange={(v) => set('poll_min', v)} options={POLL.map((n) => ({ value: String(n), label: t('mail.agents.pollMin', { count: n }) }))} />
              </FormField>
              <div className="grid gap-2" data-testid="mail-acc-agents">
                <span className="text-sm font-medium">{t('mail.agents.title')}</span>
                {account.agents?.length ? (
                  <ul className="divide-y rounded-lg border">
                    {account.agents.map((g) => {
                      const m = AGENT_PATH_RE.exec(g.agent)
                      return (
                        <li key={g.agent}>
                          <Link
                            to={m ? `/agents/${m[1]}/${m[2]}/${m[3]}?settings=mail` : '/agents'}
                            className="flex items-center gap-2.5 px-3 py-2 hover:bg-muted"
                          >
                            <AgentAvatarIcon avatar={g.avatar} size={24} mood={g.enabled ? 'idle' : 'sleep'} />
                            <span className="grid min-w-0 flex-1">
                              <span className="truncate text-sm">{g.name}</span>
                              <span className="truncate text-xs text-muted-foreground">
                                {rightsText(t, g.rights)}
                                {g.senders.length ? ` · ${t('mail.agents.onlyFrom', { list: g.senders.join(', ') })}` : ''}
                                {g.trigger?.enabled ? ` · ${t('mail.agents.watches')}` : ''}
                              </span>
                            </span>
                            <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                          </Link>
                        </li>
                      )
                    })}
                  </ul>
                ) : (
                  <p className="text-xs text-muted-foreground">{t('mail.agents.none')}</p>
                )}
              </div>
              {account?.sender_check && (
                <SenderCheck
                  check={account.sender_check}
                  onTrust={(server) => {
                    set('auth_servers', server)
                    setTrust(true)
                  }}
                />
              )}
              <button
                type="button"
                className="flex items-center gap-1.5 text-left text-sm font-medium text-muted-foreground hover:text-foreground"
                onClick={() => setTrust((s) => !s)}
                aria-expanded={trust}
              >
                {trust ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                {t('mail.agents.trust')}
              </button>
              {trust && (
                <FormField label={t('mail.agents.trustLabel')} hint={t('mail.agents.trustHint')}>
                  <Textarea rows={2} value={f.auth_servers} onChange={(e) => set('auth_servers', e.target.value)} placeholder="mx.example.com" className="font-mono text-[13px]" />
                </FormField>
              )}
            </>
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

/** Who checks the senders of this mailbox (server: imap.sender_check) - an agent's "only mail from" list needs it. */
function SenderCheck({ check, onTrust }: { check: MailSenderCheck; onTrust: (server: string) => void }) {
  const t = useT()
  if (check.state === 'auto' || check.state === 'owner') {
    return <p className="text-xs text-muted-foreground">{t(`mail.check.${check.state}`, { server: check.server })}</p>
  }
  return (
    <div className="grid gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs">
      <p>{t(`mail.check.${check.state}`, { server: check.server })}</p>
      {check.state === 'detected' && (
        <Button type="button" size="sm" variant="outline" className="justify-self-start" onClick={() => onTrust(check.server)}>
          {t('mail.check.trust', { server: check.server })}
        </Button>
      )}
    </div>
  )
}
