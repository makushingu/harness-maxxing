import { Link } from 'react-router'
import { Sparkles } from 'lucide-react'
import { useAuthState, useChangelog } from '@/lib/queries'
import { useT } from '@/i18n'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, Skeleton } from '@/components/ui'
import { Markdown } from '@/components/ui/markdown'
import type { ChangelogEntry } from '@/lib/types'
import { markSeen, useWhatsNew } from './store'
import { SHOW_LINK_CLASS, showcaseLink, showLinks } from './showcases'
import { useTour } from '@/tour/store'

const norm = (v: string) =>
  v
    .toLowerCase()
    .replace(/^v/, '')
    .replace(/[-.]?(alpha|beta|rc)[-.]?(\d+)/, (_m, p: string, n: string) => ({ alpha: 'a', beta: 'b', rc: 'rc' })[p] + n)

/** Entries newer than `since` (the version this browser saw last); everything recent when unknown. */
function newer(entries: ChangelogEntry[], since: string | null): ChangelogEntry[] {
  if (!since) return entries.slice(0, 3)
  const i = entries.findIndex((e) => norm(e.version) === norm(since))
  return i > 0 ? entries.slice(0, i) : entries.slice(0, 1)
}

export default function WhatsNewDialog() {
  const t = useT()
  const { open, since, close } = useWhatsNew()
  const { data, isPending } = useChangelog(open)
  const { data: auth } = useAuthState()
  const onOpenChange = (o: boolean) => {
    if (o) return
    const v = data?.version || auth?.version
    if (v) markSeen(v)
    close()
  }
  const list = data ? newer(data.entries, since) : []
  // "Show me": close this dialog, then spotlight the feature where it lives.
  const onLink = showcaseLink(useTour.getState().start, () => onOpenChange(false))
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="md:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="size-4 text-primary" /> {t('whatsnew.title')}
          </DialogTitle>
          <DialogDescription>{data ? t('whatsnew.desc', { version: data.version }) : t('whatsnew.loading')}</DialogDescription>
        </DialogHeader>
        <div className="-mr-2 max-h-[60vh] overflow-y-auto pr-2">
          {isPending ? (
            <div className="grid gap-2">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-16" />
            </div>
          ) : (
            <div className="grid gap-6">
              {list.map((e) => (
                <section key={e.version} className="grid gap-2">
                  <h3 className="text-sm font-semibold">
                    {e.version}
                    {e.label && <span className="ml-2 font-normal text-muted-foreground">{e.label}</span>}
                  </h3>
                  <Markdown
                    onLink={onLink}
                    className={`text-[13.5px] ${SHOW_LINK_CLASS}`}
                  >
                    {showLinks(e.body, t('show.button'))}
                  </Markdown>
                </section>
              ))}
            </div>
          )}
        </div>
        <Link to="/settings/updates" onClick={() => onOpenChange(false)} className="text-[13px] font-medium text-primary hover:underline">
          {t('updates.all')}
        </Link>
      </DialogContent>
    </Dialog>
  )
}
