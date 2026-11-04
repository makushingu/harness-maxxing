// The Agents page (/agents/*, Settings -> Features -> agents_page), laid out like a messaging app: the list of
// agents on the left (AgentsList), the selected agent on the right.
//   /agents                                  -> the overview on the right (agents at their desks, by project)
//   /agents/<project>/<topic>/<name>         -> the agent: its conversation + its profile (AgentPage)
//   /agents/<project>/<topic>/<name>/runs/<sid> -> one run, the full session in place (RunView)
//   ?new=1 opens the creation sheet, ?topic=<project>/<topic> narrows the list.
// Touch layout: /agents is the list (like the contacts of a chat app: search, grouping, unread counts - easier to
// scan on a phone than the cards); an agent or a run opens full screen with a back button.
// Agents and their runs never show in Sessions (sessions = where the user works, agents = automatic work).
import * as React from 'react'
import { Route, Routes, useLocation, useSearchParams } from 'react-router'
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
  // The empty page offers the one-sentence box, the gallery and the manual / import links: the sheet opens there.
  const [start, setStart] = React.useState<CreateStart | null>(null)
  const openWith = React.useCallback(
    (s: CreateStart) => {
      setStart(s)
      setCreating(true)
    },
    [setCreating],
  )
  const newAgent = React.useCallback(() => {
    setStart(null)
    setCreating(true)
  }, [setCreating])
  const topic = params.get('topic') || ''
  const home = /^\/agents\/?$/.test(location.pathname)

  if (on === false) return <AgentsOff />

  const detail = (
    <PreviewProvider>
      <Routes>
        <Route index element={<AgentsOverview onNew={newAgent} onStart={openWith} />} />
        <Route path=":project/:topic/:name" element={<AgentPage />} />
        <Route path=":project/:topic/:name/runs/:sid" element={<RunView />} />
      </Routes>
    </PreviewProvider>
  )
  const create = <CreateAgent open={creating} onOpenChange={setCreating} start={start} topicPath={topic ? `projects/${topic.replace('/', '/topics/')}` : undefined} />

  // Touch: one pane at a time (the list, or the agent / run full screen).
  if (touch)
    return (
      <>
        {home ? (
          <div className="flex min-h-0 flex-1 flex-col">
            <PageHeader title={t('agents.title')} />
            <AgentsList onNew={newAgent} empty={<AgentsEmpty onStart={openWith} />} className="flex-1" />
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
        <AgentsList onNew={newAgent} className="flex-1" />
      </aside>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto">{detail}</div>
      {create}
    </div>
  )
}
