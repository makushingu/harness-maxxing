// Team -> Connections: connect with someone else's Harness (one-time invitation), answer requests, see contacts.
import * as React from 'react'
import { Check, Copy, Link2, LogIn, ShieldAlert, Trash2, UserPlus, X } from 'lucide-react'
import { errorMessage } from '@/lib/api'
import { useTeamAnswer, useTeamConnections, useTeamInvite, useTeamJoin, useTeamRemoveContact, type TeamContact } from '@/lib/queries'
import { useT } from '@/i18n'
import { Button, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, Input, Skeleton, toast } from '@/components/ui'
import { Callout } from '@/features/common'
import { Avatar } from '@/features/profile/Avatar'

export function ConnectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const t = useT()
  const { data: c } = useTeamConnections(open)
  const invite = useTeamInvite()
  const join = useTeamJoin()
  const [code, setCode] = React.useState<string | null>(null)
  const [paste, setPaste] = React.useState('')
  const [joinError, setJoinError] = React.useState('')
  React.useEffect(() => {
    if (open) {
      setCode(null)
      setPaste('')
      setJoinError('')
    }
  }, [open])
  const requests = c?.contacts.filter((x) => x.status === 'request') || []
  const waiting = c?.contacts.filter((x) => x.status === 'waiting') || []
  const contacts = c?.contacts.filter((x) => x.status === 'accepted') || []
  const copy = (s: string) => void navigator.clipboard?.writeText(s).then(() => toast.success(t('team.copied')))
  const doJoin = () =>
    join.mutate(paste.trim(), {
      onSuccess: (r) => {
        setPaste('')
        setJoinError('')
        toast.success(t('team.cx.joined'), t('team.cx.joinedDesc', { fp: r.fingerprint }))
      },
      onError: (e) => setJoinError(errorMessage(e)),
    })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="md:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('team.cx.title')}</DialogTitle>
          <DialogDescription>{t('team.cx.desc')}</DialogDescription>
        </DialogHeader>

        <Callout tone="warning" icon={ShieldAlert} title={t('team.cx.trustTitle')}>
          {t('team.cx.trust')}
        </Callout>

        {!c ? (
          <Skeleton className="h-40" />
        ) : !c.ok ? (
          <Callout tone="error" title={t('team.cx.notReady')}>
            {t(`team.cx.reason.${c.reason || 'no_address'}`)} {t('team.cx.needDomain')}
          </Callout>
        ) : (
          <>
            <p className="text-[12.5px] text-muted-foreground">
              {t('team.cx.yourAddress')} <span className="font-mono text-foreground">{c.address}</span> · {t('team.cx.noTailscale')}
            </p>

            {requests.length > 0 && (
              <section className="flex flex-col gap-2">
                <h3 className="text-[13px] font-semibold">{t('team.cx.requests')}</h3>
                {requests.map((x) => (
                  <Request key={x.address} x={x} />
                ))}
              </section>
            )}

            <section className="grid gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-2 rounded-xl border p-3">
                <div className="flex items-center gap-2 text-[13.5px] font-semibold">
                  <UserPlus className="size-4 text-primary" /> {t('team.cx.invite')}
                </div>
                <p className="text-[12.5px] text-muted-foreground">{t('team.cx.inviteDesc')}</p>
                {code ? (
                  <div className="flex flex-col gap-1.5">
                    <div className="flex items-center gap-1">
                      <Input readOnly value={code} className="h-8 font-mono text-[11.5px]" onFocus={(e) => e.target.select()} />
                      <Button size="icon-sm" variant="outline" onClick={() => copy(code)} aria-label={t('team.copy')}>
                        <Copy className="size-3.5" />
                      </Button>
                    </div>
                    <p className="text-[11.5px] text-muted-foreground">{t('team.cx.inviteOnce')}</p>
                  </div>
                ) : (
                  <Button size="sm" className="mt-auto" loading={invite.isPending} onClick={() => invite.mutate(undefined, { onSuccess: (r) => setCode(r.invitation) })}>
                    <Link2 /> {t('team.cx.create')}
                  </Button>
                )}
              </div>
              <div className="flex flex-col gap-2 rounded-xl border p-3">
                <div className="flex items-center gap-2 text-[13.5px] font-semibold">
                  <LogIn className="size-4 text-primary" /> {t('team.cx.join')}
                </div>
                <p className="text-[12.5px] text-muted-foreground">{t('team.cx.joinDesc')}</p>
                <Input value={paste} onChange={(e) => setPaste(e.target.value)} placeholder="https://ui.example.com#…" className="h-8 font-mono text-[11.5px]" />
                {joinError && <p className="text-[12px] text-destructive">{joinError}</p>}
                <Button size="sm" variant="outline" className="mt-auto" disabled={!paste.includes('#')} loading={join.isPending} onClick={doJoin}>
                  {t('team.cx.joinBtn')}
                </Button>
              </div>
            </section>

            {waiting.length > 0 && (
              <section className="flex flex-col gap-1.5">
                <h3 className="text-[13px] font-semibold">{t('team.cx.waiting')}</h3>
                {waiting.map((x) => (
                  <ContactRow key={x.address} x={x} note={t('team.cx.waitingNote')} />
                ))}
              </section>
            )}
            <section className="flex flex-col gap-1.5">
              <h3 className="text-[13px] font-semibold">{t('team.cx.contacts')}</h3>
              {contacts.length ? contacts.map((x) => <ContactRow key={x.address} x={x} />) : <p className="text-[12.5px] text-muted-foreground">{t('team.cx.none')}</p>}
            </section>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

function Request({ x }: { x: TeamContact }) {
  const t = useT()
  const answer = useTeamAnswer()
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-primary/40 bg-primary/[0.04] p-3">
      <div className="flex items-center gap-2.5">
        <Avatar profile={x} />
        <div className="min-w-0 flex-1">
          <div className="text-[14px] font-medium">{x.name || x.address}</div>
          <div className="truncate font-mono text-[11.5px] text-muted-foreground">{x.address}</div>
        </div>
      </div>
      <p className="text-[12.5px] text-muted-foreground">{t('team.cx.fingerprint', { fp: x.fingerprint })}</p>
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" disabled={answer.isPending} onClick={() => answer.mutate({ address: x.address, accept: false })}>
          <X /> {t('team.cx.refuse')}
        </Button>
        <Button size="sm" loading={answer.isPending} onClick={() => answer.mutate({ address: x.address, accept: true })}>
          <Check /> {t('team.cx.accept')}
        </Button>
      </div>
    </div>
  )
}

function ContactRow({ x, note }: { x: TeamContact; note?: string }) {
  const t = useT()
  const remove = useTeamRemoveContact()
  return (
    <div className="group/c flex items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-accent/40">
      <Avatar profile={x} size="sm" />
      <span className="min-w-0 flex-1">
        <span className="text-[13.5px] font-medium">{x.name || x.address}</span>
        <span className="ml-2 font-mono text-[11.5px] text-muted-foreground">{note || x.address.replace(/^https?:\/\//, '')}</span>
      </span>
      <span className="font-mono text-[11px] text-muted-foreground" title={t('team.cx.fpTitle')}>
        {x.fingerprint}
      </span>
      <Button
        size="icon-sm"
        variant="ghost"
        className="opacity-0 group-hover/c:opacity-100"
        aria-label={t('team.cx.remove')}
        onClick={() => window.confirm(t('team.cx.removeConfirm', { name: x.name || x.address })) && remove.mutate(x.address)}
      >
        <Trash2 className="size-3.5" />
      </Button>
    </div>
  )
}
