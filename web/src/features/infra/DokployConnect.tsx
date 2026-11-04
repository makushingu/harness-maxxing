// Dokploy source of the Infra page (server/maxxing/dokploy.py): its address and API key, checked before they are kept;
// the key stays in the vault, never exposed to sessions (they deploy with `maxxing dokploy`).
import * as React from 'react'
import { Plug, Unplug } from 'lucide-react'
import { useInfraDokployConnect, useInfraDokployDisconnect } from '@/lib/queries'
import { errorMessage } from '@/lib/api'
import { useT } from '@/i18n'
import {
  Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, FormField, Input, SecretInput, confirm,
} from '@/components/ui'

export function DokployConnect({ url }: { url?: string }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const [f, setF] = React.useState({ url: url || 'http://127.0.0.1:3000', key: '' })
  const connect = useInfraDokployConnect()
  const close = () => {
    setOpen(false)
    connect.reset()
    setF((x) => ({ ...x, key: '' }))
  }
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    connect.mutate({ url: f.url.trim(), key: f.key.trim() }, { onSuccess: close })
  }
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)} data-testid="infra-dokploy-connect">
        <Plug /> {t('infra.dokploy.connect')}
      </Button>
      <Dialog open={open} onOpenChange={(o) => !o && close()}>
        <DialogContent>
          <form onSubmit={submit} className="grid gap-3">
            <DialogHeader>
              <DialogTitle>{t('infra.dokploy.title')}</DialogTitle>
              <DialogDescription>{t('infra.dokploy.desc')}</DialogDescription>
            </DialogHeader>
            <FormField label={t('infra.dokploy.url')}>
              <Input value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="http://127.0.0.1:3000" required />
            </FormField>
            <FormField label={t('infra.dokploy.key')} hint={t('infra.dokploy.keyHint')}>
              <SecretInput value={f.key} onChange={(e) => setF({ ...f, key: e.target.value })} autoFocus required />
            </FormField>
            {connect.error && <p className="text-xs text-destructive">{errorMessage(connect.error)}</p>}
            <DialogFooter>
              <Button type="submit" loading={connect.isPending} disabled={!f.url.trim() || !f.key.trim()}>
                {t('infra.dokploy.connect')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}

export function DokployDisconnect({ url }: { url?: string }) {
  const t = useT()
  const off = useInfraDokployDisconnect()
  const ask = async () => {
    if (await confirm({ title: t('infra.dokploy.removeTitle'), description: t('infra.dokploy.removeDesc'), destructive: true, confirmText: t('infra.dokploy.remove') }))
      off.mutate()
  }
  return (
    <>
      {url && <span className="max-w-60 truncate font-mono text-xs text-muted-foreground" title={url}>{url}</span>}
      <Button variant="ghost" size="sm" loading={off.isPending} onClick={ask} aria-label={t('infra.dokploy.remove')}>
        <Unplug />
      </Button>
    </>
  )
}
