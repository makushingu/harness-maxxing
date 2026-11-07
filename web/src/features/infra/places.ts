// Where each Infra resource runs, for the Infra page grouped by type then by place: this server and the other servers
// first ("own"), then the hosted services ("hosted"). A domain's place is where it points (the place of its linked
// sites, else the provider that hosts it), not where it was bought.
import { Cloud, CircleDashed, House, type LucideIcon, Server, ShoppingBag } from 'lucide-react'
import type { InfraResource, InfraView } from '@/lib/types'
import type { TFn } from '@/i18n'
import { PLATFORMS, PROVIDER_NAMES, locationLabel, providerName } from './shared'

export type Tier = 'own' | 'hosted' | 'none'
/** `sensitive`: the label is the user's own data (a server name), masked in presentation mode. */
export type Place = { key: string; label: string; tier: Tier; color: string; icon: LucideIcon; sensitive?: boolean }

const PROVIDER_COLOR: Record<string, string> = Object.assign(Object.create(null), {
  cloudflare: 'oklch(0.72 0.16 55)',
  vercel: 'oklch(0.7 0 0)',
  netlify: 'oklch(0.72 0.12 185)',
  supabase: 'oklch(0.7 0.15 155)',
  github: 'oklch(0.62 0.02 260)',
  hostinger: 'oklch(0.62 0.17 275)',
  shopify: 'oklch(0.7 0.16 135)',
})
// Other servers, in the order of the config.
const SERVER_COLORS = ['oklch(0.7 0.12 190)', 'oklch(0.7 0.13 330)', 'oklch(0.74 0.13 95)', 'oklch(0.68 0.13 230)']

export function serverNames(v?: InfraView): string[] {
  return [...new Set([...(v?.servers || []).map((s) => s.name), ...Object.keys(v?.sources.servers || {})])].filter((n) => n !== 'local')
}

export function placeInfo(key: string, v: InfraView | undefined, t: TFn): Place {
  if (key === 'local') return { key, label: t('infra.thisServer'), tier: 'own', color: 'var(--primary)', icon: House }
  if (key === 'none') return { key, label: t('infra.place.none'), tier: 'none', color: 'var(--muted-foreground)', icon: CircleDashed }
  const servers = serverNames(v)
  const i = servers.indexOf(key)
  if (i >= 0) return { key, label: locationLabel(key, t), tier: 'own', color: SERVER_COLORS[i % SERVER_COLORS.length], icon: Server, sensitive: true }
  if (key === 'server') return { key, label: t('infra.yourServer'), tier: 'own', color: SERVER_COLORS[0], icon: Server }
  return {
    key,
    label: key === 'other' ? t('infra.elsewhere') : providerName(key, t) || locationLabel(key, t),
    sensitive: key !== 'other' && !PROVIDER_NAMES[key],
    tier: 'hosted',
    color: PROVIDER_COLOR[key] || 'oklch(0.6 0.02 260)',
    icon: key === 'shopify' ? ShoppingBag : Cloud,
  }
}

/** The place of a resource: its location, or for a domain where it points. */
export function placeOf(r: InfraResource, byId: Map<string, InfraResource>): string {
  if (r.kind !== 'domain') return r.location
  const locs = r.links.map((id) => byId.get(id)).filter((x) => x && x.kind !== 'domain').map((x) => x!.location)
  if (locs.length) return [...locs].sort((a, b) => rank(a) - rank(b))[0]
  const h = r.details.hosted_by as string | undefined
  if (h && h !== 'server') return h
  return h === 'server' ? 'server' : 'none'
}

/** Other places a domain points to (after the first one). */
export function otherPlaces(r: InfraResource, byId: Map<string, InfraResource>): string[] {
  if (r.kind !== 'domain') return []
  const first = placeOf(r, byId)
  return [...new Set(r.links.map((id) => byId.get(id)).filter((x) => x && x.kind !== 'domain').map((x) => x!.location))].filter((l) => l !== first)
}

/** this server, other servers, then the hosted services, "elsewhere" and "nowhere" last. */
function rank(l: string) {
  if (l === 'local') return 0
  if (l === 'none') return 9
  if (l === 'other') return 8
  if (l === 'cloudflare') return 3
  if ((PLATFORMS as readonly string[]).includes(l)) return 4
  if (l === 'hostinger') return 5
  if (l === 'shopify') return 6
  if (PROVIDER_NAMES[l]) return 7
  return 1
}
export const byPlace = (a: string, b: string) => rank(a) - rank(b) || a.localeCompare(b)
