// Feature page "E-mail" (/mail, Settings -> Features -> mail_page): any IMAP/SMTP mailbox. The mailboxes (and the folders
// of the one open) are the second-level sidebar (MailboxNav in PageList; touch: the left drawer); the page shows
// messages | message (the list's width dragged by its edge), one pane at a time when narrow. The account, folder and message shown are in the URL
// (?a=<account>&f=<folder>&m=<uid>), so Claude can link to a message; ?a=* = "All mailboxes" (the cache of the last
// checks). The Notifications link to a draft an agent wrote as ?account=<id>&folder=<f>&draft=<uid>: it opens in Compose.
import * as React from 'react'
import { Link, useSearchParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import {
  Archive, Flag, FolderPlus, Inbox, Mail, MailOpen, MoreHorizontal, Paperclip, Pencil, Plus, RefreshCw, Reply, Search, Settings2, SquarePen, Trash2, X,
} from 'lucide-react'
import {
  Button, Checkbox, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger, EmptyState, Input, Segmented,
  Sensitive, Skeleton, Tooltip, useContextMenu, useMask, WithContextMenu,
} from '@/components/ui'
import { PageHeader } from '@/components/shell/Page'
import { PageList } from '@/components/shell/PageList'
import { ResizeEdge } from '@/components/shell/ResizeEdge'
import { keepPageListOpen } from '@/components/shell/TouchNav'
import { errorMessage } from '@/lib/api'
import { toast } from '@/components/ui/toast'
import type { MailAccount, MailAction, MailComposeMode, MailFolder, MailMessage, MailSummary } from '@/lib/types'
import {
  fetchMailCompose, mailKeys, useMailAccounts, useMailAction, useMailCreateFolder, useMailDeleteFolder, useMailFolders, useMailList, useMailRefresh, useMailRenameFolder,
  useSettings,
} from '@/lib/queries'
import { fmtRelative } from '@/lib/format'
import { cn, store } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { AccountDialog } from './AccountDialog'
import { Compose, signatureBlock, type ComposeInit } from './Compose'
import { MessageView } from './MessageView'
import { AllMailboxes } from './AllMailboxes'
import { OutboxBanner, SeenByAvatars, Verified } from './agents'
import { clean, depth, folderIcon, folderLabel, leaf, shortDate, who } from './shared'
import { composeHeldElsewhere, loadCompose, loadFiles, replyOf } from './localDraft'

/** The message list's width (px) beside the reader: its bounds and where it is kept. */
const LIST_MIN = 280
const READER_MIN = 360
const LIST_W_KEY = 'mx.mail.listWidth'

/** `a` of "All mailboxes" in the URL (a mailbox id always has a dash, never a star). */
export const ALL = '*'

type Filter = 'all' | 'unread' | 'flagged'

/** The folders of a mailbox (rename / delete a folder of your own from its ⋯; `newName` set = the New folder field). */
function FolderList({ acc, folders, loading, error, current, onPick, newName, setNewName, className }: {
  acc: MailAccount
  folders: MailFolder[]
  loading: boolean
  error: unknown
  current: string
  onPick: (f: string) => void
  newName: string | null
  setNewName: (v: string | null) => void
  className?: string
}) {
  const t = useT()
  const mask = useMask()
  const create = useMailCreateFolder(acc.id)
  const rename = useMailRenameFolder(acc.id)
  const del = useMailDeleteFolder(acc.id)
  const [renaming, setRenaming] = React.useState<{ from: string; to: string } | null>(null)
  return (
    <nav className={className} aria-label={t('mail.folders')}>
      {loading ? (
        <div className="grid gap-1.5 p-1">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-7" />
          ))}
        </div>
      ) : error ? (
        <p className="p-2 text-xs text-destructive">{errorMessage(error)}</p>
      ) : (
        <ul className="grid grid-cols-[minmax(0,1fr)] gap-px">
          {folders.map((f) => {
            const Icon = folderIcon(f)
            const active = f.name === current
            if (renaming?.from === f.name) {
              return (
                <li key={f.name}>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault()
                      if (renaming.to.trim()) rename.mutate({ name: f.name, new_name: renaming.to.trim() }, { onSuccess: (r) => (active && onPick(r.name), setRenaming(null)) })
                    }}
                  >
                    <Input autoFocus className="h-8 text-[13px]" value={renaming.to} onChange={(e) => setRenaming({ ...renaming, to: e.target.value })} onBlur={() => setRenaming(null)} />
                  </form>
                </li>
              )
            }
            const folderItems = !f.role && (
              <>
                <DropdownMenuItem onSelect={() => setRenaming({ from: f.name, to: leaf(f.name, f.delim) })}>
                  <Pencil /> {t('mail.folder.rename')}
                </DropdownMenuItem>
                <DropdownMenuItem destructive onSelect={() => window.confirm(t('mail.folder.deleteConfirm', { name: leaf(f.name, f.delim) })) && del.mutate(f.name, { onSuccess: () => active && onPick('INBOX') })}>
                  <Trash2 /> {t('mail.folder.delete')}
                </DropdownMenuItem>
              </>
            )
            return (
              <WithContextMenu key={f.name} items={folderItems}>
                <li className="group relative">
                  <button
                    type="button"
                    onClick={() => onPick(f.name)}
                    className={cn(
                      'flex h-8 w-full items-center gap-2 rounded-md pr-2 text-left text-[13px] transition-colors pointer-coarse:h-10',
                      active ? 'bg-accent font-medium text-accent-foreground' : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
                    )}
                    style={{ paddingLeft: 8 + depth(f) * 12 }}
                    title={f.role ? f.name : mask(f.name)}
                  >
                    <Icon className="size-4 shrink-0" />
                    <span className="min-w-0 flex-1 truncate">{f.role ? folderLabel(f, t) : <Sensitive length={6}>{folderLabel(f, t)}</Sensitive>}</span>
                    {!!f.unread && f.role !== 'sent' && f.role !== 'trash' && <span className="text-xs font-semibold text-primary tabular-nums">{f.unread}</span>}
                  </button>
                  {!f.role && (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button
                          type="button"
                          className="absolute top-1 right-1 hidden size-6 items-center justify-center rounded text-muted-foreground group-hover:flex hover:bg-background data-[state=open]:flex"
                          aria-label={t('mail.folder.menu')}
                        >
                          <MoreHorizontal className="size-3.5" />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">{folderItems}</DropdownMenuContent>
                    </DropdownMenu>
                  )}
                </li>
              </WithContextMenu>
            )
          })}
          {newName !== null && (
            <li>
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  if (newName.trim()) create.mutate({ name: newName.trim() }, { onSuccess: (r) => (setNewName(null), onPick(r.name)) })
                }}
              >
                <Input autoFocus className="h-8 text-[13px]" placeholder={t('mail.folder.newPh')} value={newName} onChange={(e) => setNewName(e.target.value)} onBlur={() => !newName.trim() && setNewName(null)} />
              </form>
            </li>
          )}
        </ul>
      )}
    </nav>
  )
}

