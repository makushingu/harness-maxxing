// A position's side panel (the chart's ?pos=<id>): "Conversation" = its occupant's conversation, the same flow and box as
// the Office's panel; "Position" = title, job description, department, lead, occupant, Hire, remove, inbox.
import * as React from 'react'
import { Link } from 'react-router'
import { Maximize2, UserMinus, UserPlus, Trash2, X } from 'lucide-react'
import { useLang, useT } from '@/i18n'
import { errorMessage, isApiError } from '@/lib/api'
import { agentRoute, useAgents, useDeletePosition, useEnterpriseEscalations, useEnterpriseRequests, usePositionInbox, useTasks } from '@/lib/queries'
import { fmtRelative } from '@/lib/format'
import type { Agent, Enterprise, Position } from '@/lib/types'
import { Badge, Button, confirm, toast, FormField, Input, Select, Sensitive, Sheet, SheetContent, SheetTitle, StatusDot, Tabs, TabsContent, TabsList, TabsTrigger, Textarea, Tooltip } from '@/components/ui'
import { AgentChatPanel } from '@/features/agents/AgentPage'
import { HireDialog, NONE, leadOptions } from './dialogs'
import { EscalationCard, RequestCard } from './Overview'
import { STATE_TONE, inProjects, subtreeIds, useSavePosition } from './parts'

export function PositionSheet({ enterprise: e, positionId, onClose }: { enterprise: Enterprise; positionId: string | null; onClose: () => void }) {
  const t = useT()
  const p = positionId ? e.positions.find((x) => x.id === positionId) : undefined
  return (
    <Sheet open={!!p} onOpenChange={(v) => !v && onClose()}>
      <SheetContent hideClose className="p-0 md:w-[480px]" data-testid="position-panel" aria-describedby={undefined}>
        <SheetTitle className="sr-only">{p?.title || t('ent.position.panel')}</SheetTitle>
        {p && <PanelBody key={p.id} enterprise={e} position={p} onClose={onClose} />}
      </SheetContent>
    </Sheet>
  )
}

function PanelBody({ enterprise: e, position: p, onClose }: { enterprise: Enterprise; position: Position; onClose: () => void }) {
  const t = useT()
  const [tab, setTab] = React.useState(p.occupant ? 'conversation' : 'position')
  const st = STATE_TONE[p.state]
  const close = (
    <Button variant="ghost" size="icon-sm" aria-label={t('common.close')} onClick={onClose} data-testid="position-close">
      <X />
    </Button>
  )
  return (
    <Tabs value={p.occupant || tab === 'work' ? tab : 'position'} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2">
        <TabsList className="h-8 max-md:h-10">
          {p.occupant && <TabsTrigger value="conversation">{t('ent.panel.conversation')}</TabsTrigger>}
          <TabsTrigger value="position">{t('ent.panel.position')}</TabsTrigger>
          <TabsTrigger value="work">{t('ent.panel.work')}</TabsTrigger>
        </TabsList>
        <span className="inline-flex min-w-0 flex-1 items-center justify-end gap-1.5 text-xs text-muted-foreground">
          <StatusDot tone={st.tone} pulse={st.pulse} />
          <span className="truncate">{t(st.label)}</span>
        </span>
        {(tab !== 'conversation' || !p.occupant) && close}
      </div>
      {p.occupant && (
        <TabsContent value="conversation" className="mt-0 flex min-h-0 flex-1 flex-col">
          <AgentChatPanel path={p.occupant.path} onClose={onClose} />
        </TabsContent>
      )}
      <TabsContent value="position" className="mt-0 min-h-0 flex-1 overflow-y-auto">
        <PositionForm enterprise={e} position={p} onClose={onClose} onHired={() => setTab('conversation')} />
      </TabsContent>
      <TabsContent value="work" className="mt-0 min-h-0 flex-1 overflow-y-auto">
        <PositionWork enterprise={e} position={p} />
      </TabsContent>
    </Tabs>
  )
}

