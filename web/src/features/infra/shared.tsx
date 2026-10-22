// Shared bits of the Infra page and of the ```infra chat blocks.
import { Boxes, Cloud, Database, Globe, HardDrive, type LucideIcon, Server, Workflow, Zap } from 'lucide-react'
import type { InfraKind, InfraResource, InfraStatus } from '@/lib/types'
import type { DotTone } from '@/components/ui'
import { fmtBytes } from '@/lib/format'
import { tDyn, type TFn } from '@/i18n'

export const KIND_ICON: Record<InfraKind, LucideIcon> = {
  server: Server,
  site: Globe,
  worker: Zap,
  pages: Workflow,
  database: Database,
  bucket: Boxes,
  domain: Globe,
}
export const PLATFORMS = ['vercel', 'netlify', 'supabase', 'github'] as const
export const LOCATION_ICON = (loc: string): LucideIcon =>
  loc === 'cloudflare' || (PLATFORMS as readonly string[]).includes(loc) ? Cloud : loc === 'hostinger' ? HardDrive : Server

/** Display name of a provider id (registrar, DNS, host, platform) from server/maxxing/infra (dnsinfo, platforms). */
const PROVIDER_NAMES: Record<string, string> = {
  cloudflare: 'Cloudflare', hostinger: 'Hostinger', ovh: 'OVHcloud', gandi: 'Gandi', namecheap: 'Namecheap', godaddy: 'GoDaddy',
  ionos: 'IONOS', aws: 'AWS', google: 'Google', vercel: 'Vercel', netlify: 'Netlify', porkbun: 'Porkbun', wix: 'Wix',
  o2switch: 'o2switch', infomaniak: 'Infomaniak', digitalocean: 'DigitalOcean', hetzner: 'Hetzner', 'name.com': 'Name.com',
  dnsimple: 'DNSimple', azure: 'Azure', vultr: 'Vultr', linode: 'Akamai (Linode)', squarespace: 'Squarespace',
  github: 'GitHub Pages', shopify: 'Shopify', webflow: 'Webflow', supabase: 'Supabase', render: 'Render', railway: 'Railway',
  fly: 'Fly.io', firebase: 'Firebase', heroku: 'Heroku', ghost: 'Ghost',
}
export function providerName(id: string | null | undefined, t: TFn): string {
  if (!id) return ''
  if (id === 'server') return t('infra.yourServer')
  if (id === 'other') return t('infra.elsewhere')
  return PROVIDER_NAMES[id] || id
}

export const STATUS_TONE: Record<InfraStatus, DotTone> = { ok: 'ok', warn: 'warn', down: 'error', unknown: 'idle' }

// Names shown for the other servers (their label, "VPS Hostinger"), set from the last /api/infra answer.
const serverLabels = new Map<string, string>()
export function rememberServers(servers?: { name: string; label?: string }[]) {
  for (const s of servers || []) serverLabels.set(s.name, s.label || s.name)
}

export function locationLabel(loc: string, t: TFn) {
  if (loc === 'local') return t('infra.thisServer')
  if (loc === 'other') return t('infra.elsewhere')
  return serverLabels.get(loc) || PROVIDER_NAMES[loc] || loc
}

/** "http_404" -> "HTTP 404", known codes -> a sentence. */
export function statusText(r: InfraResource, t: TFn): string {
  const d = r.status_detail
  if (!d) return tDyn(t, `infra.status.${r.status}`, r.status)
  const m = /^http_(\d+)$/.exec(d)
  if (m) return `HTTP ${m[1]}`
  return tDyn(t, `infra.why.${d}`, d.replace(/_/g, ' '))
}

/** One short line under the name: what it is and how big. */
export function subtitle(r: InfraResource, t: TFn): string {
  const d = r.details
  switch (r.kind) {
    case 'site':
      if (d.kind === 'proxy') return `${t('infra.kindProxy')} ${(d.upstreams || []).join(', ')}`
      if (d.kind === 'static') return `${t('infra.kindStatic')} ${d.root || ''}`
      if (d.kind === 'redirect') return `${t('infra.kindRedirect')} ${d.redirect || ''}`
      return d.kind || ''
    case 'database':
      return [d.engine === 'supabase' ? `Supabase Postgres ${d.version || ''}`.trim() : d.engine, d.region, d.container ? `docker ${d.container}` : d.where === 'native' ? t('infra.native') : '', d.size != null ? fmtBytes(d.size) : '', d.tables ? t('infra.tables', { count: d.tables }) : '', d.path || '']
        .filter(Boolean)
        .join(' · ')
    case 'bucket':
      return [d.engine === 'r2' ? 'R2' : d.engine || providerName(d.platform, t), d.public ? t('infra.public') : '', d.bytes != null ? fmtBytes(d.bytes) : '', d.objects != null ? t('infra.objects', { count: d.objects }) : '']
        .filter(Boolean)
        .join(' · ')
    case 'domain':
      return [
        d.registrar ? t('infra.registrar', { name: providerName(d.registrar, t) }) : '',
        d.dns ? `DNS ${providerName(d.dns, t)}` : '',
        d.hosted_by ? t('infra.hostedBy', { name: providerName(d.hosted_by, t) }) : '',
        d.days_left != null ? t('infra.expiresIn', { count: d.days_left }) : '',
      ]
        .filter(Boolean)
        .join(' · ')
    case 'server':
      return [d.os, d.ips?.[0], d.cpus ? `${d.cpus} CPU` : '', d.mem_total ? fmtBytes(d.mem_total) : '', d.disk_free != null ? t('infra.diskFree', { size: fmtBytes(d.disk_free) }) : '']
        .filter(Boolean)
        .join(' · ')
    case 'worker':
      return (d.routes || []).join(', ')
    case 'pages':
      return [d.platform ? providerName(d.platform, t) : '', d.framework, d.branch, d.repo?.github].filter(Boolean).join(' · ')
  }
  return ''
}
