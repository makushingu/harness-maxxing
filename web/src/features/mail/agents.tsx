// The agents on the E-mail page: what they did with a message ("seen by", kept in mail.db, never written to the
// mailbox), the check-shield of a sender the provider verified, and the messages they wrote that wait for the
// owner's OK (the outbox, also "to do" events of the Notifications).
import * as React from 'react'
import { Link } from 'react-router'
import { ChevronDown, ChevronRight, Paperclip, Pencil, Send, ShieldCheck, X } from 'lucide-react'
import { Button, Sensitive, Tooltip } from '@/components/ui'
import { AgentAvatarIcon } from '@/features/agents/Avatar'
import { fmtBytes } from '@/lib/format'
import { AGENT_PATH_RE, useMailOutbox, useMailOutboxAct } from '@/lib/queries'
import type { MailOutboxItem, MailRight, MailSeenBy } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useLang, useT, type TFn, type TKey } from '@/i18n'
import { shortDate } from './shared'

const WHAT: Record<string, TKey> = {
  seen: 'mail.seen.w.seen',
  read: 'mail.seen.w.read',
  draft: 'mail.seen.w.draft',
  filed: 'mail.seen.w.filed',
  archived: 'mail.seen.w.archived',
  'moved to the trash': 'mail.seen.w.trash',
  'marked as junk': 'mail.seen.w.junk',
  'moved to the inbox': 'mail.seen.w.inbox',
  'marked read': 'mail.seen.w.markedRead',
  'marked unread': 'mail.seen.w.markedUnread',
  starred: 'mail.seen.w.starred',
  unstarred: 'mail.seen.w.unstarred',
  replied: 'mail.seen.w.replied',
  sent: 'mail.seen.w.sent',
}
// the details the server writes in English; anything else (a folder name) is shown as it is
const DETAIL: Record<string, TKey> = {
  'draft ready': 'mail.seen.d.draftReady',
  "waiting for the owner's OK": 'mail.seen.d.waiting',
  'changed by the owner': 'mail.seen.d.changed',
}

/** "read 14:02", "filed in Invoices 14:03", "draft ready 9 oct." */
export function seenText(t: TFn, lang: string, e: MailSeenBy): string {
  const key = WHAT[e.what]
  const when = shortDate(e.at, lang)
  if (e.what === 'filed' && e.detail) return `${t('mail.seen.filedIn', { folder: e.detail })} ${when}`
  if (!key) return `${e.what} ${when}`
  let what = t(key)
  if (e.what === 'draft' || e.what === 'sent' || e.what === 'replied') {
    const d = DETAIL[e.detail] ? t(DETAIL[e.detail]) : e.detail.startsWith('approved') ? t('mail.seen.d.approved') : ''
    if (d) what = `${what} (${d})`
  }
  return `${what} ${when}`
}

/** The agents that did something with a message, each once (its last action), in order of their first one. */
function byAgent(list: MailSeenBy[]): { agent: string; name: string; avatar: MailSeenBy['avatar']; events: MailSeenBy[] }[] {
  const out = new Map<string, { agent: string; name: string; avatar: MailSeenBy['avatar']; events: MailSeenBy[] }>()
  for (const e of list) {
    const g = out.get(e.agent) || { agent: e.agent, name: e.name, avatar: e.avatar, events: [] }
    g.events.push(e)
    out.set(e.agent, g)
  }
  return [...out.values()]
}

/** Tiny faces of the agents in a row of the list; the tooltip tells what each did and when. */
export function SeenByAvatars({ list, className }: { list?: MailSeenBy[]; className?: string }) {
  const t = useT()
  const lang = useLang()
  if (!list?.length) return null
  const groups = byAgent(list)
  const tip = (
    <div className="grid gap-0.5">
      {groups.map((g) => {
        const last = g.events[g.events.length - 1]
        return <span key={g.agent}>{t('mail.seen.by', { name: g.name, what: seenText(t, lang, last) })}</span>
      })}
    </div>
  )
  return (
    <Tooltip content={tip}>
      <span className={cn('flex shrink-0 items-center -space-x-1', className)} aria-label={groups.map((g) => g.name).join(', ')} data-testid="mail-seen-by">
        {groups.slice(0, 3).map((g) => (
          <AgentAvatarIcon key={g.agent} avatar={g.avatar} size={16} className="rounded-sm ring-1 ring-background" />
        ))}
        {groups.length > 3 && <span className="pl-1.5 text-[10px] text-muted-foreground">+{groups.length - 3}</span>}
      </span>
    </Tooltip>
  )
}

