// The Agents page (/agents/*, Settings -> Features -> agents_page), laid out like a messaging app: the list of
// agents on the left (AgentsList), the selected agent on the right.
//   /agents                                  -> the overview on the right: the Office (agents at their desks, by
//                                               project; Classic or Space view, chosen at the top right)
//   /agents/office                           -> the same Office (the way to it on a phone, where /agents is the list)
//   /agents/<project>/<topic>/<name>         -> the agent: its conversation + its profile (AgentPage)
//   /agents/<project>/<topic>/<name>/runs/<sid> -> one run, the full session in place (RunView)
//   /agents/groups/<project>/<name>          -> an agent group: the owner talks to several agents (GroupPage)
//   /agents/groups/new?project=<p>           -> the form of a new group (GroupForm)
//   ?new=1 opens the creation sheet, ?topic=<project>/<topic> narrows the list.
// "New agent" and "Edit with Claude" open a new-session draft in Sessions (EditWithClaude.tsx), not a page here.
// The left column, top to bottom: title, search, New agent, the Office entry, the state filter, the agents by project.
// Touch layout: /agents is the list (like the contacts of a chat app: search, state filter, unread counts - easier to
// scan on a phone than the cards) with the Office entry; the Office, an agent or a run opens full screen with a back
// button.
// Agents and their runs never show in Sessions (sessions = where the user works, agents = automatic work).
import * as React from 'react'
import { Route, Routes, useParams, useSearchParams } from 'react-router'
import { useT } from '@/i18n'
import { useCompact } from '@/stores/media'
import { PreviewProvider } from '@/pages/sessions/FilePreview'
import { AgentsList, OfficeLink } from './AgentsList'
import { AgentHover } from './AgentHover'
import { PageList } from '@/components/shell/PageList'
import { AgentsOverview } from './AgentsPage'
import AgentPage from './AgentPage'
import { RunView } from './RunView'
import { CreateAgent, type CreateStart } from './CreateAgent'
import GroupPage from './GroupPage'
import { NewGroupPage } from './GroupForm'
import { useAgentGroups, useWorkspace } from '@/lib/queries'
import { AgentsOff, useAgentsOn } from './parts'

export default function AgentsLayout() {
  const t = useT()
  const on = useAgentsOn()
  const touch = useCompact()
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

  if (on === false) return <AgentsOff />

  const detail = (
    <PreviewProvider>
      <Routes>
        <Route index element={<AgentsOverview onNew={newAgent} onStart={openWith} />} />
        <Route path="office" element={<AgentsOverview onNew={newAgent} onStart={openWith} />} />
        <Route path="groups/new" element={<NewGroupPage />} />
        {/* Static "groups" ranks before the agents' :project: see GroupPageFor for a project called "groups". */}
        <Route path="groups/:project/:name" element={<GroupPageFor />} />
        <Route path=":project/:topic/:name" element={<AgentPageFor />} />
        <Route path=":project/:topic/:name/runs/:sid" element={<RunView />} />
      </Routes>
    </PreviewProvider>
  )
  const create = <CreateAgent open={creating} onOpenChange={setCreating} start={start} topicPath={topicPath} />

  // The list in the second-level sidebar (components/shell/PageList.tsx; touch: the left drawer), the agent or the
  // Office in the page.
  return (
    <div className="flex min-h-0 flex-1" data-testid="agents-layout">
      <PageList id="agents" label={t('agents.title')}>
        {touch ? (
          <AgentsList nav={<OfficeLink onNew={newAgent} />} className="min-h-0 flex-1" />
        ) : (
          <AgentHover className="min-h-0 flex-1">
            <AgentsList nav={<OfficeLink onNew={newAgent} />} className="flex-1" />
          </AgentHover>
        )}
      </PageList>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto">{detail}</div>
      {create}
    </div>
  )
}

/** One page per agent: going from one agent to another starts fresh, so a role being edited, a typed message or a
 *  reply target never carries over to (and gets saved or sent to) the next agent. */
function AgentPageFor() {
  const { project = '', topic = '', name = '' } = useParams()
  return <AgentPage key={`${project}/${topic}/${name}`} />
}

/** One page per group (same reason). /agents/groups/<a>/<b> is also the address of the agent <b> of the topic <a> in a
 *  project called "groups": that agent shows when no group has that name. */
function GroupPageFor() {
  const { project = '', name = '' } = useParams()
  const { data: ws } = useWorkspace()
  const agentHere = !!ws?.projects.find((p) => p.name === 'groups')?.topics.some((x) => x.name === project)
  const { data: groups } = useAgentGroups(agentHere)
  if (agentHere && groups && !groups.some((g) => g.project === project && g.name === name))
    return <AgentPage key={`groups/${project}/${name}`} at={{ project: 'groups', topic: project, name }} />
  return <GroupPage key={`${project}/${name}`} />
}
