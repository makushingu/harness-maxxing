// /docs and /docs/:slug — in-app documentation: left index (sections) + search (titles, then full text).
import * as React from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router'
import { BookOpen, FileQuestion, ListTree, Search } from 'lucide-react'
import { useAllDocs, useDoc, useDocs } from '@/lib/queries'
import type { DocMeta } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Button, EmptyState, Input, Sheet, SheetBody, SheetContent, SheetHeader, SheetTitle, Skeleton, SkeletonText } from '@/components/ui'
import { Markdown } from '@/components/ui/markdown'
import { PageHeader } from '@/components/shell/Page'

function groupDocs(docs: DocMeta[]) {
  const sorted = [...docs].sort((a, b) => a.order - b.order || a.title.localeCompare(b.title))
  const out: { section: string; docs: DocMeta[] }[] = []
  for (const d of sorted) {
    const g = out.find((x) => x.section === d.section)
    if (g) g.docs.push(d)
    else out.push({ section: d.section, docs: [d] })
  }
  return out
}

function snippet(md: string, q: string) {
  const text = md.replace(/```[\s\S]*?```/g, ' ').replace(/[#>*_`|[\]()-]+/g, ' ').replace(/\s+/g, ' ')
  const i = text.toLowerCase().indexOf(q.toLowerCase())
  if (i < 0) return null
  const s = Math.max(0, i - 40)
  return { before: (s > 0 ? '…' : '') + text.slice(s, i), match: text.slice(i, i + q.length), after: text.slice(i + q.length, i + q.length + 60) + '…' }
}

function DocIndex({ docs, current, onPick }: { docs: DocMeta[]; current?: string; onPick?: () => void }) {
  const t = useT()
  const [q, setQ] = React.useState('')
  const query = q.trim()
  const full = useAllDocs(query.length >= 3)
  const titleHits = query ? docs.filter((d) => (d.title + ' ' + d.section).toLowerCase().includes(query.toLowerCase())) : []
  const textHits =
    query.length >= 3
      ? (full.data ?? [])
          .filter((d) => !titleHits.some((h) => h.slug === d.slug))
          .map((d) => ({ d, s: snippet(d.markdown, query) }))
          .filter((x) => x.s)
      : []
  const searching = full.isFetching
  const linkCls = (active: boolean) =>
    cn('block rounded-md px-2.5 py-1.5 text-sm outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring max-md:py-2.5', active ? 'bg-accent font-medium text-foreground' : 'text-muted-foreground hover:text-foreground')
  return (
    <div className="grid gap-4">
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('docs.search')} className="pl-8" aria-label={t('docs.search')} type="search" />
      </div>
      {query ? (
        <div className="grid gap-1" aria-live="polite">
          {titleHits.map((d) => (
            <Link key={d.slug} to={`/docs/${d.slug}`} className={linkCls(d.slug === current)} onClick={onPick}>
              {d.title}
            </Link>
          ))}
          {textHits.map(({ d, s }) => (
            <Link key={d.slug} to={`/docs/${d.slug}`} className={cn(linkCls(d.slug === current), 'grid gap-0.5')} onClick={onPick}>
              <span className="font-medium text-foreground">{d.title}</span>
              <span className="line-clamp-2 text-xs">
                {s!.before}
                <mark className="rounded-sm bg-primary/20 text-foreground">{s!.match}</mark>
                {s!.after}
              </span>
            </Link>
          ))}
          {!titleHits.length && !textHits.length && <p className="px-2.5 py-2 text-sm text-muted-foreground">{searching ? t('palette.searching') : t('common.noResults')}</p>}
        </div>
      ) : (
        <nav className="grid gap-5" aria-label={t('nav.docs')}>
          {groupDocs(docs).map((g) => (
            <div key={g.section} className="grid gap-0.5">
              <h3 className="mb-1 px-2.5 text-xs font-medium tracking-wide text-muted-foreground/80 uppercase">{g.section}</h3>
              {g.docs.map((d) => (
                <Link key={d.slug} to={`/docs/${d.slug}`} className={linkCls(d.slug === current)} aria-current={d.slug === current ? 'page' : undefined} onClick={onPick}>
                  {d.title}
                </Link>
              ))}
            </div>
          ))}
        </nav>
      )}
    </div>
  )
}

export default function DocsPage() {
  const t = useT()
  const navigate = useNavigate()
  const { slug } = useParams()
  const { data: docs, isLoading } = useDocs()
  const { data: page, isLoading: pageLoading, isError } = useDoc(slug)
  const [sheet, setSheet] = React.useState(false)
  const onLink = React.useCallback(
    (href: string) => {
      if (/^[a-z0-9-]+(#.*)?$/i.test(href) || href.startsWith('/docs/')) {
        const s = href.replace(/^\/docs\//, '').replace(/#.*$/, '').replace(/\.md$/, '')
        return () => navigate(`/docs/${s}`)
      }
      return null
    },
    [navigate],
  )
  if (!slug && docs?.length) {
    const first = groupDocs(docs)[0].docs[0]
    return <Navigate to={`/docs/${first.slug}`} replace />
  }
  const meta = docs?.find((d) => d.slug === slug)
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title={meta?.title || t('nav.docs')}
        sensitiveTitle={t('nav.docs')}
        leading={
          <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setSheet(true)} aria-label={t('docs.index')}>
            <ListTree />
          </Button>
        }
      />
      <div className="mx-auto flex w-full max-w-6xl flex-1 gap-10 px-4 py-6 md:px-6 md:py-8">
        <aside className="sticky top-[calc(var(--header-h)+2rem)] hidden max-h-[calc(100dvh-var(--header-h)-4rem)] w-60 shrink-0 self-start overflow-y-auto pb-4 md:block">
          {isLoading ? <SkeletonText lines={8} /> : <DocIndex docs={docs || []} current={slug} />}
        </aside>
        <article className="min-w-0 flex-1 pb-16" key={slug}>
          {isLoading || pageLoading ? (
            <div className="grid max-w-3xl gap-6">
              <Skeleton className="h-9 w-2/3" />
              <SkeletonText lines={5} />
              <SkeletonText lines={4} />
            </div>
          ) : isError || (!page && slug) ? (
            <EmptyState icon={FileQuestion} title={t('docs.notFound')} action={<Button onClick={() => navigate('/docs')}>{t('docs.backToIndex')}</Button>} />
          ) : !docs?.length ? (
            <EmptyState icon={BookOpen} title={t('docs.empty')} />
          ) : page ? (
            <Markdown className="max-w-3xl animate-in text-[15px]" onLink={onLink}>
              {page.markdown}
            </Markdown>
          ) : null}
        </article>
      </div>
      <Sheet open={sheet} onOpenChange={setSheet}>
        <SheetContent side="left" aria-describedby={undefined}>
          <SheetHeader>
            <SheetTitle>{t('nav.docs')}</SheetTitle>
          </SheetHeader>
          <SheetBody>
            <DocIndex docs={docs || []} current={slug} onPick={() => setSheet(false)} />
          </SheetBody>
        </SheetContent>
      </Sheet>
    </div>
  )
}
