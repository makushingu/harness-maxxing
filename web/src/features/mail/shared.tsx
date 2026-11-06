// Small pieces shared by the E-mail page panes.
import { Archive, FileText, Flag, Folder, Inbox, Mails, Send, ShieldAlert, Trash2, type LucideIcon } from 'lucide-react'
import type { MailAddress, MailFolder, MailRole } from '@/lib/types'
import type { TKey } from '@/i18n'
import { fmtDate } from '@/lib/format'

export const ROLE_ICON: Record<MailRole, LucideIcon> = {
  inbox: Inbox,
  drafts: FileText,
  sent: Send,
  archive: Archive,
  junk: ShieldAlert,
  trash: Trash2,
  all: Mails,
  flagged: Flag,
}

export const folderIcon = (f: Pick<MailFolder, 'role'>): LucideIcon => (f.role ? ROLE_ICON[f.role] : Folder)

/** Display name of a folder: the role name for special folders ("Sent" for "INBOX.Sent"), else the last segment. */
export function folderLabel(f: MailFolder, t: (k: TKey) => string): string {
  if (f.role && f.role !== 'all' && f.role !== 'flagged') return t(`mail.role.${f.role}` as TKey)
  return leaf(f.name, f.delim)
}

export function leaf(name: string, delim: string | null): string {
  if (!delim) return name
  const parts = name.split(delim)
  const rest = parts[0].toUpperCase() === 'INBOX' && parts.length > 1 ? parts.slice(1) : parts
  return rest[rest.length - 1] || name
}

/** Nesting depth below the personal prefix (INBOX.A.B -> 1). */
export function depth(f: MailFolder): number {
  if (!f.delim || f.role) return 0
  const parts = f.name.split(f.delim)
  const n = parts[0].toUpperCase() === 'INBOX' ? parts.length - 2 : parts.length - 1
  return Math.max(0, Math.min(4, n))
}

// Bidi controls (U+202E "right-to-left override"...) turn "moc.lapyap@" into "@paypal.com" on screen and
// "facture\u202Efdp.exe" into "facture exe.pdf"; other control characters can hide the end of a name. Dropped from
// whatever a sender wrote before it is shown (the text itself still renders in its own direction inside <bdi>).
const CONTROLS = /[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/g
export const clean = (s: string | null | undefined) => (s || '').replace(CONTROLS, '')

export const who = (a: MailAddress | undefined) => (a ? clean(a.name) || clean(a.email) : '')
export const whoFull = (a: MailAddress) => (a.name ? `${clean(a.name)} <${clean(a.email)}>` : clean(a.email))

/** "14:32" today, "12 oct." this year, "12/10/2025" before. */
export function shortDate(ts: number | null, lang: string): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) return fmtDate(ts, lang, undefined, { dateStyle: undefined, timeStyle: undefined, hour: '2-digit', minute: '2-digit' })
  if (d.getFullYear() === now.getFullYear()) return fmtDate(ts, lang, undefined, { dateStyle: undefined, timeStyle: undefined, day: 'numeric', month: 'short' })
  return fmtDate(ts, lang, undefined, { dateStyle: 'short', timeStyle: undefined })
}

export function initials(a: MailAddress | undefined): string {
  const s = (a?.name || a?.email || '?').replace(/["']/g, '').trim()
  const parts = s.split(/[\s@._-]+/).filter(Boolean)
  return ((parts[0]?.[0] || '?') + (parts.length > 1 ? parts[1][0] : '')).toUpperCase()
}

const HUES = ['bg-blue-500/15 text-blue-600 dark:text-blue-300', 'bg-violet-500/15 text-violet-600 dark:text-violet-300',
  'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300', 'bg-amber-500/15 text-amber-700 dark:text-amber-300',
  'bg-rose-500/15 text-rose-600 dark:text-rose-300', 'bg-teal-500/15 text-teal-600 dark:text-teal-300']
export function avatarTone(a: MailAddress | undefined): string {
  const s = a?.email || a?.name || ''
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return HUES[Math.abs(h) % HUES.length]
}
