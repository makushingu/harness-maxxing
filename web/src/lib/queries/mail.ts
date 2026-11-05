import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api, request } from '../api'
import type {
  MailAccount, MailAction, MailAll, MailCompose, MailComposeMode, MailDetect, MailDraft, MailFolder, MailList, MailMessage, MailOutboxItem, MailPollMin, MailRefreshResult, MailSent, MailTest,
} from '../types'
import { qk } from './keys'
import { useMut } from './util'

// E-mail page (server/maxxing/mail): live IMAP, nothing cached on the server; the cache here keeps the views fast.
export const mailKeys = {
  all: ['mail'] as const,
  accounts: ['mail', 'accounts'] as const,
  folders: (acc: string) => ['mail', 'folders', acc] as const,
  list: (acc: string) => ['mail', 'list', acc] as const,
  listOf: (acc: string, folder: string, page: number, q: string, filter: string) => ['mail', 'list', acc, folder, page, q, filter] as const,
  message: (acc: string, folder: string, uid: number) => ['mail', 'message', acc, folder, uid] as const,
  lists: ['mail', 'list'] as const,
  foldersAll: ['mail', 'folders'] as const,
  outboxAll: ['mail', 'outbox'] as const,
  outbox: (acc: string) => ['mail', 'outbox', acc] as const,
  everything: ['mail', 'all'] as const,
}

export function useMailAccounts(enabled = true) {
  return useQuery({ queryKey: mailKeys.accounts, queryFn: () => api.get<MailAccount[]>('/api/mail/accounts'), enabled, staleTime: 60_000 })
}
export function useMailFolders(acc: string | null) {
  return useQuery({
    queryKey: mailKeys.folders(acc || ''),
    queryFn: () => api.get<MailFolder[]>(`/api/mail/${acc}/folders`),
    enabled: !!acc,
    staleTime: 30_000,
    refetchInterval: 120_000,
    retry: false,
  })
}
export function useMailList(acc: string | null, folder: string, page: number, q: string, filter: 'all' | 'unread' | 'flagged') {
  return useQuery({
    queryKey: mailKeys.listOf(acc || '', folder, page, q, filter),
    queryFn: () =>
      api.get<MailList>(`/api/mail/${acc}/messages`, { folder, page, q: q || undefined, unread: filter === 'unread' || undefined, flagged: filter === 'flagged' || undefined }),
    enabled: !!acc,
    staleTime: 20_000,
    refetchInterval: 60_000,
    retry: false,
    placeholderData: keepPreviousData,
  })
}
export function useMailMessage(acc: string | null, folder: string, uid: number | null) {
  return useQuery({
    queryKey: mailKeys.message(acc || '', folder, uid || 0),
    queryFn: () => api.get<MailMessage>(`/api/mail/${acc}/message`, { folder, uid: uid! }),
    enabled: !!acc && !!uid,
    staleTime: Infinity,
    retry: false,
  })
}

export type MailAccountIn = {
  address: string
  password: string
  label?: string
  name?: string
  username?: string
  imap_host: string
  imap_port: number
  imap_tls: string
  smtp_host: string
  smtp_port: number
  smtp_tls: string
  signature?: string
  poll_min?: MailPollMin
  auth_servers?: string[]
}
export function useMailDetect() {
  return useMut((address: string) => api.post<MailDetect>('/api/mail/detect', { address }), { errorToast: false })
}
export function useMailAddAccount() {
  return useMut((b: MailAccountIn) => api.post<{ account: MailAccount; test: MailTest }>('/api/mail/accounts', b), {
    invalidate: [mailKeys.accounts],
    errorToast: false,
  })
}
export function useMailUpdateAccount() {
  return useMut(({ id, ...b }: Partial<MailAccountIn> & { id: string }) => api.patch<{ account: MailAccount; test: MailTest | null }>(`/api/mail/accounts/${id}`, b), {
    invalidate: [mailKeys.all],
    errorToast: false,
  })
}
export function useMailDeleteAccount() {
  return useMut((id: string) => api.del(`/api/mail/accounts/${id}`), { invalidate: [mailKeys.all] })
}
export function useMailAction(acc: string) {
  return useMut((b: { folder: string; uids: number[]; action: MailAction; target?: string }) =>
    api.post<{ ok: boolean; moved_to: string | null }>(`/api/mail/${acc}/actions`, b), {
    // deleting a draft an agent wrote ends its request
    invalidate: [mailKeys.list(acc), mailKeys.folders(acc), mailKeys.outboxAll],
  })
}
export function useMailCreateFolder(acc: string) {
  return useMut((b: { name: string; parent?: string }) => api.post<{ name: string }>(`/api/mail/${acc}/folders`, b), {
    invalidate: [mailKeys.folders(acc)],
  })
}
export function useMailRenameFolder(acc: string) {
  return useMut((b: { name: string; new_name: string }) => api.put<{ name: string }>(`/api/mail/${acc}/folders`, b), {
    invalidate: [mailKeys.folders(acc)],
  })
}
export function useMailDeleteFolder(acc: string) {
  return useMut((name: string) => api.del(`/api/mail/${acc}/folders?name=${encodeURIComponent(name)}`), { invalidate: [mailKeys.folders(acc)] })
}
export const mailAttachmentUrl = (acc: string, folder: string, uid: number, index: number, inline = false) =>
  `/api/mail/${acc}/attachment?folder=${encodeURIComponent(folder)}&uid=${uid}&index=${index}${inline ? '&inline=1' : ''}`

