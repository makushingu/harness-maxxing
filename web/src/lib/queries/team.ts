import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, seg } from '../api'
import type { Ok, Profile, Session } from '../types'
import { useMut } from './util'

// Team chats (server/maxxing/team.py): plain chats between people, kept fresh by the bus topic `team`.
export type TeamPerson = Profile & { server: string; status: 'online' | 'away' | 'offline'; address?: string; peer?: boolean; contact?: boolean; last_seen?: number }
export type TeamPollOption = { id: string; label: string; votes: string[] }
export type TeamFile = { path: string; name: string; size: number; mime: string }
export type TeamMessage = {
  id: string
  author: string
  at: number
  text: string
  /** info: a local line ("Léa left the group"), never sent */
  kind: 'text' | 'summary' | 'poll' | 'info'
  info?: 'joined' | 'removed' | 'left'
  reply_to?: string
  edited?: number
  deleted?: boolean
  files?: (TeamFile & { pending?: boolean; failed?: boolean })[]
  /** people it was not delivered to yet (chats with real people) */
  pending?: string[]
  poll?: { question: string; multi: boolean; options: TeamPollOption[] }
  summary?: { from: number; to: number; count: number; cost_usd: number; duration_ms: number }
  sent?: { session: string; title: string; at: number }[]
  reactions?: Record<string, string[]>
  /** shown at the send, before the server answered (its id is not one of the server yet) */
  sending?: boolean
}
export type TeamChat = {
  id: string
  kind: 'dm' | 'group'
  name: string
  emoji: string
  members: string[]
  created: number
  read_at?: number
  remote?: boolean
  /** the group's creator (only they can change it) */
  admin?: string | null
  muted?: boolean
  /** the user left this group, or was removed: read-only */
  left?: boolean | 'self' | 'removed'
  /** person -> read up to (their "Seen") */
  seen?: Record<string, number>
  last: { author: string; at: number; kind: TeamMessage['kind']; text: string; files: number; deleted?: boolean } | null
  unread: number
  updated: number
}
/** typing: chat id -> the people writing in it right now (refreshed by the bus, dropped by the server when it ends). */
export type TeamState = { me: string; people: Record<string, TeamPerson>; chats: TeamChat[]; reactions: string[]; typing?: Record<string, string[]> }

export const teamKeys = {
  all: ['team'] as const,
  state: ['team', 'state'] as const,
  chat: (id: string) => ['team', 'chat', id] as const,
}

export function useTeam(enabled = true) {
  // every minute too: presence (online / seen 5 min ago) ages without any event
  return useQuery({ queryKey: teamKeys.state, queryFn: () => api.get<TeamState>('/api/team'), enabled, refetchInterval: 60_000 })
}
export function useTeamChat(id: string | null) {
  return useQuery({
    queryKey: teamKeys.chat(id || ''),
    queryFn: () => api.get<{ chat: TeamChat; messages: TeamMessage[] }>(`/api/team/chats/${seg(id!)}`),
    enabled: !!id,
  })
}

const inv = [teamKeys.all] as const
const chatUrl = (cid: string) => `/api/team/chats/${seg(cid)}`

type ChatData = { chat: TeamChat; messages: TeamMessage[] }
type SendVars = { cid: string; text: string; reply_to?: string; files?: ({ path: string } & Partial<TeamFile>)[] }
/** The message shown while each send is on its way (by its variables). */
const sending = new WeakMap<SendVars, string>()

/** The message is in the open chat at once (no wait for the answer, then for the chat read again): the server's
 *  one takes its place when it answers, and it goes away if the send is refused. */
