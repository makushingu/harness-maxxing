// Team -> Friends: the people you are connected with (open a chat in one click), requests to answer, and the
// "Add a friend" dialog (one-time invitation, server to server).
import * as React from 'react'
import { Check, Copy, Fingerprint, Link2, LogIn, MessageCircle, MoreHorizontal, ShieldAlert, Trash2, UserPlus, X } from 'lucide-react'
import { errorMessage } from '@/lib/api'
import {
  useTeamAnswer, useTeamConnections, useTeamCreateChat, useTeamInvite, useTeamJoin, useTeamRemoveContact, type TeamContact, type TeamState,
} from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import {
  Button, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger, EmptyState, Input, Skeleton, toast,
} from '@/components/ui'
import { Callout } from '@/features/common'
import { Avatar } from '@/features/profile/Avatar'
import { friendsOf, PersonAvatar, usePresence } from './people'

/** Open the direct chat with a person (created the first time, the same one after). */
export function useOpenDm(onOpen: (chatId: string) => void) {
  const create = useTeamCreateChat()
  return {
    open: (person: string) => create.mutate({ kind: 'dm', members: [person] }, { onSuccess: (c) => onOpen(c.id) }),
    pending: create.isPending ? create.variables?.members[0] : undefined,
  }
}

/* ------------------------------------------------------------------------------------------------ friends tab */
export function FriendsView({ team, onOpenChat, compact }: { team: TeamState | undefined; onOpenChat: (id: string) => void; compact?: boolean }) {
  const t = useT()
  const presence = usePresence()
  const { data: cx } = useTeamConnections()
  const [add, setAdd] = React.useState(false)
  const [q, setQ] = React.useState('')
  const dm = useOpenDm(onOpenChat)
  const requests = cx?.contacts.filter((x) => x.status === 'request') || []
  const waiting = cx?.contacts.filter((x) => x.status === 'waiting') || []
  const byId = new Map((cx?.contacts || []).map((x) => [x.id, x]))
  const friends = friendsOf(team).filter(([, p]) => !q || p.name.toLowerCase().includes(q.toLowerCase()))
  const online = friends.filter(([, p]) => p.status === 'online').length
  const nobody = team && cx && !friendsOf(team).length && !requests.length && !waiting.length

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className={cn('flex items-center gap-2 border-b', compact ? 'p-2' : 'p-3')}>
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('team.friends.search')} className="h-8 flex-1 text-[13px]" />
        <Button size="sm" onClick={() => setAdd(true)} className="shrink-0">
          <UserPlus /> {t('team.friends.add')}
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto p-2">
        {!team || !cx ? (
          [0, 1, 2].map((i) => <Skeleton key={i} className="m-1 h-12" />)
        ) : nobody ? (
          <EmptyState
            compact
            icon={UserPlus}
            title={t('team.friends.none')}
            description={t('team.friends.noneDesc')}
            action={
              <Button onClick={() => setAdd(true)}>
                <UserPlus /> {t('team.friends.add')}
              </Button>
            }
          />
        ) : (
          <>
            {requests.length > 0 && (
              <Section title={t('team.cx.requests')} count={requests.length}>
                {requests.map((x) => (
                  <Request key={x.address} x={x} />
                ))}
              </Section>
            )}
            {friendsOf(team).length > 0 && (
              <Section title={t('team.friends.title')} hint={online ? t('team.online', { count: online }) : undefined}>
                {friends.map(([id, p]) => (
                  <div
                    key={id}
                    role="button"
                    tabIndex={0}
                    onClick={() => dm.open(id)}
                    onKeyDown={(e) => e.key === 'Enter' && dm.open(id)}
                    className="group/f flex cursor-pointer items-center gap-3 rounded-lg px-2 py-1.5 transition-colors hover:bg-accent/60"
                  >
                    <PersonAvatar person={p} status />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[14px] font-medium">{p.name}</span>
                      <span className={cn('block truncate text-[12px]', p.status === 'online' ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground')}>{presence(p)}</span>
                    </span>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      loading={dm.pending === id}
                      className="text-muted-foreground opacity-0 group-hover/f:opacity-100 focus-visible:opacity-100 max-md:opacity-100"
                      aria-label={t('team.friends.message', { name: p.name })}
                    >
                      <MessageCircle />
                    </Button>
                    <FriendMenu contact={byId.get(id)} name={p.name} />
                  </div>
                ))}
                {!friends.length && <p className="px-2 py-3 text-[12.5px] text-muted-foreground">{t('team.friends.noMatch')}</p>}
              </Section>
            )}
            {waiting.length > 0 && (
              <Section title={t('team.cx.waiting')} count={waiting.length}>
                {waiting.map((x) => (
                  <div key={x.address} className="group/f flex items-center gap-3 rounded-lg px-2 py-1.5">
                    <Avatar profile={x} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13.5px] font-medium">{x.name || t('team.friends.someone')}</span>
                      <span className="block text-[12px] text-muted-foreground">{t('team.cx.waitingNote')}</span>
                    </span>
                    <FriendMenu contact={x} name={x.name} />
                  </div>
                ))}
              </Section>
            )}
          </>
        )}
      </div>
      <AddFriendDialog open={add} onOpenChange={setAdd} />
    </div>
  )
}