function PositionForm({ enterprise: e, position: p, onClose, onHired }: { enterprise: Enterprise; position: Position; onClose: () => void; onHired: () => void }) {
  const t = useT()
  const { save, pending } = useSavePosition(e)
  const del = useDeletePosition()
  const { data: agents } = useAgents()
  const [title, setTitle] = React.useState(p.title)
  const [department, setDepartment] = React.useState(p.department)
  const [job, setJob] = React.useState(p.job)
  const [hiring, setHiring] = React.useState(false)
  const dirty = title.trim() !== p.title || department.trim() !== p.department || job !== p.job

  const below = React.useMemo(() => subtreeIds(e.positions, p.id), [e.positions, p.id])
  const eligible = React.useMemo(() => {
    const seated = new Set(e.positions.filter((x) => x.id !== p.id && x.agent).map((x) => x.agent as string))
    const list: Agent[] = (agents?.agents || []).filter((a) => inProjects(a.path, e.projects) && !seated.has(a.path))
    return list
  }, [agents, e.positions, e.projects, p.id])
  const occupantOptions = React.useMemo(() => {
    const o = eligible.map((a) => ({ value: a.path, label: <Sensitive length={14}>{`${a.display_name} · ${a.project} / ${a.topic}`}</Sensitive> }))
    // an agent that is gone (or outside the linked projects) still shows as the current value
    if (p.agent && !o.some((x) => x.value === p.agent)) o.unshift({ value: p.agent, label: <Sensitive length={14}>{p.occupant?.display_name || p.agent.split('/').pop() || p.agent}</Sensitive> })
    return o
  }, [eligible, p.agent, p.occupant])

  const reports = e.positions.filter((x) => x.reports_to === p.id)
  const lead = p.reports_to || 'owner'
  const leadTitle = p.reports_to ? e.positions.find((x) => x.id === p.reports_to)?.title || p.reports_to : t('ent.position.leadTop')
  // a position that leads others: the server wants to know where they go (409 has_reports), so it is asked first
  const moveAndRemove = async () => {
    const ok = await confirm({
      title: t('ent.position.removeTitle', { title: p.title }),
      description: t('ent.position.removeMove', { count: reports.length, lead: leadTitle }),
      confirmText: t('ent.position.removeMoveAction'),
      destructive: true,
    })
    if (ok) del.mutate({ id: e.id, pos: p.id, reparent_to: lead }, { onSuccess: onClose, onError: (err) => toast.error(errorMessage(err)) })
  }
  const remove = async () => {
    if (reports.length) return moveAndRemove()
    const ok = await confirm({ title: t('ent.position.removeTitle', { title: p.title }), description: t('ent.position.removeDesc'), confirmText: t('ent.position.remove'), destructive: true })
    if (ok) del.mutate({ id: e.id, pos: p.id }, { onSuccess: onClose, onError: (err) => (isApiError(err, 'has_reports') ? void moveAndRemove() : toast.error(errorMessage(err))) })
  }

  return (
    <div className="grid gap-5 p-4" data-testid="position-form">
      <div className="grid gap-4">
        <FormField label={t('ent.position.title')}>
          <Input value={title} onChange={(ev) => setTitle(ev.target.value)} maxLength={80} autoComplete="off" />
        </FormField>
        <FormField label={t('ent.position.department')}>
          <Input value={department} onChange={(ev) => setDepartment(ev.target.value)} list="ent-departments-edit" maxLength={48} autoComplete="off" />
        </FormField>
        <datalist id="ent-departments-edit">
          {Object.keys(e.departments).map((d) => (
            <option key={d} value={d} />
          ))}
        </datalist>
        <FormField label={t('ent.position.job')} hint={t('ent.position.jobHint')}>
          <Textarea value={job} onChange={(ev) => setJob(ev.target.value)} minRows={4} maxRows={12} />
        </FormField>
        <div>
          <Button size="sm" disabled={!dirty || !title.trim()} loading={pending} onClick={() => save(p.id, { title: title.trim(), department: department.trim(), job })} data-testid="position-save">
            {t('common.save')}
          </Button>
        </div>
      </div>

      <FormField label={t('ent.position.changeLead')}>
        <Select
          value={p.reports_to ?? NONE}
          onValueChange={(v) => save(p.id, { reports_to: v === NONE ? null : v }, { structural: true })}
          options={leadOptions(t('ent.position.leadTop'), e.positions, below)}
        />
      </FormField>

      <div className="grid gap-2">
        <FormField label={t('ent.position.occupant')} hint={p.agent ? undefined : t('ent.position.vacantHint')}>
          <Select
            value={p.agent || undefined}
            onValueChange={(v) => save(p.id, { agent: v }, { structural: true })}
            options={occupantOptions}
            placeholder={t('ent.position.occupantPick')}
            disabled={occupantOptions.length === 0}
          />
        </FormField>
        <div className="flex flex-wrap items-center gap-2">
          {p.agent ? (
            <Button size="sm" variant="outline" onClick={() => save(p.id, { agent: null }, { structural: true })} data-testid="position-vacate">
              <UserMinus /> {t('ent.position.vacate')}
            </Button>
          ) : (
            <Button size="sm" onClick={() => setHiring(true)} data-testid="position-hire-open">
              <UserPlus /> {t('ent.position.hire')}
            </Button>
          )}
          {p.occupant && (
            <Tooltip content={t('agents.office.openPage')}>
              <Button asChild size="sm" variant="ghost">
                <Link to={agentRoute(agentOf(p.occupant.path))}>
                  <Maximize2 /> {t('ent.position.openAgent')}
                </Link>
              </Button>
            </Tooltip>
          )}
        </div>
        {!p.agent && occupantOptions.length === 0 && <p className="text-[13px] text-muted-foreground">{t('ent.position.noAgents')}</p>}
      </div>

      <div className="border-t pt-4">
        <Button variant="outline" size="sm" className="text-destructive hover:text-destructive" onClick={remove} loading={del.isPending} data-testid="position-remove">
          <Trash2 /> {t('ent.position.remove')}
        </Button>
      </div>
      <HireDialog enterprise={e} position={p} open={hiring} onOpenChange={setHiring} onHired={onHired} />
    </div>
  )
}