export function useTeamSend() {
  const qc = useQueryClient()
  /** The message on its way leaves the chat; `msg` (the server's one) takes its place unless it is there already. */
  const settle = (v: SendVars, msg?: TeamMessage) => {
    const id = sending.get(v)
    qc.setQueryData<ChatData>(teamKeys.chat(v.cid), (old) => {
      if (!old) return old
      const rest = old.messages.filter((m) => m.id !== id)
      return { ...old, messages: !msg || rest.some((m) => m.id === msg.id) ? rest : [...rest, msg] }
    })
  }
  return useMut(
    ({ cid, files, ...b }: SendVars) => api.post<TeamMessage>(`${chatUrl(cid)}/messages`, { ...b, files: files?.map((f) => ({ path: f.path })) }),
    {
      invalidate: inv,
      onMutate: async (v) => {
        const key = teamKeys.chat(v.cid)
        // only a chat already read (a send from elsewhere, or while it loads, has nothing to show it in)
        if (!qc.getQueryData(key)) return
        // a read on its way would bring the chat back without it
        await qc.cancelQueries({ queryKey: key })
        const id = `sending-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
        sending.set(v, id)
        const me = qc.getQueryData<TeamState>(teamKeys.state)?.me || 'me'
        const files = (v.files || []).filter((f): f is TeamFile => !!f.name && !!f.mime)
        qc.setQueryData<ChatData>(key, (old) => old && {
          ...old,
          messages: [
            ...old.messages,
            {
              id, author: me, at: Date.now() / 1000, text: v.text.trim(), kind: 'text', sending: true,
              ...(v.reply_to && { reply_to: v.reply_to }),
              ...(files.length && { files }),
              // as the server's one will say: not delivered yet to the chat's real people (the clock shows at once)
              ...(old.chat.remote && { pending: old.chat.members }),
            },
          ],
        })
      },
      onSuccess: (msg, v) => settle(v, msg),
      // refused: it goes (only it: another one sent meanwhile stays), and the chat is read again
      onError: (_e, v) => {
        settle(v)
        void qc.invalidateQueries({ queryKey: teamKeys.chat(v.cid) })
      },
    },
  )
}
/** "I am writing" (the server sends it at most every 3 s, never queued). */
export function useTeamTyping() {
  return useMut((cid: string) => api.post<Ok>(`${chatUrl(cid)}/typing`), { errorToast: false })
}
export function useTeamEdit() {
  return useMut(({ cid, mid, text }: { cid: string; mid: string; text: string }) => api.post<TeamMessage>(`${chatUrl(cid)}/messages/${seg(mid)}/edit`, { text }), { invalidate: inv })
}
export function useTeamDelete() {
  return useMut(({ cid, mid }: { cid: string; mid: string }) => api.post<TeamMessage>(`${chatUrl(cid)}/messages/${seg(mid)}/delete`), { invalidate: inv })
}
export function useTeamGroup() {
  return useMut(({ cid, ...b }: { cid: string; name?: string; emoji?: string; add?: string[]; remove?: string[] }) => api.post<TeamChat>(`${chatUrl(cid)}/group`, b), {
    invalidate: inv,
  })
}
export function useTeamLeave() {
  return useMut((cid: string) => api.post<TeamChat>(`${chatUrl(cid)}/leave`), { invalidate: inv })
}
export function useTeamMute() {
  return useMut(({ cid, muted }: { cid: string; muted: boolean }) => api.post<TeamChat>(`${chatUrl(cid)}/mute`, { muted }), { invalidate: inv })
}
/** "This Harness is open" for the contacts (the server sends it at most every 2 min). */
export const teamPresence = () => api.post<Ok>('/api/team/presence').catch(() => undefined)
export function useTeamRead() {
  return useMut((cid: string) => api.post<Ok>(`${chatUrl(cid)}/read`), { invalidate: [teamKeys.state], errorToast: false })
}
export function useTeamCreateChat() {
  return useMut((b: { kind: 'dm' | 'group'; members: string[]; name?: string; emoji?: string }) => api.post<TeamChat>('/api/team/chats', b), { invalidate: inv })
}
export function useTeamReact() {
  return useMut(({ cid, mid, emoji }: { cid: string; mid: string; emoji: string }) => api.post<TeamMessage>(`${chatUrl(cid)}/messages/${seg(mid)}/react`, { emoji }), {
    invalidate: inv,
  })
}
export function useTeamPoll() {
  return useMut(({ cid, ...b }: { cid: string; question: string; options: string[]; multi: boolean }) => api.post<TeamMessage>(`${chatUrl(cid)}/polls`, b), {
    invalidate: inv,
  })
}
export function useTeamVote() {
  return useMut(({ cid, mid, option }: { cid: string; mid: string; option: string }) => api.post<TeamMessage>(`${chatUrl(cid)}/messages/${seg(mid)}/vote`, { option }), {
    invalidate: inv,
  })
}
export function useTeamSummarize() {
  return useMut(({ cid, ids }: { cid: string; ids: string[] }) => api.post<TeamMessage>(`${chatUrl(cid)}/summarize`, { ids }), { invalidate: inv })
}
export function useTeamUpload() {
  return useMut((files: File[]) => api.upload<{ files: TeamFile[] }>('/api/team/files', files))
}
export function useTeamForward() {
  return useMut(
    ({ cid, mid, ...b }: { cid: string; mid: string; text: string; session?: string; path?: string; title?: string }) =>
      api.post<{ session: Session; message: TeamMessage }>(`${chatUrl(cid)}/messages/${seg(mid)}/forward`, b),
    { invalidate: [teamKeys.all, ['sessions'], ['workspace']] },
  )
}

// Connections with other Harness servers (server/maxxing/teampeer.py)
export type TeamContact = {
  address: string
  id: string
  name: string
  emoji: string
  color: Profile['color']
  status: 'accepted' | 'request' | 'waiting'
  fingerprint: string
  since: number
  last_seen: number
}
export type TeamConnections = {
  ok: boolean
  address: string
  reason: '' | 'no_address' | 'not_https' | 'tailscale' | 'local'
  insecure: boolean
  contacts: TeamContact[]
  open_invites: number
}
export function useTeamConnections(enabled = true) {
  return useQuery({ queryKey: ['team', 'connections'], queryFn: () => api.get<TeamConnections>('/api/team/connections'), enabled })
}
export function useTeamInvite() {
  return useMut(() => api.post<{ invitation: string; expires: number }>('/api/team/connections/invite'), { invalidate: inv })
}
export function useTeamJoin() {
  return useMut((invitation: string) => api.post<{ address: string; fingerprint: string }>('/api/team/connections/join', { invitation }), {
    invalidate: inv,
    errorToast: false,
  })
}
export function useTeamAnswer() {
  return useMut((b: { address: string; accept: boolean }) => api.post<Ok>('/api/team/connections/answer', b), { invalidate: inv })
}
export function useTeamRemoveContact() {
  return useMut((address: string) => api.post<Ok>('/api/team/connections/remove', { address }), { invalidate: inv })
}
