import { useQuery, useQueryClient } from '@tanstack/react-query'
import * as React from 'react'
import { api } from '../api'

// Infra -> E-mail (server/maxxing/infra/mailinfo.py, GET /api/infra/mail): view only. The server caches the providers
// 5 min and the DNS 1 h; refresh() asks it to skip both.
export type MailProblemLevel = 'error' | 'warn' | 'info'
export type MailProblem = { level: MailProblemLevel; code: string; text: string; fix: string; params: Record<string, string | number> }
export type MailLastCheck = { at: number; ok: boolean; error: string } | null
export type InfraMailbox = {
  id: string
  address: string
  label?: string
  domain: string
  imap_host?: string
  imap_port?: number
  smtp_host?: string
  smtp_port?: number
  has_password?: boolean
  last_check: MailLastCheck
}
export type MailCfRule = { name: string; enabled: boolean; catch_all: boolean; from: string | null; action: string | null; to: string[]; worker: string | null }
export type MailCfZone = {
  zone: string
  name: string
  routing: { enabled: boolean; status: string | null } | null
  rules: MailCfRule[]
  error?: string
  message?: string
  missing_permission?: boolean
}
export type MailCloudflare = {
  connected: boolean
  key: string | null
  error?: string
  message?: string
  zones: MailCfZone[]
  addresses: { email: string; verified: boolean; verified_at: string | null }[]
  addresses_error?: string
  addresses_fix?: string
  missing_permission_zones?: number
  fix?: string
}
export type MailHostingerOrder = {
  id: string
  domain: string | null
  status: string | null
  plan: string | null
  seats: number | null
  expires: string | null
  mailboxes: { address: string; status: string | null; catch_all: boolean }[]
  aliases: { address: string; to: string; enabled: boolean }[]
  forwarders: { from: string; to: string; enabled: boolean; confirmed: boolean; keep_copy: boolean }[]
  catchalls: { domain: string; to: string; enabled: boolean; confirmed: boolean }[]
  error?: string
  message?: string
}
export type MailHostinger = { connected: boolean; key: string | null; error?: string; message?: string; orders: MailHostingerOrder[] }
export type MailRouteKind = 'forward' | 'worker' | 'drop' | 'mailbox' | 'alias' | 'catchall' | 'other'
export type MailRoute = {
  domain: string
  address: string
  via: 'cloudflare' | 'hostinger'
  kind: MailRouteKind
  enabled: boolean
  account: string | null
  worker: string | null
  to: { address: string; verified: boolean | null; account: string | null }[]
}
export type MailDomainHealth = {
  domain: string
  sources: string[]
  expects: boolean
  checked: number | null
  error: string | null
  mx: string[]
  spf: { record: string | null; count: number; lookups: number | null }
  dkim: string[]
  dmarc: { record: string | null; count: number; policy: string | null }
  problems: MailProblem[]
}
export type InfraMailView = {
  generated_at: number | null
  cached: boolean
  mail_page: boolean
  mailboxes: InfraMailbox[]
  cloudflare: MailCloudflare
  hostinger: MailHostinger
  routes: MailRoute[]
  domains: MailDomainHealth[]
}

export const infraMailKey = ['infra', 'mail'] as const

export function useInfraMail(enabled = true) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: infraMailKey,
    queryFn: () => api.get<InfraMailView>('/api/infra/mail'),
    enabled,
    staleTime: 60_000,
  })
  const [refreshing, setRefreshing] = React.useState(false)
  const refresh = React.useCallback(async () => {
    setRefreshing(true)
    try {
      qc.setQueryData(infraMailKey, await api.get<InfraMailView>('/api/infra/mail?refresh=1'))
    } finally {
      setRefreshing(false)
    }
  }, [qc])
  return { ...q, refresh, refreshing }
}
