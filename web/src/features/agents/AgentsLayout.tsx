// The Agents page (/agents/*, Settings -> Features -> agents_page), laid out like a messaging app: the list of
// agents on the left (AgentsList), the selected agent on the right.
//   /agents                                  -> the overview on the right: the Office (agents at their desks, by
//                                               project; Classic or Gamified view, chosen at the top right)
//   /agents/office                           -> the same Office (the way to it on a phone, where /agents is the list)
//   /agents/<project>/<topic>/<name>         -> the agent: its conversation + its profile (AgentPage)
//   /agents/<project>/<topic>/<name>/runs/<sid> -> one run, the full session in place (RunView)
//   ?new=1 opens the creation sheet, ?topic=<project>/<topic> narrows the list.
// "New agent" and "Edit with Claude" open a new-session draft in Sessions (EditWithClaude.tsx), not a page here.
// The left column, top to bottom: title, search, New agent, the Office entry, the state filter, the agents by project.
// Touch layout: /agents is the list (like the contacts of a chat app: search, state filter, unread counts - easier to
// scan on a phone than the cards) with the Office entry; the Office, an agent or a run opens full screen with a back
// button.
// Agents and their runs never show in Sessions (sessions = where the user works, agents = automatic work).
import * as React from 'react'
import { Link, Route, Routes, useLocation, useSearchParams } from 'react-router'
import { Building2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { useCompact } from '@/stores/media'
import { PageHeader } from '@/components/shell/Page'
import { PreviewProvider } from '@/pages/sessions/FilePreview'
import { AgentsList } from './AgentsList'
import { AgentsEmpty, AgentsOverview } from './AgentsPage'
import AgentPage from './AgentPage'
import { RunView } from './RunView'
import { CreateAgent, type CreateStart } from './CreateAgent'
import { AgentsOff, useAgentsOn } from './parts'

export default function AgentsLayout() {
  const t = useT()
  const on = useAgentsOn()
  const touch = useCompact()
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const creating = params.get('new') === '1'
  const setCreating = React.useCallback(
    (v: boolean) =>
      setParams(
        (p) => {
          if (v) p.set('new', '1')
          else p.delete('new')
          return p
        },
        { replace: true },
      ),
    [setParams],
  )
  // "New agent" and the empty page (its manual / template / import choices, with the picked topic) open the sheet.
  const [start, setStart] = React.useState<CreateStart | null>(null)
  const openWith = React.useCallback(
    (s: CreateStart) => {
      setStart(s)
      setCreating(true)
    },
    [setCreating],
  )
  const topic = params.get('topic') || ''
  const topicPath = topic ? `projects/${topic.replace('/', '/topics/')}` : undefined
  // "New agent": the sheet asks where (the listed topic if the list is narrowed to one), then With Claude / By hand.
  const newAgent = React.useCallback(() => openWith({}), [openWith])
  const home = /^\/agents\/?$/.test(location.pathname)
  const office = home || /^\/agents\/office\/?$/.test(location.pathname)

  if (on === false) return <AgentsOff />

  const detail = (
    <PreviewProvider>
      <Routes>
        <Route index element={<AgentsOverview onNew={newAgent} onStart={openWith} />} />
        <Route path="office" element={<AgentsOverview onNew={newAgent} onStart={openWith} />} />
        <Route path=":project/:topic/:name" element={<AgentPage />} />
        <Route path=":project/:topic/:name/runs/:sid" element={<RunView />} />
      </Routes>
    </PreviewProvider>
  )
  // The way back to the Office (every agent at its desk), whichever agent or run is open: a nav entry of its own,
  // set apart from the search and New agent above it.
  const officeLink = (
    <div className="shrink-0 border-y px-2 py-1.5">
      <Link
        to={touch ? '/agents/office' : '/agents'}
        aria-current={office && !touch ? 'page' : undefined}
        className={cn(
          'flex items-center gap-2.5 rounded-md px-2.5 text-sm font-medium text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
          touch ? 'h-11' : 'h-9',
          office && !touch && 'bg-accent text-foreground',
        )}
        data-testid="agents-office"
      >
        <Building2 className="size-4" />
        {t('agents.side.office')}
      </Link>
    </div>
  )
  const create = <CreateAgent open={creating} onOpenChange={setCreating} start={start} topicPath={topicPath} />

  // Touch: one pane at a time (the list, or the agent / run full screen).
  if (touch)
    return (
      <>
        {home ? (
          <div className="flex min-h-0 flex-1 flex-col">
            <PageHeader title={t('agents.title')} />
            <AgentsList onNew={newAgent} nav={officeLink} empty={<AgentsEmpty onStart={openWith} />} className="flex-1" />
          </div>
        ) : (
          detail
        )}
        {create}
      </>
    )

  return (
    <div className="flex min-h-0 flex-1" data-testid="agents-layout">
      <aside className="flex w-72 shrink-0 flex-col border-r bg-sidebar/40 xl:w-80" aria-label={t('agents.title')}>
        <div className="flex min-h-[var(--header-h)] shrink-0 items-center border-b px-4">
          <h1 className="text-base font-semibold tracking-tight">{t('agents.title')}</h1>
        </div>
        <AgentsList onNew={newAgent} nav={officeLink} className="flex-1" />
      </aside>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto">{detail}</div>
      {create}
    </div>
  )
}