/** The second-level sidebar of the page (touch: the left drawer). All mailboxes (with two or more), each mailbox, the folders of the one
 *  open under it (its ⋯: edit it, new folder), Add a mailbox at the bottom. */
function MailboxNav({ acc, all, accounts, folders, loading, error, current, onPick, onAccount, onAddAccount, onEditAccount }: {
  acc: MailAccount
  all: boolean
  accounts: MailAccount[]
  folders: MailFolder[]
  loading: boolean
  error: unknown
  current: string
  onPick: (f: string) => void
  onAccount: (id: string) => void
  onAddAccount: () => void
  onEditAccount: () => void
}) {
  const t = useT()
  const mask = useMask()
  const [newName, setNewName] = React.useState<string | null>(null)
  const row = (active: boolean) =>
    cn(
      'flex h-9 w-full min-w-0 items-center gap-2.5 rounded-md px-2.5 text-left text-[13px] transition-colors pointer-coarse:h-10',
      active ? 'bg-accent font-medium text-accent-foreground' : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
    )
  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="mail-boxes">
      <nav className="min-h-0 flex-1 overflow-y-auto p-2" aria-label={t('mail.account')}>
        {accounts.length > 1 && (
          <button type="button" className={row(all)} onClick={() => onAccount(ALL)} aria-current={all || undefined}>
            <Inbox className="size-4 shrink-0" />
            <span className="min-w-0 flex-1 truncate">{t('mail.all.title')}</span>
          </button>
        )}
        {accounts.map((a) => {
          const open = !all && a.id === acc.id
          const accItems = open && (
            <>
              <DropdownMenuItem onSelect={onEditAccount}>
                <Settings2 /> {t('mail.acc.edit')}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setNewName('')}>
                <FolderPlus /> {t('mail.folder.new')}
              </DropdownMenuItem>
            </>
          )
          return (
            <div key={a.id} className="mt-0.5">
              <WithContextMenu items={accItems}>
                <div className="group relative">
                  <button type="button" className={cn(row(open), 'pr-9')} onClick={() => onAccount(a.id)} aria-current={open || undefined} title={mask(a.address, 8)} data-testid="mail-box">
                    <Mail className="size-4 shrink-0" />
                    <span className="min-w-0 flex-1 truncate">
                      <Sensitive length={8}>{a.label || a.address}</Sensitive>
                    </span>
                  </button>
                  {open && (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button
                          type="button"
                          className="absolute top-1.5 right-1.5 flex size-6 items-center justify-center rounded text-muted-foreground opacity-0 group-hover:opacity-100 hover:bg-background focus-visible:opacity-100 data-[state=open]:opacity-100 pointer-coarse:opacity-100"
                          aria-label={t('mail.accountMenu')}
                        >
                          <MoreHorizontal className="size-3.5" />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">{accItems}</DropdownMenuContent>
                    </DropdownMenu>
                  )}
                </div>
              </WithContextMenu>
              {open && (
                <FolderList
                  className="mt-0.5 mb-2 ml-3.5 border-l pl-1.5"
                  acc={acc}
                  folders={folders}
                  loading={loading}
                  error={error}
                  current={current}
                  onPick={onPick}
                  newName={newName}
                  setNewName={setNewName}
                />
              )}
            </div>
          )
        })}
      </nav>
      <div className="shrink-0 border-t p-2">
        <button type="button" className={row(false)} onClick={onAddAccount} data-testid="mail-add-box">
          <Plus className="size-4 shrink-0" />
          <span className="min-w-0 flex-1 truncate">{t('mail.acc.addTitle')}</span>
        </button>
      </div>
    </div>
  )
}

