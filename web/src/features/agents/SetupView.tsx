// A configuration session opened in place in the Agents page, with the same column as the Sessions page
// (SessionColumn, "solo" variant), like a run (RunView):
//   /agents/<project>/<topic>/<name>/setup/<sid> -> "Edit with Claude" on an existing agent (a session of its topic)
//   /agents/setup/<sid>                          -> "Create in one sentence" (a session of any topic)
// Unlike a run, the session is a normal session of a topic (full rights): no redirect when its path is not the
// agent's, and opening it does not read the agent's results. "Open in Sessions" shows it where it lives.
import * as React from 'react'
import { Link, useParams } from 'react-router'
import { ArrowLeft, ExternalLink, WandSparkles } from 'lucide-react'
import { useT } from '@/i18n'
import { agentRoute, useAgent, useSessionSeeded } from '@/lib/queries'
import { Button, Sensitive, Skeleton, Tooltip } from '@/components/ui'
import { PageHeader } from '@/components/shell/Page'
import { SessionColumn } from '@/pages/sessions/Column'
import type { Col } from '@/pages/sessions/store'
import { sessionsUrl } from '@/pages/sessions/util'
import { AgentAvatarIcon } from './Avatar'

const TOPIC_RE = /^projects\/([^/]+)\/topics\/([^/]+)/

export function SetupView() {
  const t = useT()
  const { project = '', topic = '', name = '', sid = '' } = useParams()
  // no name in the route: the creation of a new agent
  const creating = !name
  const { data: a } = useAgent(creating ? null : `projects/${project}/topics/${topic}/agents/${name}`)
  const { data: session } = useSessionSeeded(sid)
  const col = React.useMemo<Col>(() => ({ key: `setup:${sid}`, kind: 'session', id: sid }), [sid])
  const back = creating ? '/agents' : agentRoute({ project, topic, name })
  const backLabel = creating ? t('agents.setup.backList') : t('agents.runView.back')
  const where = session?.path.match(TOPIC_RE)
  return (
    <div className="flex h-full min-h-0 flex-1 flex-col" data-testid="agent-setup-view">
      <PageHeader
        leading={
          <div className="flex items-center gap-2">
            <Tooltip content={backLabel}>
              <Button asChild variant="ghost" size="icon-sm" aria-label={backLabel} className="-ml-1">
                <Link to={back} data-testid="agent-setup-back">
                  <ArrowLeft />
                </Link>
              </Button>
            </Tooltip>
            {creating ? (
              <WandSparkles className="size-5 shrink-0 text-muted-foreground" aria-hidden />
            ) : (
              <Link to={back} className="shrink-0" tabIndex={-1} aria-hidden>
                <AgentAvatarIcon avatar={a?.avatar} size={32} />
              </Link>
            )}
          </div>
        }
        title={
          creating ? (
            t('agents.setup.new')
          ) : a ? (
            <>
              <span className="font-normal text-muted-foreground">{t('agents.setup.title')} ·</span> <Sensitive length={8}>{a.display_name}</Sensitive>
            </>
          ) : (
            <Skeleton className="h-4 w-40" />
          )
        }
        sensitiveTitle={creating ? t('agents.setup.new') : t('agents.setup.title')}
        description={where ? <Sensitive length={10}>{`${where[1]} / ${where[2]}`}</Sensitive> : undefined}
        actions={
          session ? (
            <Button asChild size="sm" variant="ghost" data-testid="agent-setup-sessions">
              <Link to={sessionsUrl(session)}>
                <ExternalLink /> <span className="max-sm:sr-only">{t('agents.setup.openSessions')}</span>
              </Link>
            </Button>
          ) : undefined
        }
      />
      {/* the page header above already leaves room for the notch */}
      <div className="flex min-h-0 flex-1 flex-col" style={{ '--safe-top': '0px' } as React.CSSProperties}>
        <SessionColumn key={sid} col={col} sid={sid} index={0} count={1} variant="solo" />
      </div>
    </div>
  )
}