/** Under the header of an open message: "Writer · read 14:02 · filed in Invoices 14:03", one line per agent. */
export function SeenByLine({ list }: { list?: MailSeenBy[] }) {
  const t = useT()
  const lang = useLang()
  if (!list?.length) return null
  return (
    <div className="grid gap-1 rounded-lg bg-muted/50 px-3 py-2 text-xs text-muted-foreground" data-testid="mail-seen-line">
      {byAgent(list).map((g) => {
        const m = AGENT_PATH_RE.exec(g.agent)
        const name = <Sensitive length={6}>{g.name}</Sensitive>
        return (
          <div key={g.agent} className="flex min-w-0 items-center gap-1.5">
            <AgentAvatarIcon avatar={g.avatar} size={16} />
            {m && g.events[0].exists ? (
              <Link to={`/agents/${m[1]}/${m[2]}/${m[3]}`} className="shrink-0 font-medium text-foreground hover:underline">
                {name}
              </Link>
            ) : (
              <span className="shrink-0 font-medium text-foreground">{name}</span>
            )}
            <span className="min-w-0 truncate">
              {g.events.map((e) => ` · ${seenText(t, lang, e)}`).join('')}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/** The provider checked the sender's domain (DKIM / SPF / DMARC). Nothing shown otherwise: most mail is fine. */
export function Verified({ on, className }: { on?: boolean; className?: string }) {
  const t = useT()
  if (!on) return null
  return (
    <Tooltip content={t('mail.seen.verified')}>
      <ShieldCheck className={cn('size-3.5 shrink-0 text-success', className)} aria-label={t('mail.seen.verified')} />
    </Tooltip>
  )
}

const RIGHTS: MailRight[] = ['read', 'draft', 'move', 'mark', 'send']
/** "Read, write drafts, send" */
export function rightsText(t: TFn, rights: MailRight[]): string {
  if (!rights.length) return t('mail.agents.noRight')
  return RIGHTS.filter((r) => rights.includes(r)).map((r) => t(`mail.agents.right.${r}` as TKey)).join(', ')
}

/** On top of the list: "Writer wants to send 1 e-mail", unfolding to each message with Send / Edit / Refuse. */
export function OutboxBanner({ acc, onEdit }: { acc: string; onEdit: (draft: { folder: string; uid: number }) => void }) {
  const t = useT()
  const { data } = useMailOutbox(acc)
  const [open, setOpen] = React.useState(false)
  const items = data || []
  if (!items.length) return null
  const names = [...new Set(items.map((x) => x.agent_name))]
  const title = names.length === 1 ? t('mail.outbox.title', { name: names[0], count: items.length }) : t('mail.outbox.titleMany', { count: items.length })
  return (
    <div className="shrink-0 border-b bg-warning/10" data-testid="mail-outbox">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] hover:bg-warning/10">
        {items[0].avatar ? <AgentAvatarIcon avatar={items[0].avatar} size={20} /> : <Send className="size-4 text-warning" />}
        <span className="min-w-0 flex-1 truncate font-medium">{title}</span>
        {open ? <ChevronDown className="size-4 shrink-0 text-muted-foreground" /> : <ChevronRight className="size-4 shrink-0 text-muted-foreground" />}
      </button>
      {open && (
        <ul className="grid max-h-[50vh] grid-cols-[minmax(0,1fr)] gap-2 overflow-y-auto px-3 pb-3">
          {items.map((x) => (
            <OutboxItem key={x.id} item={x} onEdit={onEdit} />
          ))}
        </ul>
      )}
    </div>
  )
}

function OutboxItem({ item: x, onEdit }: { item: MailOutboxItem; onEdit: (draft: { folder: string; uid: number }) => void }) {
  const t = useT()
  const lang = useLang()
  const act = useMailOutboxAct()
  const busy = act.isPending ? act.variables?.action : null
  const to = [...x.to, ...x.cc]
  // a long text shows its first lines: it is sent only once read in full (an agent may hide orders after them)
  const long = x.text.length > 280 || x.text.split('\n').length > 3
  const [all, setAll] = React.useState(false)
  const unread = x.text_cut || (long && !all)
  return (
    <li className="grid grid-cols-[minmax(0,1fr)] gap-1.5 rounded-lg border bg-card p-2.5 text-[13px]" data-testid="mail-outbox-item">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <AgentAvatarIcon avatar={x.avatar} size={16} />
        <span className="min-w-0 flex-1 truncate">
          <Sensitive length={6}>{x.agent_name}</Sensitive> · {shortDate(x.at, lang)}
        </span>
      </div>
      <div className="grid gap-0.5">
        <span className="truncate">
          <span className="text-muted-foreground">{t('mail.to')} </span>
          <Sensitive length={10}>{to.join(', ')}</Sensitive>
        </span>
        {!!x.bcc?.length && (
          <span className="truncate" data-testid="mail-outbox-bcc">
            <span className="text-muted-foreground">{t('mail.compose.bcc')} </span>
            <Sensitive length={10}>{x.bcc.join(', ')}</Sensitive>
          </span>
        )}
        <span className="truncate font-medium">
          <Sensitive length={10}>{x.subject || t('mail.noSubject')}</Sensitive>
        </span>
        {x.text && (
          <p className={cn('text-xs break-words whitespace-pre-line text-muted-foreground', !all && 'line-clamp-3')}>
            <Sensitive block>{x.text}</Sensitive>
          </p>
        )}
        {long && !all && (
          <button type="button" className="justify-self-start text-xs text-primary hover:underline" onClick={() => setAll(true)} data-testid="mail-outbox-all">
            {t('mail.outbox.showAll')}
          </button>
        )}
      </div>
      {!!x.files.length && (
        <div className="flex flex-wrap gap-1.5">
          {x.files.map((f) => (
            <span key={f.name} className="flex max-w-56 items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px]">
              <Paperclip className="size-3 shrink-0 text-muted-foreground" />
              <span className="truncate">
                <Sensitive length={6}>{f.name}</Sensitive>
              </span>
              <span className="shrink-0 text-muted-foreground">{fmtBytes(f.size)}</span>
            </span>
          ))}
        </div>
      )}
      {x.why && (
        <p className="text-xs break-words text-muted-foreground">
          {t('mail.outbox.why')} <Sensitive length={10}>{x.why}</Sensitive>
        </p>
      )}
      {x.note && <p className="text-xs text-destructive">{x.note}</p>}
      <div className="flex flex-wrap gap-1.5 pt-0.5">
        <Tooltip content={unread ? t(x.text_cut ? 'mail.outbox.tooLong' : 'mail.outbox.readFirst') : null}>
          <span>
            <Button size="sm" loading={busy === 'send'} disabled={!!busy || unread} onClick={() => act.mutate({ id: x.id, action: 'send' })} data-testid="mail-outbox-send">
              <Send /> {t('mail.compose.send')}
            </Button>
          </span>
        </Tooltip>
        {x.draft && (
          <Button size="sm" variant="outline" disabled={!!busy} onClick={() => onEdit(x.draft!)}>
            <Pencil /> {t('common.edit')}
          </Button>
        )}
        <Button size="sm" variant="ghost" loading={busy === 'deny'} disabled={!!busy} onClick={() => act.mutate({ id: x.id, action: 'deny' })} data-testid="mail-outbox-deny">
          <X /> {t('mail.outbox.refuse')}
        </Button>
      </div>
    </li>
  )
}
