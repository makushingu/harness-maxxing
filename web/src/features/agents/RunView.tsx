// One run of an agent, opened in place in the Agents page (/agents/<project>/<topic>/<name>/runs/<sid>): the full
// session (messages, tools, approvals, the reply box) with the same column as the Sessions page (SessionColumn,
// "solo" variant), under a bar that goes back to the agent's conversation and offers "Continue in Sessions".
import * as React from 'react'
import { Link, Navigate, useParams } from 'react-router'
import { ArrowLeft } from 'lucide-react'
import { useLang, useT } from '@/i18n'
import { agentRoute, useAgent, useAgentSeen, useSessionSeeded } from '@/lib/queries'
import { Button, Sensitive, Skeleton, Tooltip } from '@/components/ui'
import { PageHeader } from '@/components/shell/Page'
import { SessionColumn } from '@/pages/sessions/Column'
import type { Col } from '@/pages/sessions/store'
import { sessionsUrl } from '@/pages/sessions/util'
import { AgentAvatarIcon } from './Avatar'
import { ContinueButton, agoText } from './parts'

export function RunView() {
  const t = useT()
  const lang = useLang()
  const { project = '', topic = '', name = '', sid = '' } = useParams()
  const path = `projects/${project}/topics/${topic}/agents/${name}`
  const { data: a } = useAgent(path)
  const { data: session } = useSessionSeeded(sid)
  const col = React.useMemo<Col>(() => ({ key: `run:${sid}`, kind: 'session', id: sid }), [sid])
  // Opening a run reads the agent's results, like opening its page (the nav badge drops).
  const seen = useAgentSeen()
  const seenMutate = seen.mutate
  const unread = a?.thread_unread || 0
  React.useEffect(() => {
    if (unread > 0) seenMutate({ path })
  }, [unread, path, seenMutate])
  // Not a run of this agent (an old link, a session moved away): open it where it lives.
  if (session && session.path !== path) return <Navigate to={sessionsUrl(session)} replace />

  const back = agentRoute({ project, topic, name })
  const running = session?.state === 'running'
  return (
    <div className="flex h-full min-h-0 flex-1 flex-col" data-testid="agent-run-view">
      <PageHeader
        leading={
          <div className="flex items-center gap-2">
            <Tooltip content={t('agents.runView.back')}>
              <Button asChild variant="ghost" size="icon-sm" aria-label={t('agents.runView.back')} className="-ml-1">
                <Link to={back} data-testid="agent-run-back">
                  <ArrowLeft />
                </Link>
              </Button>
            </Tooltip>
            <Link to={back} className="shrink-0" tabIndex={-1} aria-hidden>
              <AgentAvatarIcon avatar={a?.avatar} size={32} />
            </Link>
          </div>
        }
        title={
          a ? (
            <>
              <Sensitive length={8}>{a.display_name}</Sensitive> <span className="font-normal text-muted-foreground">· {t('agents.runView.run')}</span>
            </>
          ) : (
            <Skeleton className="h-4 w-40" />
          )
        }
        sensitiveTitle={t('agents.runView.run')}
        description={session ? t('agents.runView.started', { when: agoText(session.created, lang, t) }) : undefined}
        actions={<ContinueButton agent={{ path, running_sessions: running ? [{ id: sid, title: '' }] : [] }} sid={sid} />}
      />
      {/* the page header above already leaves room for the notch */}
      <div className="flex min-h-0 flex-1 flex-col" style={{ '--safe-top': '0px' } as React.CSSProperties}>
        <SessionColumn key={sid} col={col} sid={sid} index={0} count={1} variant="solo" agentRun />
      </div>
    </div>
  )
}