/** The project / topic / name of an agent path, for its page route. */
function agentOf(path: string): Pick<Agent, 'project' | 'topic' | 'name'> {
  const m = /^projects\/([^/]+)\/topics\/([^/]+)\/agents\/([^/]+)$/.exec(path)
  return { project: m?.[1] || '', topic: m?.[2] || '', name: m?.[3] || '' }
}

/** "Inbox & tasks": what waits in the position's inbox, the tasks delegated to it, and its requests and escalations. */
function PositionWork({ enterprise: e, position: p }: { enterprise: Enterprise; position: Position }) {
  const t = useT()
  const lang = useLang()
  const { data: inbox } = usePositionInbox(e.id, p.id)
  const { data: tasks } = useTasks()
  const requests = useEnterpriseRequests(e.id)
  const escalations = useEnterpriseEscalations(e.id)
  const mine = (tasks?.tasks || []).filter((x) => x.enterprise?.id === e.id && x.enterprise.owner === p.id && x.status !== 'done')
  const reqs = (requests.data || []).filter((r) => r.position === p.id && r.status === 'pending')
  const escs = (escalations.data || []).filter((x) => x.position === p.id && x.status === 'open')
  return (
    <div className="grid gap-6 p-4" data-testid="position-work">
      <section className="grid gap-2">
        <div className="flex items-center gap-2">
          <h4 className="text-sm font-medium">{t('ent.position.inbox')}</h4>
          <Badge variant="muted">{inbox?.length ?? p.inbox}</Badge>
        </div>
        {(inbox || []).length === 0 ? (
          <p className="text-[13px] text-muted-foreground">{t('ent.position.inboxEmpty')}</p>
        ) : (
          <ul className="divide-y rounded-lg border">
            {(inbox || []).slice(0, 12).map((i) => (
              <li key={i.id} className="grid gap-0.5 px-3 py-2 text-[13px]">
                <span className="line-clamp-2">
                  <Sensitive length={20}>{i.text}</Sensitive>
                </span>
                <span className="text-xs text-muted-foreground">
                  {i.kind} · <Sensitive length={6}>{i.from}</Sensitive> · {fmtRelative(i.at, lang)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="grid gap-2">
        <div className="flex items-center gap-2">
          <h4 className="text-sm font-medium">{t('ent.position.tasks')}</h4>
          <Badge variant="muted">{mine.length}</Badge>
        </div>
        {mine.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">{t('ent.position.tasksEmpty')}</p>
        ) : (
          <ul className="divide-y rounded-lg border" data-testid="position-tasks">
            {mine.map((x) => (
              <li key={x.id} className="grid gap-0.5 px-3 py-2 text-[13px]">
                <span className="line-clamp-2">
                  <Sensitive length={20}>{x.title}</Sensitive>
                </span>
                <span className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                  <span>{t(x.status === 'doing' ? 'ent.position.taskDoing' : 'ent.position.taskTodo')}</span>
                  {x.due && <span>{t('ent.position.taskDue', { date: x.due })}</span>}
                  {x.enterprise?.stage === 'blocked' && <Badge variant="warning">{t('ent.state.blocked')}</Badge>}
                  {x.enterprise?.stage === 'review' && <Badge variant="muted">{t('ent.position.taskReview')}</Badge>}
                  {x.enterprise?.requester && x.enterprise.requester !== 'owner' && (
                    <span>
                      {t('ent.position.taskFrom')} <Sensitive length={8}>{e.positions.find((q) => q.id === x.enterprise?.requester)?.title || x.enterprise.requester}</Sensitive>
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="grid gap-2">
        <h4 className="text-sm font-medium">{t('ent.position.asks')}</h4>
        {reqs.length + escs.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">{t('ent.position.asksEmpty')}</p>
        ) : (
          <ul className="grid gap-3">
            {reqs.map((r) => (
              <li key={r.id}>
                <RequestCard enterprise={e} request={r} />
              </li>
            ))}
            {escs.map((x) => (
              <li key={x.id}>
                <EscalationCard enterprise={e} escalation={x} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
