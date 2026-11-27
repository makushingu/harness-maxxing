// Settings -> Extensions -> Community: the catalogue of harness-maxxing.com/community, in three tabs (extensions,
// themes, skills). Read from the website only when this section is open (GET /api/community/catalogue). Installing
// is two steps: the server downloads the listing at its reviewed commit and shows what it would do (the report of
// `maxxing community check`), then installs exactly that content once the owner confirms.
import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Check, Download, ExternalLink, RefreshCw, Server, Star, Users } from 'lucide-react'
import { api } from '@/lib/api'
import { useT } from '@/i18n'
import { Badge, Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, EmptyState, Segmented, Skeleton, toast } from '@/components/ui'
import { SettingsCard, SectionStack } from './ui'
import { COMMUNITY_URL } from './About'

type Tab = 'extension' | 'theme' | 'skill'
interface Listing { slug: string; type: string; tab: Tab; title: string; description: string; repo: string; sha: string; server_code: boolean; stars: number; author: string; banner: string; url: string }
interface Finding { level: 'info' | 'warn' | 'danger'; what: string; file: string; line: number | null; excerpt: string }
interface Report { kind: Tab; id: string; sha256: string; files: number; summary: string; runs_on_server: boolean; counts: Record<Finding['level'], number>; findings: Finding[]; installed?: { sha256: string }; changed?: boolean; listing: Listing }
interface Installed { kind: Tab; id: string; source: string; state: string }

const TABS: Tab[] = ['extension', 'theme', 'skill']
const TONE = { danger: 'text-destructive', warn: 'text-warning', info: 'text-muted-foreground' } as const