function Row({ m, selected, checked, onOpen, onCheck, menu }: { m: MailSummary; selected: boolean; checked: boolean; onOpen: () => void; onCheck: (v: boolean) => void; menu: () => React.ReactNode }) {
  const lang = useLang()
  const t = useT()
  const ctx = useContextMenu()
  return (
    <li
      {...ctx.props}
      className={cn(
        'group relative flex cursor-pointer items-start gap-2.5 border-b px-3 py-2.5 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
        selected ? 'bg-accent' : checked ? 'bg-primary/5' : 'hover:bg-accent/40',
      )}
      onClick={onOpen}
      // the row opens with Enter / Space too (its checkbox keeps its own keys)
      tabIndex={0}
      aria-current={selected || undefined}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget || (e.key !== 'Enter' && e.key !== ' ')) return
        e.preventDefault()
        onOpen()
      }}
      data-testid="mail-row"
    >
      {!m.seen && <span className="absolute top-4 left-1 size-1.5 rounded-full bg-primary" aria-label={t('mail.unread')} />}
      <span onClick={(e) => e.stopPropagation()} className="pt-0.5">
        <Checkbox checked={checked} onCheckedChange={(v) => onCheck(!!v)} aria-label={t('mail.select')} className={cn(!checked && 'opacity-40 group-hover:opacity-100')} />
      </span>
      <div className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)] gap-0.5">
        <div className="flex items-baseline gap-2">
          <span className={cn('min-w-0 truncate text-[13px]', !m.seen ? 'font-semibold' : 'text-foreground/90')}>
            <Sensitive length={8}>{who(m.from) ? <bdi>{who(m.from)}</bdi> : t('mail.unknownSender')}</Sensitive>
          </span>
          <Verified on={m.from_verified} className="self-center" />
          <span className="flex-1" />
          <SeenByAvatars list={m.seen_by} className="self-center" />
          {m.answered && <Reply className="size-3 shrink-0 text-muted-foreground" aria-label={t('mail.answered')} />}
          {m.flagged && <Flag className="size-3 shrink-0 fill-amber-400 text-amber-500" />}
          {m.attachments && <Paperclip className="size-3 shrink-0 text-muted-foreground" />}
          <span className="shrink-0 text-[11px] text-muted-foreground tabular-nums">{shortDate(m.date, lang)}</span>
        </div>
        <span className={cn('truncate text-[13px]', !m.seen ? 'font-medium' : 'text-muted-foreground')}>
          <Sensitive length={10}>{m.subject ? <bdi>{clean(m.subject)}</bdi> : t('mail.noSubject')}</Sensitive>
        </span>
      </div>
      {ctx.open && ctx.menu(menu())}
    </li>
  )
}

