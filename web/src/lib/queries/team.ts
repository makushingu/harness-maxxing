import { useQuery } from '@tanstack/react-query'
import { api, seg } from '../api'
import type { Ok, Profile, Session } from '../types'
import { useMut } from './util'

// Team chats (server/maxxing/team.py): plain chats between people, kept fresh by the bus topic `team`.
export type TeamPerson = Profile & { server: string; status: 'online' | 'away' | 'offline'; address?: string; peer?: boolean; contact?: boolean }
export type TeamPollOption = { id: string; label: string; votes: string[] }
export type TeamFile = { path: string; name: string; size: number; mime: string }
export type TeamMessage = {
  id: string
  author: string
  at: number
  text: string
  kind: 'text' | 'summary' | 'poll'
  reply_to?: string
  files?: (TeamFile & { pending?: boolean; failed?: boolean })[]
  /** people it was not delivered to yet (chats with real people) */
  pending?: string[]
  poll?: { question: string; multi: boolean; options: TeamPollOption[] }
  summary?: { from: number; to: number; count: number; cost_usd: number; duration_ms: number }
  sent?: { session: string; title: string; at: number }[]
  reactions?: Record<string, string[]>
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
  last: { author: string; at: number; kind: TeamMessage['kind']; text: string; files: number } | null
  unread: number
  updated: number
}
export type TeamState = { me: string; people: Record<string, TeamPerson>; chats: TeamChat[]; reactions: string[] }

export const teamKeys = {
  all: ['team'] as const,
  state: ['team', 'state'] as const,
  chat: (id: string) => ['team', 'chat', id] as const,
}

export function useTeam(enabled = true) {
  return useQuery({ queryKey: teamKeys.state, queryFn: () => api.get<TeamState>('/api/team'), enabled })
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

export function useTeamSend() {
  return useMut(({ cid, ...b }: { cid: string; text: string; reply_to?: string; files?: { path: string }[] }) => api.post<TeamMessage>(`${chatUrl(cid)}/messages`, b), {
    invalidate: inv,
  })
}
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