export function CommunitySection() {
  const t = useT()
  const [tab, setTab] = React.useState<Tab>('extension')
  const [open, setOpen] = React.useState<Listing | null>(null)
  const cat = useQuery({ queryKey: ['community-catalogue'], queryFn: () => api.get<{ items: Listing[] }>('/api/community/catalogue'), staleTime: 60_000, retry: false })
  const inst = useQuery({ queryKey: ['workspace', 'community-installed'], queryFn: () => api.get<{ packages: Installed[] }>('/api/community/installed'), staleTime: 60_000 })
  const items = cat.data?.items ?? []
  const has = (it: Listing) => !!inst.data?.packages.some((p) => p.state !== 'removed' && p.source.startsWith(`${it.url} @`))
  const list = items.filter((x) => x.tab === tab)
  return (
    <SectionStack>
      <SettingsCard
        title={t('pkg.catalogue')}
        description={t('pkg.catalogueDesc')}
        actions={
          <>
            <Button variant="outline" size="sm" asChild>
              <a href={COMMUNITY_URL} target="_blank" rel="noreferrer"><ExternalLink /> {t('pkg.site')}</a>
            </Button>
            <Button variant="outline" size="sm" loading={cat.isFetching} onClick={() => cat.refetch()}>
              <RefreshCw /> {t('common.refresh')}
            </Button>
          </>
        }
      >
        <div className="grid gap-4">
          <Segmented<Tab>
            value={tab}
            onChange={setTab}
            size="sm"
            aria-label={t('pkg.catalogue')}
            options={TABS.map((k) => ({ value: k, label: `${t(`pkg.tab.${k}`)}${cat.data ? ` (${items.filter((x) => x.tab === k).length})` : ''}` }))}
          />
          {cat.isLoading ? (
            <div className="grid gap-2"><Skeleton className="h-20" /><Skeleton className="h-20" /></div>
          ) : cat.isError ? (
            <EmptyState compact icon={AlertTriangle} title={t('pkg.unreachable')} description={(cat.error as Error).message} />
          ) : !list.length ? (
            <EmptyState compact icon={Users} title={t('pkg.empty')} description={t('pkg.emptyDesc')} />
          ) : (
            <ul className="grid gap-3 sm:grid-cols-2" data-testid="community-list">
              {list.map((it) => (
                <li key={it.slug} className="flex flex-col overflow-hidden rounded-lg border">
                  {it.banner && <img src={it.banner} alt="" loading="lazy" className="aspect-[2/1] w-full border-b object-cover" />}
                  <div className="flex flex-1 flex-col gap-2 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{it.title}</span>
                      {it.tab === 'extension' && <Badge variant="muted">{t(`pkg.type.${it.type}`)}</Badge>}
                      {it.server_code && <Badge variant="outline"><Server className="size-3" /> {t('pkg.serverCode')}</Badge>}
                    </div>
                    <p className="line-clamp-3 text-[13px] text-muted-foreground">{it.description}</p>
                    <p className="mt-auto flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
                      <span>{it.author}</span>
                      {it.stars > 0 && <span className="inline-flex items-center gap-1"><Star className="size-3" /> {it.stars}</span>}
                      <a href={it.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline pointer-coarse:min-h-10">{t('pkg.details')} <ExternalLink className="size-3" /></a>
                    </p>
                    {has(it) ? (
                      <span className="inline-flex items-center gap-1.5 text-[13px] text-muted-foreground"><Check className="size-3.5" /> {t('pkg.installed')}</span>
                    ) : (
                      <Button variant="outline" size="sm" className="w-fit" onClick={() => setOpen(it)}><Download /> {t('pkg.checkInstall')}</Button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </SettingsCard>
      {open && <InstallDialog listing={open} onClose={() => setOpen(null)} />}
    </SectionStack>
  )
}

function InstallDialog({ listing, onClose }: { listing: Listing; onClose: () => void }) {
  const t = useT()
  const qc = useQueryClient()
  const [read, setRead] = React.useState(false)
  const rep = useQuery({ queryKey: ['community-check', listing.slug, listing.sha], queryFn: () => api.post<Report>(`/api/community/catalogue/${listing.slug}/check`), retry: false, staleTime: 0, gcTime: 0 })
  const r = rep.data
  const install = useMutation({
    mutationFn: () => api.post(`/api/community/catalogue/${listing.slug}/install`, { sha256: r!.sha256, read_it: read, force: !!r!.installed }),
    onSuccess: () => {
      for (const k of [['workspace'], ['extensions'], ['themes']]) qc.invalidateQueries({ queryKey: k })
      toast.success(t('pkg.done', { name: listing.title }))
      onClose()
    },
    onError: (e: Error) => toast.error(e.message),
  })
  const danger = r?.counts.danger ?? 0
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{listing.title}</DialogTitle>
          <DialogDescription>{t('pkg.reportDesc', { commit: listing.sha.slice(0, 12) })}</DialogDescription>
        </DialogHeader>
        {rep.isLoading ? (
          <div className="grid gap-2"><Skeleton className="h-10" /><Skeleton className="h-24" /></div>
        ) : rep.isError || !r ? (
          <p className="text-sm text-destructive">{(rep.error as Error | null)?.message}</p>
        ) : (
          <div className="grid gap-3" data-testid="community-report">
            <p className="text-sm">{r.summary}</p>
            <p className="text-[13px] text-muted-foreground">
              {t(r.runs_on_server ? 'pkg.runsServer' : 'pkg.runsBrowser')} · {t('pkg.files', { n: r.files })} · <span className="font-mono text-xs" title={r.sha256}>sha256 {r.sha256.slice(0, 12)}</span>
            </p>
            {r.findings.length > 0 && (
              <ul className="max-h-[40vh] divide-y overflow-y-auto rounded-lg border text-[13px]">
                {r.findings.map((f, i) => (
                  <li key={i} className="grid gap-0.5 px-3 py-2">
                    <span className={TONE[f.level]}>{f.what}</span>
                    <span className="font-mono text-xs text-muted-foreground [overflow-wrap:anywhere]">{f.file}{f.line ? `:${f.line}` : ''}{f.excerpt ? `  ${f.excerpt}` : ''}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-[13px] text-muted-foreground">{t('pkg.notVerdict')}</p>
            {danger > 0 && (
              <label className="flex cursor-pointer items-start gap-2 text-[13px]">
                <input type="checkbox" checked={read} onChange={(e) => setRead(e.target.checked)} className="mt-0.5" />
                {t('pkg.readIt')}
              </label>
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button data-testid="community-install" disabled={!r || (danger > 0 && !read)} loading={install.isPending} onClick={() => install.mutate()}>
            <Download /> {t(r?.installed ? 'pkg.replace' : 'pkg.install')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