/** Width of an element (0 until it is mounted), followed as it changes. */
function useWidth(el: HTMLElement | null): number {
  const [w, setW] = React.useState(() => (typeof window === 'undefined' ? 0 : window.innerWidth))
  React.useLayoutEffect(() => {
    if (!el) return
    setW(el.getBoundingClientRect().width)
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [el])
  return w
}

function Setup({ onAdd, off }: { onAdd: () => void; off?: boolean }) {
  const t = useT()
  if (off) {
    return (
      <EmptyState
        icon={Mail}
        title={t('mail.off')}
        description={t('mail.offDesc')}
        action={
          <Button asChild variant="outline">
            <Link to="/settings/features">{t('mail.openSettings')}</Link>
          </Button>
        }
      />
    )
  }
  return <EmptyState icon={Mail} title={t('mail.empty')} description={t('mail.emptyDesc')} action={<Button onClick={onAdd}><Plus /> {t('mail.acc.addTitle')}</Button>} />
}

export default function MailPage() {
  const t = useT()
  const lang = useLang()
  const qc = useQueryClient()
  const { data: settings } = useSettings()
  const on = !!settings?.mail_page
  const accounts = useMailAccounts(on)
  const [params, setParams] = useSearchParams()
  const list = accounts.data || []
  const all = params.get('a') === ALL && list.length > 1
  const acc = list.find((a) => a.id === params.get('a')) || list[0] || null
  const folder = params.get('f') || 'INBOX'
  const uid = Number(params.get('m')) || null
  const [q, setQ] = React.useState('')
  const [query, setQuery] = React.useState('')
  const [filter, setFilter] = React.useState<Filter>('all')
  const [page, setPage] = React.useState(0)
  const [checked, setChecked] = React.useState<Set<number>>(new Set())
  const [dialog, setDialog] = React.useState<'add' | 'edit' | null>(null)
  const [compose, setCompose] = React.useState<ComposeInit | null>(null)
  const mask = useMask()
  // the panes follow the width the page really has (the sidebar open or not), not the window: three panes leave
  // the reader at least ~26rem, else one pane beside the folders, else one pane at a time
  const [box, setBox] = React.useState<HTMLDivElement | null>(null)
  const width = useWidth(box)
  // the folders are in the second-level sidebar: messages | message from 760 px, one pane at a time below
  const wide = width >= 760
  // the list's width beside the reader: dragged by its right edge, kept in this browser (double-click: the default)
  const listRef = React.useRef<HTMLElement>(null)
  const [savedW, setSavedW] = React.useState(() => Number(store.get(LIST_W_KEY)) || 0)
  const saveListW = (w: number | null) => {
    if (w) store.set(LIST_W_KEY, String(Math.round(w)))
    else store.remove(LIST_W_KEY)
    setSavedW(w ? Math.round(w) : 0)
  }
  const listW = Math.max(LIST_MIN, Math.min(savedW || (width >= 1200 ? 416 : 352), width - READER_MIN))

  const folders = useMailFolders(all ? null : acc?.id || null)
  const msgs = useMailList(all ? null : acc?.id || null, folder, page, query, filter)
  const check = useMailRefresh()
  const action = useMailAction(acc?.id || '')
  const current = folders.data?.find((f) => f.name === folder)

  const go = (next: { a?: string; f?: string; m?: number | null }) => {
    const p = new URLSearchParams(params)
    if (next.a !== undefined) p.set('a', next.a)
    if (next.f !== undefined) p.set('f', next.f)
    if (next.m !== undefined) (next.m ? p.set('m', String(next.m)) : p.delete('m'))
    setParams(p, { replace: next.m === undefined })
  }
  React.useEffect(() => {
    setPage(0)
    setChecked(new Set())
  }, [acc?.id, folder, query, filter])
  // another page, or mails gone from the list after a refresh: nothing hidden stays selected for a bulk action
  React.useEffect(() => setChecked(new Set()), [page])
  const rows = React.useMemo(() => msgs.data?.messages || [], [msgs.data])
  React.useEffect(() => {
    setChecked((s) => {
      if (!s.size) return s
      const shown = new Set(rows.map((r) => r.uid))
      const n = new Set([...s].filter((u) => shown.has(u)))
      return n.size === s.size ? s : n
    })
  }, [rows])

  const total = msgs.data?.total || 0
  const pages = Math.max(1, Math.ceil(total / (msgs.data?.size || 50)))

  const run = (uids: number[], a: MailAction, target?: string) => {
    if (!acc || !uids.length) return
    if (a === 'delete' && !window.confirm(t('mail.act.deleteConfirm', { count: uids.length }))) return
    // the open message leaves the list: open the next one (or none)
    const leaves = a === 'move' || a === 'archive' || a === 'trash' || a === 'junk' || a === 'inbox' || a === 'delete'
    if (leaves && uid && uids.includes(uid)) {
      const i = rows.findIndex((r) => r.uid === uid)
      const next = rows.slice(i + 1).find((r) => !uids.includes(r.uid)) || rows.slice(0, i).reverse().find((r) => !uids.includes(r.uid))
      go({ m: wide && next ? next.uid : null })
    }
    action.mutate({ folder, uids, action: a, target }, {
      onSuccess: () => {
        setChecked(new Set())
        // a flag changed: patch the message already loaded. Loading it again would mark it read on the server,
        // which undid "Mark as unread" at once.
        if (!leaves) {
          const patch: Partial<MailMessage> | null =
            a === 'seen' ? { seen: true } : a === 'unseen' ? { seen: false } : a === 'flag' ? { flagged: true } : a === 'unflag' ? { flagged: false } : null
          for (const u of uids) {
            if (patch) qc.setQueryData<MailMessage>(mailKeys.message(acc.id, folder, u), (m) => (m ? { ...m, ...patch } : m))
            else qc.invalidateQueries({ queryKey: mailKeys.message(acc.id, folder, u) })
          }
        }
      },
    })
  }

  const newMessage = () => acc && setCompose({ mode: 'new', acc: acc.id, to: [], cc: [], bcc: [], subject: '', text: signatureBlock(acc) })
  const openCompose = async (mode: MailComposeMode, f: string, u: number, accId = acc?.id) => {
    if (!accId) return
    try {
      const c = await fetchMailCompose(accId, mode, f, u)
      setCompose({
        mode,
        acc: accId,
        to: c.to,
        cc: c.cc,
        bcc: c.bcc || [],
        subject: c.subject,
        text: c.text,
        in_reply_to: c.in_reply_to,
        references: c.references,
        // a reply saved as a draft: the message it answers was kept in this browser (localDraft.ts)
        reply: mode === 'reply' || mode === 'replyall' ? { folder: f, uid: u } : mode === 'draft' ? replyOf(accId, { folder: f, uid: u }) : undefined,
        source: c.attachments.length ? { folder: f, uid: u, attachments: c.attachments } : undefined,
        draft: mode === 'draft' ? { folder: f, uid: u } : undefined,
      })
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  // opening an unread message marks it read on the server: refresh the counts once it is loaded
  const openMsg = (m: MailSummary) => {
    if (current?.role === 'drafts') {
      void openCompose('draft', folder, m.uid)
      return
    }
    go({ m: m.uid })
    // already loaded once (then marked unread): it is not loaded again, so mark it read here
    if (!m.seen && acc && qc.getQueryData(mailKeys.message(acc.id, folder, m.uid))) {
      qc.setQueryData<MailMessage>(mailKeys.message(acc.id, folder, m.uid), (x) => (x ? { ...x, seen: true } : x))
      action.mutate({ folder, uids: [m.uid], action: 'seen' })
      return
    }
    if (!m.seen && acc) {
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: mailKeys.folders(acc.id) })
        qc.invalidateQueries({ queryKey: mailKeys.list(acc.id) })
      }, 1200)
    }
  }

  // The link of a Notification (?account=&folder=&draft=): that mailbox and folder, the draft open in Compose.
  const linked = params.get('account')
  const restoring = React.useRef(false)
  React.useEffect(() => {
    if (!linked || !accounts.data) return
    const f = params.get('folder') || 'INBOX'
    const d = Number(params.get('draft')) || 0
    const p = new URLSearchParams(params)
    for (const k of ['account', 'folder', 'draft']) p.delete(k)
    if (accounts.data.some((a) => a.id === linked)) {
      p.set('a', linked)
      p.set('f', f)
      p.delete('m')
      if (d) {
        restoring.current = true
        void openCompose('draft', f, d, linked)
      }
    }
    setParams(p, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linked, accounts.data])

  // A message being written when the page was left (reload, Back, a closed tab): it opens again, as it was.
  React.useEffect(() => {
    // a Notification link opens its own draft first: the kept message waits for the next visit
    if (restoring.current || !accounts.data || compose || linked) return
    restoring.current = true
    const c = loadCompose()
    // still being written in another tab: opening it here too could send it twice
    if (!c || !accounts.data.some((a) => a.id === c.acc) || composeHeldElsewhere()) return
    void loadFiles().then((files) => {
      const { at: _at, showCc, kept, files: _n, ...init } = c
      // a copy kept before `replyAcc` existed cannot tell which mailbox its reply is in: no "answered" flag then
      if (!init.replyAcc) init.reply = undefined
      setCompose({ ...init, restored: { showCc, kept, files } })
      toast.info(t('mail.compose.restored'))
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accounts.data, linked])

  // Infra -> E-mail "Add to the E-mail page" (?add=<address>): the add dialog, prefilled
  const [addAddress, setAddAddress] = React.useState('')
  const addParam = params.get('add')
  React.useEffect(() => {
    if (!addParam) return
    setAddAddress(addParam)
    setDialog('add')
    const p = new URLSearchParams(params)
    p.delete('add')
    setParams(p, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addParam])

  // Refresh = a check of the mailbox now (new mail starts its agents), then the list again.
  const refresh = () => {
    check.mutate(all ? undefined : acc?.id, {
      onSuccess: (r) => {
        const bad = r.find((x) => !x.ok)
        if (bad) toast.error(t('mail.check.failed', { error: bad.error || '' }))
      },
    })
    if (!acc || all) return
    qc.invalidateQueries({ queryKey: mailKeys.list(acc.id) })
    qc.invalidateQueries({ queryKey: mailKeys.folders(acc.id) })
  }
  const last = all ? null : acc?.last_check
  const checkedTip = last ? (last.ok ? t('mail.check.at', { when: fmtRelative(last.at, lang) }) : t('mail.check.failed', { error: last.error })) : t('mail.check.never')

  const header = (
    <PageHeader
      title={t('mail.title')}
      description={all ? t('mail.all.title') : acc ? <Sensitive length={10}>{acc.address}</Sensitive> : t('mail.desc')}
      actions={
        acc && (
          <>
            <Tooltip content={checkedTip}>
              <Button variant="ghost" size="icon" onClick={refresh} aria-label={t('mail.check.now')} data-testid="mail-refresh">
                <RefreshCw className={cn((check.isPending || msgs.isFetching) && 'animate-spin')} />
              </Button>
            </Tooltip>
            <Button size="sm" onClick={newMessage} disabled={all} data-testid="mail-new">
              <SquarePen /> <span className="max-sm:sr-only">{t('mail.compose.new')}</span>
            </Button>
          </>
        )
      }
    />
  )

  if (settings && !on) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        {header}
        <Setup off onAdd={() => {}} />
      </div>
    )
  }
  if (accounts.isLoading || !settings) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        {header}
        <div className="grid gap-2 p-6">
          <Skeleton className="h-8 w-1/3" />
          <Skeleton className="h-64" />
        </div>
      </div>
    )
  }
  if (accounts.error && !accounts.data) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        {header}
        <EmptyState
          tone="error"
          title={t('mail.accountsError')}
          description={errorMessage(accounts.error)}
          action={<Button variant="outline" onClick={() => accounts.refetch()} disabled={accounts.isFetching}>{t('common.retry')}</Button>}
        />
      </div>
    )
  }
  if (!acc) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        {header}
        <Setup onAdd={() => setDialog('add')} />
        <AccountDialog open={dialog === 'add'} address={addAddress} onOpenChange={(o) => { setDialog(o ? 'add' : null); if (!o) setAddAddress('') }} onSaved={(a) => go({ a: a.id, f: 'INBOX', m: null })} />
      </div>
    )
  }

  const boxNav = (
    <MailboxNav
      acc={acc}
      all={all}
      accounts={list}
      folders={folders.data || []}
      loading={folders.isLoading}
      error={folders.error}
      current={folder}
      onPick={(f) => go({ f, m: null })}
      onAccount={(a) => (keepPageListOpen(), go({ a, f: 'INBOX', m: null }))}
      onAddAccount={() => setDialog('add')}
      onEditAccount={() => setDialog('edit')}
    />
  )
  const sel = [...checked]
  // The "..." of a selection and the right click on a message (its own actions, or the selection's when it is checked).
  const moreItems = (uids: number[]) => (
    <>
      <DropdownMenuItem onSelect={() => run(uids, 'unseen')}>{t('mail.act.unread')}</DropdownMenuItem>
      <DropdownMenuItem onSelect={() => run(uids, 'flag')}>{t('mail.act.flag')}</DropdownMenuItem>
      <DropdownMenuItem onSelect={() => run(uids, 'unflag')}>{t('mail.act.unflag')}</DropdownMenuItem>
      <DropdownMenuItem onSelect={() => run(uids, current?.role === 'junk' ? 'inbox' : 'junk')}>{current?.role === 'junk' ? t('mail.act.inbox') : t('mail.act.junk')}</DropdownMenuItem>
      <DropdownMenuSeparator />
      {(folders.data || []).filter((f) => f.name !== folder).map((f) => {
        const Icon = folderIcon(f)
        return (
          <DropdownMenuItem key={f.name} onSelect={() => run(uids, 'move', f.name)}>
            <Icon /> {t('mail.moveTo', { folder: f.role ? folderLabel(f, t) : mask(folderLabel(f, t)) })}
          </DropdownMenuItem>
        )
      })}
    </>
  )
  const rowItems = (m: MailSummary) => {
    const uids = checked.has(m.uid) ? sel : [m.uid]
    const del = current?.role === 'trash' || current?.role === 'junk'
    return (
      <>
        {current?.role !== 'archive' && (
          <DropdownMenuItem onSelect={() => run(uids, 'archive')}>
            <Archive /> {t('mail.act.archive')}
          </DropdownMenuItem>
        )}
        <DropdownMenuItem destructive={del} onSelect={() => run(uids, del ? 'delete' : 'trash')}>
          <Trash2 /> {del ? t('mail.act.deleteForever') : t('mail.act.trash')}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => run(uids, 'seen')}>
          <MailOpen /> {t('mail.act.read')}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {moreItems(uids)}
      </>
    )
  }
  const listPane = (
    <div className="flex min-h-0 flex-1 flex-col">
      <OutboxBanner acc={acc.id} onEdit={(d) => void openCompose('draft', d.folder, d.uid)} />
      {last && !last.ok && (
        <p className="shrink-0 truncate border-b px-3 py-1.5 text-xs text-destructive" title={last.error}>
          {t('mail.check.failed', { error: last.error })}
        </p>
      )}
      <div className="grid shrink-0 gap-2 border-b p-2">
        <form
          className="relative"
          onSubmit={(e) => {
            e.preventDefault()
            setQuery(q.trim())
          }}
        >
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="h-8 pr-8 pl-8 text-[13px]" placeholder={t('mail.searchPh')} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t('mail.search')} />
          {(q || query) && (
            <button type="button" className="absolute top-1/2 right-2 -translate-y-1/2 text-muted-foreground hover:text-foreground before:absolute before:-inset-3 before:content-['']" onClick={() => (setQ(''), setQuery(''))} aria-label={t('mail.clearSearch')}>
              <X className="size-4" />
            </button>
          )}
        </form>
        {sel.length ? (
          <div className="flex h-8 items-center gap-0.5">
            <Checkbox checked={sel.length === rows.length ? true : 'indeterminate'} onCheckedChange={(v) => setChecked(v ? new Set(rows.map((r) => r.uid)) : new Set())} aria-label={t('mail.selectAll')} className="mx-1" />
            <span className="mr-auto text-xs text-muted-foreground">{t('mail.selected', { count: sel.length })}</span>
            {current?.role !== 'archive' && (
              <Button variant="ghost" size="icon-sm" onClick={() => run(sel, 'archive')} aria-label={t('mail.act.archive')} title={t('mail.act.archive')}>
                <Archive />
              </Button>
            )}
            <Button variant="ghost" size="icon-sm" onClick={() => run(sel, current?.role === 'trash' || current?.role === 'junk' ? 'delete' : 'trash')} aria-label={t('mail.act.trash')} title={t('mail.act.trash')}>
              <Trash2 />
            </Button>
            <Button variant="ghost" size="icon-sm" onClick={() => run(sel, 'seen')} aria-label={t('mail.act.read')} title={t('mail.act.read')}>
              <MailOpen />
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon-sm" aria-label={t('mail.more')}>
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="max-h-96 overflow-y-auto">{moreItems(sel)}</DropdownMenuContent>
            </DropdownMenu>
          </div>
        ) : (
          <Segmented
            size="sm"
            value={filter}
            onChange={setFilter}
            aria-label={t('mail.filter')}
            options={[
              { value: 'all', label: t('mail.filter.all') },
              { value: 'unread', label: t('mail.filter.unread') },
              { value: 'flagged', label: t('mail.filter.flagged') },
            ]}
          />
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {msgs.isLoading ? (
          <div className="grid gap-2 p-3">
            {Array.from({ length: 8 }, (_, i) => (
              <Skeleton key={i} className="h-11" />
            ))}
          </div>
        ) : msgs.error ? (
          <EmptyState compact tone="error" title={t('mail.listError')} description={errorMessage(msgs.error)} action={<Button variant="outline" size="sm" onClick={() => msgs.refetch()}>{t('common.retry')}</Button>} />
        ) : !rows.length ? (
          <EmptyState compact icon={Mail} title={query ? t('mail.noResult') : t('mail.noMessage')} />
        ) : (
          <ul>
            {rows.map((m) => (
              <Row
                key={m.uid}
                m={m}
                selected={m.uid === uid}
                checked={checked.has(m.uid)}
                onOpen={() => openMsg(m)}
                menu={() => rowItems(m)}
                onCheck={(v) =>
                  setChecked((s) => {
                    const n = new Set(s)
                    if (v) n.add(m.uid)
                    else n.delete(m.uid)
                    return n
                  })
                }
              />
            ))}
          </ul>
        )}
        {pages > 1 && (
          <div className="flex items-center justify-between gap-2 p-2 text-xs text-muted-foreground">
            <Button variant="ghost" size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
              {t('mail.newer')}
            </Button>
            <span className="tabular-nums">{t('mail.pageOf', { page: page + 1, pages, total })}</span>
            <Button variant="ghost" size="sm" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>
              {t('mail.older')}
            </Button>
          </div>
        )}
      </div>
    </div>
  )
  const reader = uid ? (
    <MessageView
      acc={acc.id}
      folder={folder}
      uid={uid}
      folders={folders.data || []}
      currentRole={current?.role || null}
      onBack={wide ? undefined : () => go({ m: null })}
      onAction={(a, target) => run([uid], a, target)}
      onCompose={(mode) => void openCompose(mode, folder, uid)}
    />
  ) : (
    <EmptyState icon={Mail} title={t('mail.pick')} description={t('mail.pickDesc')} />
  )

  const allPane = (
    <AllMailboxes
      accounts={list}
      onOpen={(r) => {
        go({ a: r.account, f: r.folder, m: r.uid })
      }}
    />
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col" ref={setBox}>
      {header}
      <div className="flex min-h-0 flex-1">
        <PageList id="mail" label={t('nav.mail')}>
          {boxNav}
        </PageList>
        {all ? (
          <section className="flex min-w-0 flex-1 flex-col">{allPane}</section>
        ) : wide ? (
          <>
            <section ref={listRef} className="relative flex shrink-0 flex-col border-r" style={{ width: listW }}>
              {listPane}
              <ResizeEdge side={listRef} min={LIST_MIN} max={Math.max(LIST_MIN, width - READER_MIN)} onWidth={saveListW} />
            </section>
            <section className="flex min-w-0 flex-1 flex-col">{reader}</section>
          </>
        ) : (
          <section className="flex min-w-0 flex-1 flex-col">{uid ? reader : listPane}</section>
        )}
      </div>
      {compose && <Compose key={`${compose.mode}-${compose.reply?.uid || compose.draft?.uid || 'new'}-${compose.restored ? 'r' : ''}`} init={compose} accounts={list} onClose={() => setCompose(null)} />}
      <AccountDialog
        open={!!dialog}
        onOpenChange={(o) => { if (!o) { setDialog(null); setAddAddress('') } }}
        account={dialog === 'edit' ? acc : null}
        address={dialog === 'add' ? addAddress : undefined}
        onSaved={(a) => dialog === 'add' && go({ a: a.id, f: 'INBOX', m: null })}
      />
    </div>
  )
}
