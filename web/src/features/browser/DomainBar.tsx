// In the live view of a sandboxed agent's browser: a page outside the agent's domains (the person's sign-in page of
// another domain, a link, the owner's conversation, which is not limited). Its runs would empty that tab: the bar says
// so and adds the site to its domains in one click (its commands get it too).
import { useQueryClient } from '@tanstack/react-query'
import { ShieldCheck } from 'lucide-react'
import { useT } from '@/i18n'
import { browserKeys, useBrowserOwner, usePatchAgent } from '@/lib/queries'
import { Button } from '@/components/ui'

function hostOf(url: string): string {
  try {
    const u = new URL(url)
    return u.protocol === 'http:' || u.protocol === 'https:' ? u.hostname.toLowerCase().replace(/\.$/, '') : ''
  } catch {
    return ''
  }
}

export function DomainBar({ nav, url, who }: { nav: string; url: string; who?: string }) {
  const t = useT()
  const path = nav.startsWith('agent:') ? nav.slice(6) : ''
  const { data: o } = useBrowserOwner(path, !!path)
  const patch = usePatchAgent()
  const qc = useQueryClient()
  const host = hostOf(url)
  const sites = o?.sites
  if (!path || !sites || !host || sites.some((s) => host === s || host.endsWith(`.${s}`))) return null
  const add = async () => {
    await patch.mutateAsync({ path, domains: [...sites, host] })
    await qc.invalidateQueries({ queryKey: browserKeys.owner(path) })
  }
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b bg-warning/10 px-3 py-2 text-[13px]" data-testid="browser-domain-bar">
      <ShieldCheck className="size-4 shrink-0 text-warning" />
      <span className="min-w-0 flex-1">{t('browser.domain.out', { host, name: who || t('browser.domain.agent') })}</span>
      <Button size="sm" className="h-7 shrink-0" disabled={patch.isPending} onClick={() => void add()} data-testid="browser-domain-add">
        {t('browser.domain.add')}
      </Button>
    </div>
  )
}
