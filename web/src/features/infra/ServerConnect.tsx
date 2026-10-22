// Connecting the other servers of the Infra page (server/maxxing/infra/connect.py): a Hostinger VPS in one click (the
// Harness key is added through the Hostinger API when the VPS does not accept one of ours yet), any server by address
// (when no key works, the line to paste in its authorized_keys), then rename / disconnect.
import * as React from 'react'
import { KeyRound, Plug, Plus, Unplug } from 'lucide-react'
import { useInfraConnect, useInfraDomainAdd, useInfraDomainRemove, useInfraServerRemove, useInfraServerRename, type InfraConnectOut } from '@/lib/queries'
import type { InfraResource } from '@/lib/types'
import { errorMessage } from '@/lib/api'
import { useT } from '@/i18n'
import {
  Button, CopyButton, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, FormField, Input, confirm,
} from '@/components/ui'

function PasteKey({ out }: { out: InfraConnectOut }) {
  const t = useT()
  if (!out.command) return null
  return (
    <div className="grid gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-2.5 text-[13px]">
      <p>{t('infra.srv.pasteKey')}</p>
      <div className="flex items-start gap-1.5">
        <code className="min-w-0 flex-1 rounded bg-muted px-2 py-1.5 font-mono text-[11px] break-all">{out.command}</code>
        <CopyButton text={out.command} />
      </div>
      <p className="text-xs text-muted-foreground">{t('infra.srv.pasteThen')}</p>
    </div>
  )
}

/** For a Hostinger VPS that is not read yet: in its panel, or `compact` in its card. */
export function ConnectVps({ r, compact }: { r: InfraResource; compact?: boolean }) {
  const t = useT()
  const connect = useInfraConnect()
  const done = connect.data?.connected
  if (compact)
    return (
      <div className="grid gap-1.5">
        {done ? (
          <p className="text-[13px] text-success">{t('infra.srv.connected', { name: connect.data?.label || connect.data?.name || '' })}</p>
        ) : (
          <Button size="sm" className="justify-self-start" loading={connect.isPending} onClick={() => connect.mutate({ id: r.id })}>
            <KeyRound /> {connect.isPending ? t('infra.srv.connecting') : t('infra.srv.connectVps')}
          </Button>
        )}
        {connect.error && <p className="text-xs text-destructive">{errorMessage(connect.error)}</p>}
      </div>
    )
  return (
    <div className="grid gap-2 rounded-xl border border-primary/30 bg-primary/5 p-3" data-testid="infra-connect-vps">
      <p className="flex items-center gap-2 text-sm font-medium">
        <Plug className="size-4 text-primary" /> {t('infra.srv.connectTitle')}
      </p>
      <p className="text-[13px] text-muted-foreground">{t('infra.srv.connectHint')}</p>
      {done ? (
        <p className="text-[13px] text-success">{t('infra.srv.connected', { name: connect.data?.label || connect.data?.name || '' })}</p>
      ) : (
        <Button size="sm" className="justify-self-start" loading={connect.isPending} onClick={() => connect.mutate({ id: r.id })}>
          <KeyRound /> {connect.isPending ? t('infra.srv.connecting') : t('infra.srv.connect')}
        </Button>
      )}
      {connect.error && <p className="text-xs text-destructive">{errorMessage(connect.error)}</p>}
    </div>
  )
}

/** In the panel of a server read over SSH: its name on the page, disconnect. */
export function ServerSettings({ r }: { r: InfraResource }) {
  const t = useT()
  const name = r.details.server as string
  const rename = useInfraServerRename()
  const remove = useInfraServerRemove()
  const [label, setLabel] = React.useState(r.name)
  React.useEffect(() => setLabel(r.name), [r.id, r.name])
  const save = () => label.trim() && label.trim() !== r.name && rename.mutate({ name, label: label.trim() })
  const disconnect = async () => {
    if (await confirm({ title: t('infra.srv.removeTitle', { name: r.name }), description: t('infra.srv.removeDesc'), destructive: true, confirmText: t('infra.srv.remove') }))
      remove.mutate({ name })
  }
  return (
    <div className="grid gap-2 rounded-xl border p-3" data-testid="infra-server-settings">
      <FormField label={t('infra.srv.label')} hint={t('infra.srv.labelHint', { name })}>
        <Input value={label} onChange={(e) => setLabel(e.target.value)} onBlur={save} onKeyDown={(e) => e.key === 'Enter' && save()} className="h-8 text-xs" />
      </FormField>
      <Button variant="ghost" size="sm" className="justify-self-start text-destructive" loading={remove.isPending} onClick={disconnect}>
        <Unplug /> {t('infra.srv.remove')}
      </Button>
      {(rename.error || remove.error) && <p className="text-xs text-destructive">{errorMessage(rename.error || remove.error)}</p>}
    </div>
  )
}