export const fetchMailCompose = (acc: string, mode: MailComposeMode, folder: string, uid: number) =>
  api.get<MailCompose>(`/api/mail/${acc}/compose`, { mode, folder, uid })

function draftForm(d: MailDraft, files: File[]): FormData {
  const fd = new FormData()
  fd.append('data', JSON.stringify(d))
  for (const f of files) fd.append('files', f, f.name)
  return fd
}
export function useMailSend(acc: string) {
  return useMut(({ draft, files }: { draft: MailDraft; files: File[] }) =>
    request<MailSent>(`/api/mail/${acc}/send`, { method: 'POST', body: draftForm(draft, files) }), {
    // sending a draft an agent wrote ends its request (outbox, Notifications)
    invalidate: [mailKeys.accounts, mailKeys.list(acc), mailKeys.folders(acc), mailKeys.outboxAll, qk.feed.all],
    errorToast: false,
  })
}
export function useMailSaveDraft(acc: string) {
  return useMut(({ draft, files }: { draft: MailDraft; files: File[] }) =>
    request<{ folder: string; uid: number }>(`/api/mail/${acc}/draft`, { method: 'POST', body: draftForm(draft, files) }), {
    invalidate: [mailKeys.list(acc), mailKeys.folders(acc)],
    errorToast: false,
  })
}

/** Check one mailbox (or all) for new mail now: new mail starts the agents watching it. */
export function useMailRefresh() {
  return useMut((account: string | undefined) => api.post<MailRefreshResult[]>('/api/mail/refresh', { account }), {
    invalidate: [mailKeys.accounts, mailKeys.lists, mailKeys.foldersAll, mailKeys.everything, mailKeys.outboxAll],
    errorToast: false,
  })
}
/** "All mailboxes": the newest mails of every mailbox from the cache of the last checks (not live). */
export function useMailAll(enabled = true) {
  return useQuery({
    queryKey: mailKeys.everything,
    queryFn: () => api.get<MailAll>('/api/mail/all', { limit: 100 }),
    enabled,
    staleTime: 30_000,
    refetchInterval: 120_000,
    retry: false,
  })
}
/** Messages written by agents that wait for the owner's OK (the same requests are "to do" events of the feed). */
export function useMailOutbox(acc: string | null, enabled = true) {
  return useQuery({
    queryKey: mailKeys.outbox(acc || ''),
    queryFn: () => api.get<MailOutboxItem[]>('/api/mail/outbox', { account: acc! }),
    enabled: !!acc && enabled,
    staleTime: 20_000,
    refetchInterval: 60_000,
  })
}
export function useMailOutboxAct() {
  return useMut(({ id, action }: { id: string; action: 'send' | 'deny' }) => api.post<{ id: string; status: string }>(`/api/mail/outbox/${id}/${action}`, {}), {
    invalidate: [mailKeys.outboxAll, mailKeys.accounts, mailKeys.lists, mailKeys.foldersAll, qk.feed.all],
  })
}