function Section({ title, count, hint, children }: { title: string; count?: number; hint?: string; children: React.ReactNode }) {
  return (
    <section className="mb-3 flex flex-col gap-0.5">
      <h3 className="flex items-baseline gap-1.5 px-2 pt-1 pb-1 text-[11.5px] font-semibold tracking-wide text-muted-foreground uppercase">
        {title}
        {!!count && <span className="tabular-nums">· {count}</span>}
        {hint && <span className="ml-auto font-medium tracking-normal text-emerald-600 normal-case dark:text-emerald-400">{hint}</span>}
      </h3>
      {children}
    </section>
  )
}

/** The fingerprint (to check the link with the person) and Remove. */
function FriendMenu({ contact, name }: { contact: TeamContact | undefined; name: string }) {
  const t = useT()
  const remove = useTeamRemoveContact()
  if (!contact) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="icon-sm" variant="ghost" onClick={(e) => e.stopPropagation()} className="text-muted-foreground opacity-0 group-hover/f:opacity-100 data-[state=open]:opacity-100 max-md:opacity-100" aria-label={t('common.more')}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64" onClick={(e) => e.stopPropagation()}>
        <DropdownMenuLabel className="flex items-center gap-2 font-normal text-muted-foreground">
          <Fingerprint className="size-4" />
          <span className="text-[12px]">{t('team.friends.fp')}</span>
          <span className="ml-auto font-mono text-[12px] text-foreground">{contact.fingerprint}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          destructive
          onSelect={() => window.confirm(t('team.cx.removeConfirm', { name: name || t('team.friends.someone') })) && remove.mutate(contact.address)}
        >
          <Trash2 className="size-4" /> {contact.status === 'waiting' ? t('team.friends.cancel') : t('team.cx.remove')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function Request({ x }: { x: TeamContact }) {
  const t = useT()
  const answer = useTeamAnswer()
  return (
    <div className="mx-1 mb-1 flex flex-col gap-2 rounded-xl border border-primary/40 bg-primary/[0.04] p-3">
      <div className="flex items-center gap-2.5">
        <Avatar profile={x} size="lg" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[14px] font-medium">{x.name || t('team.friends.someone')}</div>
          <div className="text-[12px] text-muted-foreground">{t('team.friends.wants')}</div>
        </div>
      </div>
      <p className="text-[12px] text-muted-foreground">{t('team.cx.fingerprint', { fp: x.fingerprint })}</p>
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

/* ------------------------------------------------------------------------------------------------ add a friend */
export function AddFriendDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
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
  const copy = (s: string) => void navigator.clipboard?.writeText(s).then(() => toast.success(t('team.copied')))
  const doJoin = () =>
    join.mutate(paste.trim(), {
      onSuccess: (r) => {
        onOpenChange(false)
        toast.success(t('team.cx.joined'), t('team.cx.joinedDesc', { fp: r.fingerprint }))
      },
      onError: (e) => setJoinError(errorMessage(e)),
    })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="md:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('team.friends.add')}</DialogTitle>
          <DialogDescription>{t('team.cx.desc')}</DialogDescription>
        </DialogHeader>
        {!c ? (
          <Skeleton className="h-40" />
        ) : !c.ok ? (
          <Callout tone="error" title={t('team.cx.notReady')}>
            {t(`team.cx.reason.${c.reason || 'no_address'}`)} {t('team.cx.needDomain')}
          </Callout>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-2 rounded-xl border p-3.5">
              <div className="flex items-center gap-2 text-[14px] font-semibold">
                <span className="inline-flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Link2 className="size-4" />
                </span>
                {t('team.cx.invite')}
              </div>
              <p className="text-[12.5px] text-muted-foreground">{t('team.cx.inviteDesc')}</p>
              {code ? (
                <div className="mt-auto flex flex-col gap-1.5">
                  <Button size="sm" onClick={() => copy(code)}>
                    <Copy /> {t('team.friends.copyInvite')}
                  </Button>
                  <Input readOnly value={code} className="h-7 font-mono text-[11px]" onFocus={(e) => e.target.select()} />
                  <p className="text-[11.5px] text-muted-foreground">{t('team.cx.inviteOnce')}</p>
                </div>
              ) : (
                <Button size="sm" className="mt-auto" loading={invite.isPending} onClick={() => invite.mutate(undefined, { onSuccess: (r) => setCode(r.invitation) })}>
                  <Link2 /> {t('team.cx.create')}
                </Button>
              )}
            </div>
            <div className="flex flex-col gap-2 rounded-xl border p-3.5">
              <div className="flex items-center gap-2 text-[14px] font-semibold">
                <span className="inline-flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <LogIn className="size-4" />
                </span>
                {t('team.cx.join')}
              </div>
              <p className="text-[12.5px] text-muted-foreground">{t('team.cx.joinDesc')}</p>
              <Input value={paste} onChange={(e) => setPaste(e.target.value)} placeholder="https://ui.example.com#…" className="h-8 font-mono text-[11.5px]" />
              {joinError && <p className="text-[12px] text-destructive">{joinError}</p>}
              <Button size="sm" variant="outline" className="mt-auto" disabled={!paste.includes('#')} loading={join.isPending} onClick={doJoin}>
                {t('team.cx.joinBtn')}
              </Button>
            </div>
          </div>
        )}
        <Callout tone="warning" icon={ShieldAlert} title={t('team.cx.trustTitle')}>
          {t('team.cx.trust')}
        </Callout>
        {c?.ok && <p className="text-[11.5px] text-muted-foreground">{t('team.cx.needDomain')}</p>}
      </DialogContent>
    </Dialog>
  )
}