/** Page action: connect any server by address. */
export function AddServer() {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const [f, setF] = React.useState({ host: '', user: 'root', port: '22', label: '' })
  const connect = useInfraConnect()
  const out = connect.data
  const close = () => {
    setOpen(false)
    connect.reset()
    setF({ host: '', user: 'root', port: '22', label: '' })
  }
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    connect.mutate({ host: f.host.trim(), user: f.user.trim() || 'root', port: Number(f.port) || 22, label: f.label.trim() }, { onSuccess: (o) => o.connected && close() })
  }
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)} data-testid="infra-add-server">
        <Plus /> {t('infra.srv.add')}
      </Button>
      <Dialog open={open} onOpenChange={(o) => !o && close()}>
        <DialogContent>
          <form onSubmit={submit} className="grid gap-3">
            <DialogHeader>
              <DialogTitle>{t('infra.srv.addTitle')}</DialogTitle>
              <DialogDescription>{t('infra.srv.addDesc')}</DialogDescription>
            </DialogHeader>
            <FormField label={t('infra.srv.host')}>
              <Input value={f.host} onChange={(e) => setF({ ...f, host: e.target.value })} placeholder="203.0.113.10" autoFocus required />
            </FormField>
            <div className="grid grid-cols-[1fr_96px] gap-2">
              <FormField label={t('infra.srv.user')}>
                <Input value={f.user} onChange={(e) => setF({ ...f, user: e.target.value })} />
              </FormField>
              <FormField label={t('infra.srv.port')}>
                <Input value={f.port} onChange={(e) => setF({ ...f, port: e.target.value.replace(/\D/g, '') })} inputMode="numeric" />
              </FormField>
            </div>
            <FormField label={t('infra.srv.label')}>
              <Input value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} placeholder={t('infra.srv.labelPlaceholder')} />
            </FormField>
            {out && !out.connected && <PasteKey out={out} />}
            {connect.error && <p className="text-xs text-destructive">{errorMessage(connect.error)}</p>}
            <DialogFooter>
              <Button type="submit" loading={connect.isPending} disabled={!f.host.trim()}>
                {out && !out.connected ? t('infra.srv.retry') : t('infra.srv.connect')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}

/** Domains tab: watch a domain from any registrar (public DNS + RDAP, no key). */
export function AddDomain() {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const [name, setName] = React.useState('')
  const add = useInfraDomainAdd()
  const close = () => {
    setOpen(false)
    setName('')
    add.reset()
  }
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)} data-testid="infra-add-domain">
        <Plus /> {t('infra.dom.add')}
      </Button>
      <Dialog open={open} onOpenChange={(o) => !o && close()}>
        <DialogContent>
          <form
            className="grid gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              add.mutate({ name: name.trim() }, { onSuccess: close })
            }}
          >
            <DialogHeader>
              <DialogTitle>{t('infra.dom.add')}</DialogTitle>
              <DialogDescription>{t('infra.dom.addDesc')}</DialogDescription>
            </DialogHeader>
            <FormField label={t('infra.dom.name')}>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="example.com" autoFocus required />
            </FormField>
            {add.error && <p className="text-xs text-destructive">{errorMessage(add.error)}</p>}
            <DialogFooter>
              <Button type="submit" loading={add.isPending} disabled={!name.trim()}>
                {t('infra.dom.add')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}

/** In the panel of a domain added by hand. */
export function RemoveDomain({ name }: { name: string }) {
  const t = useT()
  const remove = useInfraDomainRemove()
  return (
    <div className="grid gap-1.5 rounded-xl border p-3">
      <p className="text-[13px] text-muted-foreground">{t('infra.dom.addedHint')}</p>
      <Button variant="ghost" size="sm" className="justify-self-start text-destructive" loading={remove.isPending} onClick={() => remove.mutate({ name })}>
        <Unplug /> {t('infra.dom.remove')}
      </Button>
      {remove.error && <p className="text-xs text-destructive">{errorMessage(remove.error)}</p>}
    </div>
  )
}
