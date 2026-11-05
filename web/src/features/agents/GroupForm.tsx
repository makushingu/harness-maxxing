// Create or edit an agent group: a pane at /agents/groups/new (?project= prefilled), the same form in a sheet from a
// group's "…" -> Edit. Fields: project (else the one of the first agent picked: only agents of that project can be
// members), name + folder name (derived, editable at creation), emoji, goal (its CLAUDE.md), 2-6 members with a
// one-line role each (in the order picked: @all and "nobody named" follow it), the lead, the shared folder, trust
// between members, and the limits (folded). Three starters prefill the name, emoji, goal and roles (no agent is made).
import * as React from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { ArrowLeft, FolderOpen, ShieldCheck } from 'lucide-react'
import { useT, type TKey } from '@/i18n'
import { isApiError } from '@/lib/api'
import { groupRoute, useAgents, useCreateGroup, usePatchGroup, useWorkspace } from '@/lib/queries'
import type { Agent, AgentGroup, AgentGroupLimits } from '@/lib/types'
import { SLUG_RE, cn, slugify } from '@/lib/utils'
import { Button, Checkbox, FormField, Input, Select, Sensitive, Switch, Textarea, toast, useMask } from '@/components/ui'
import { Callout } from '@/features/common'
import { PageHeader } from '@/components/shell/Page'
import { useCompact } from '@/stores/media'
import { AgentAvatarIcon } from './Avatar'
import { AgentsOff, useAgentsOn } from './parts'

const MIN_MEMBERS = 2
const MAX_MEMBERS = 6
const DEFAULT_LIMITS: AgentGroupLimits = { waves: 3, replies: 10, per_hour: 40 }
/** name: [min, max] (agent_rooms.LIMITS) */
const LIMIT_RANGE: Record<keyof AgentGroupLimits, [number, number]> = { waves: [1, 6], replies: [1, 30], per_hour: [1, 200] }

/** Starters: a name, an emoji, a goal and the roles of the first members, in order (texts in the dictionaries). */
const STARTERS: { id: 'writing' | 'council' | 'support'; emoji: string; roles: number }[] = [
  { id: 'writing', emoji: '✍️', roles: 3 },
  { id: 'council', emoji: '🧭', roles: 3 },
  { id: 'support', emoji: '🛟', roles: 2 },
]

type Member = { path: string; role: string }
type Form = {
  project: string
  display: string
  slug: string
  slugEdited: boolean
  emoji: string
  goal: string
  members: Member[]
  lead: string
  shared: boolean
  trust: boolean
  limits: AgentGroupLimits
  /** the roles of the starter picked: given in order to the members picked after it */
  roles: string[]
}

const fresh = (project = ''): Form => ({
  project, display: '', slug: '', slugEdited: false, emoji: '', goal: '', members: [], lead: '', shared: true, trust: true, limits: { ...DEFAULT_LIMITS }, roles: [],
})
const fromGroup = (g: AgentGroup): Form => ({
  project: g.project,
  display: g.display_name,
  slug: g.name,
  slugEdited: true,
  emoji: g.emoji,
  goal: g.goal,
  members: g.members.map((m) => ({ path: m.path, role: m.role })),
  lead: g.lead,
  shared: g.shared_files,
  trust: g.trust_members,
  limits: { ...DEFAULT_LIMITS, ...g.limits },
  roles: [],
})

/** The page of /agents/groups/new: the form in the pane on the right (full screen on a phone). */
export function NewGroupPage() {
  const t = useT()
  const on = useAgentsOn()
  const touch = useCompact()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  if (on === false) return <AgentsOff />
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="group-create">
      <PageHeader
        leading={
          touch ? (
            <Button asChild variant="ghost" size="icon-sm" aria-label={t('agents.back')} className="-ml-1">
              <Link to="/agents">
                <ArrowLeft />
              </Link>
            </Button>
          ) : undefined
        }
        title={t('groups.create.title')}
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto grid max-w-2xl content-start gap-5 px-4 py-5 md:px-8">
          <p className="text-sm text-muted-foreground">{t('groups.create.explain')}</p>
          <GroupForm project={params.get('project') || ''} onDone={(g) => navigate(groupRoute(g))} onCancel={() => navigate('/agents')} />
        </div>
      </div>
    </div>
  )
}

/** `group`: edit it (project and folder name fixed), else create one (`project` prefilled). */
export function GroupForm({ group, project = '', onDone, onCancel }: { group?: AgentGroup; project?: string; onDone: (g: AgentGroup) => void; onCancel: () => void }) {
  const t = useT()
  const mask = useMask()
  const touch = useCompact()
  const { data: ws } = useWorkspace()
  const { data: agentsData } = useAgents()
  const create = useCreateGroup()
  const patch = usePatchGroup({ errorToast: false })
  const [f, setF] = React.useState<Form>(() => (group ? fromGroup(group) : fresh(project)))
  const [errors, setErrors] = React.useState<{ name?: string; members?: string; form?: string }>({})
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }))
  const editing = !!group
  const busy = create.isPending || patch.isPending

  const agents = React.useMemo(() => agentsData?.agents || [], [agentsData])
  const byPath = React.useMemo(() => new Map(agents.map((a) => [a.path, a])), [agents])
  // Projects with at least two agents can hold a group.
  const projects = React.useMemo(() => {
    const n = new Map<string, number>()
    for (const a of agents) n.set(a.project, (n.get(a.project) || 0) + 1)
    return (ws?.projects || []).filter((p) => (n.get(p.name) || 0) >= MIN_MEMBERS || p.name === f.project)
  }, [agents, ws, f.project])
  const choices = React.useMemo(
    () => agents.filter((a) => !f.project || a.project === f.project).sort((x, y) => x.project.localeCompare(y.project) || x.topic.localeCompare(y.topic) || x.display_name.localeCompare(y.display_name)),
    [agents, f.project],
  )
  const slug = f.slugEdited ? f.slug : slugify(f.display).slice(0, 48)
  const picked = f.members.map((m) => m.path)
  const pickedNames = new Set(picked.map((p) => p.split('/').pop()))
  const count = f.members.length
  const canSave = !!f.project && !!f.display.trim() && SLUG_RE.test(slug) && count >= MIN_MEMBERS && count <= MAX_MEMBERS

  const toggle = (a: Agent, on: boolean) =>
    setF((x) => {
      if (!on) return { ...x, members: x.members.filter((m) => m.path !== a.path), lead: x.lead === a.path ? '' : x.lead }
      const members = [...x.members, { path: a.path, role: x.roles[x.members.length] || '' }]
      // The first agent picked sets the project when none was chosen.
      return { ...x, project: x.project || a.project, members }
    })
  const setRole = (path: string, role: string) => set('members', f.members.map((m) => (m.path === path ? { ...m, role } : m)))
  const starter = (s: (typeof STARTERS)[number]) => {
    const roles = Array.from({ length: s.roles }, (_, i) => t(`groups.starter.${s.id}.role${i + 1}` as TKey))
    setF((x) => ({
      ...x,
      display: t(`groups.starter.${s.id}.name` as TKey),
      slugEdited: false,
      emoji: s.emoji,
      goal: t(`groups.starter.${s.id}.goal` as TKey),
      roles,
      // members already picked take the roles they have none of, in order
      members: x.members.map((m, i) => ({ ...m, role: m.role || roles[i] || '' })),
    }))
  }

  const submit = async () => {
    setErrors({})
    const body = {
      display_name: f.display.trim(),
      emoji: f.emoji.trim(),
      goal: f.goal.trim(),
      members: f.members.map((m) => ({ path: m.path, role: m.role.trim() })),
      lead: f.lead,
      shared_files: f.shared,
      trust_members: f.trust,
      limits: f.limits,
    }
    try {
      const g = editing ? await patch.mutateAsync({ path: group.path, ...body }) : await create.mutateAsync({ project: f.project, name: slug, ...body })
      toast.success(editing ? t('groups.edit.saved') : t('groups.create.done', { name: g.display_name }))
      onDone(g)
    } catch (e) {
      const code = isApiError(e) ? e.code : ''
      const msg = e instanceof Error ? e.message : String(e)
      if (code === 'exists') setErrors({ name: t('groups.create.exists') })
      else if (code === 'invalid_name') setErrors({ name: msg })
      else if (code === 'members' || code === 'same_name' || code === 'bad_member' || code === 'unknown_member') setErrors({ members: msg })
      else setErrors({ form: msg })
    }
  }

  return (
    <form
      className="grid content-start gap-5"
      onSubmit={(e) => {
        e.preventDefault()
        if (canSave) submit()
      }}
      data-testid="group-form"
    >
      {!editing && (
        <div className="grid gap-2">
          <span className="text-sm font-medium">{t('groups.starter.title')}</span>
          <div className="grid gap-2 sm:grid-cols-3">
            {STARTERS.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => starter(s)}
                className="grid gap-0.5 rounded-xl border px-3 py-2.5 text-left outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
                data-testid={`group-starter-${s.id}`}
              >
                <span className="flex items-center gap-1.5 text-sm font-medium">
                  <span aria-hidden>{s.emoji}</span> {t(`groups.starter.${s.id}.name` as TKey)}
                </span>
                <span className="text-xs text-muted-foreground">{t(`groups.starter.${s.id}.desc` as TKey)}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <FormField label={t('groups.field.project')} hint={editing ? undefined : t('groups.field.projectHint')}>
        <Select
          value={f.project || undefined}
          onValueChange={(v) => setF((x) => ({ ...x, project: v, members: x.members.filter((m) => m.path.startsWith(`projects/${v}/`)), lead: x.lead.startsWith(`projects/${v}/`) ? x.lead : '' }))}
          disabled={editing}
          placeholder={projects.length ? t('agents.create.pickProject') : t('groups.field.noProject')}
          options={projects.map((p) => ({ value: p.name, label: mask(p.emoji ? `${p.emoji} ${p.name}` : p.name, 6) }))}
        />
      </FormField>

      <div className="grid items-start gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_5.5rem]">
        <FormField label={t('groups.field.name')} error={errors.name}>
          <Input value={f.display} autoFocus={!editing && !touch} maxLength={60} onChange={(e) => set('display', e.target.value)} placeholder={t('groups.field.namePlaceholder')} data-testid="group-name" />
        </FormField>
        <FormField label={t('agents.create.slug')} hint={editing ? undefined : t('groups.field.slugHint')}>
          <Input
            value={slug}
            maxLength={48}
            disabled={editing}
            onChange={(e) => setF((x) => ({ ...x, slug: e.target.value.toLowerCase(), slugEdited: true }))}
            aria-invalid={!!slug && !SLUG_RE.test(slug)}
            className="font-mono"
            data-testid="group-slug"
          />
        </FormField>
        <FormField label={t('groups.field.emoji')}>
          <Input value={f.emoji} maxLength={8} onChange={(e) => set('emoji', e.target.value)} placeholder="💬" className="text-center" data-testid="group-emoji" />
        </FormField>
      </div>

      <FormField label={t('groups.field.goal')} hint={t('groups.field.goalHint')}>
        <Textarea minRows={3} maxRows={12} maxLength={4000} value={f.goal} onChange={(e) => set('goal', e.target.value)} placeholder={t('groups.field.goalPlaceholder')} data-testid="group-goal" />
      </FormField>

      <div className="grid gap-2" data-testid="group-members-field">
        <div className="flex items-baseline gap-2">
          <span className="flex-1 text-sm font-medium">{t('groups.field.members')}</span>
          <span className={cn('text-xs tabular-nums', count < MIN_MEMBERS || count > MAX_MEMBERS ? 'text-muted-foreground' : 'text-success')}>{t('groups.field.membersCount', { count, max: MAX_MEMBERS })}</span>
        </div>
        <p className="text-xs text-muted-foreground">{t('groups.field.membersHint')}</p>
        {!choices.length ? (
          <p className="rounded-lg border border-dashed px-3 py-3 text-sm text-muted-foreground">{f.project ? t('groups.field.noAgents') : t('groups.field.noAgentsAll')}</p>
        ) : (
          <div className="grid divide-y rounded-xl border">
            {choices.map((a) => {
              const i = picked.indexOf(a.path)
              const on = i >= 0
              // two members cannot share an @name (their folder name)
              const clash = !on && pickedNames.has(a.name)
              const disabled = !on && (count >= MAX_MEMBERS || clash)
              return (
                <div key={a.path} className={cn('grid gap-2 px-3 py-2', disabled && 'opacity-60')} data-testid="group-member-choice" data-path={a.path}>
                  <label className={cn('flex min-w-0 items-center gap-2.5 pointer-coarse:min-h-10', disabled ? 'cursor-default' : 'cursor-pointer')}>
                    <Checkbox checked={on} disabled={disabled} onCheckedChange={(v) => toggle(a, v === true)} />
                    <AgentAvatarIcon avatar={a.avatar} size={28} />
                    <span className="grid min-w-0 flex-1">
                      <span className="truncate text-sm font-medium">
                        <Sensitive length={8}>{a.display_name}</Sensitive> <span className="font-mono text-xs font-normal text-muted-foreground">@{a.name}</span>
                      </span>
                      <span className="truncate text-xs text-muted-foreground">
                        <Sensitive length={10}>{f.project ? a.topic : `${a.project} / ${a.topic}`}</Sensitive>
                        {clash && ` · ${t('groups.field.sameName', { name: a.name })}`}
                      </span>
                    </span>
                    {on && <span className="grid size-5 shrink-0 place-items-center rounded-full bg-primary text-[11px] font-medium text-primary-foreground tabular-nums">{i + 1}</span>}
                  </label>
                  {on && (
                    <Input
                      value={f.members[i].role}
                      maxLength={120}
                      onChange={(e) => setRole(a.path, e.target.value)}
                      placeholder={t('groups.field.rolePlaceholder')}
                      aria-label={t('groups.field.role', { name: a.display_name })}
                      className="h-8 text-[13px] md:ml-[4.25rem] md:w-[calc(100%-4.25rem)]"
                      data-testid="group-member-role"
                    />
                  )}
                </div>
              )
            })}
          </div>
        )}
        {errors.members && <p className="text-sm text-destructive">{errors.members}</p>}
        {editing && group.members.some((m) => !byPath.has(m.path)) && <p className="text-xs text-muted-foreground">{t('groups.field.goneMembers')}</p>}
      </div>

      <FormField label={t('groups.field.lead')} hint={t('groups.field.leadHint')}>
        <Select
          value={f.lead || '__none'}
          onValueChange={(v) => set('lead', v === '__none' ? '' : v)}
          disabled={count === 0}
          options={[{ value: '__none', label: t('groups.field.leadNone') }, ...f.members.map((m) => ({ value: m.path, label: mask(byPath.get(m.path)?.display_name || m.path.split('/').pop() || '', 6) }))]}
        />
      </FormField>

      <div className="grid gap-3 rounded-lg border p-3">
        <div className="flex items-start gap-3">
          <FolderOpen className="mt-0.5 size-4 shrink-0 text-primary" />
          <label htmlFor="gr-shared" className="grid min-w-0 flex-1 cursor-pointer gap-0.5">
            <span className="text-sm font-medium">{t('groups.field.shared')}</span>
            <span className="text-xs text-muted-foreground">{t('groups.field.sharedHint')}</span>
          </label>
          <Switch id="gr-shared" checked={f.shared} onCheckedChange={(v) => set('shared', v)} data-testid="group-shared" />
        </div>
        <div className="flex items-start gap-3 border-t pt-3">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" />
          <label htmlFor="gr-trust" className="grid min-w-0 flex-1 cursor-pointer gap-0.5">
            <span className="text-sm font-medium">{t('groups.field.trust')}</span>
            <span className="text-xs text-muted-foreground">{t('groups.field.trustHint')}</span>
          </label>
          <Switch id="gr-trust" checked={f.trust} onCheckedChange={(v) => set('trust', v)} data-testid="group-trust" />
        </div>
      </div>

      <details className="group rounded-lg border p-3">
        <summary className="cursor-pointer text-sm font-medium pointer-coarse:min-h-10 pointer-coarse:content-center">{t('groups.limits.title')}</summary>
        <p className="mt-1 mb-3 text-xs text-muted-foreground">{t('groups.limits.desc')}</p>
        <div className="grid items-start gap-3 sm:grid-cols-3">
          {(Object.keys(LIMIT_RANGE) as (keyof AgentGroupLimits)[]).map((k) => (
            <FormField key={k} label={t(`groups.limits.${k}` as TKey)} hint={t(`groups.limits.${k}Hint` as TKey)}>
              <Input
                type="number"
                inputMode="numeric"
                min={LIMIT_RANGE[k][0]}
                max={LIMIT_RANGE[k][1]}
                value={String(f.limits[k])}
                onChange={(e) => {
                  const n = Math.round(Number(e.target.value))
                  if (Number.isFinite(n)) set('limits', { ...f.limits, [k]: Math.max(LIMIT_RANGE[k][0], Math.min(LIMIT_RANGE[k][1], n)) })
                }}
                className="tabular-nums"
                data-testid={`group-limit-${k}`}
              />
            </FormField>
          ))}
        </div>
      </details>

      {errors.form && <Callout tone="error">{errors.form}</Callout>}

      <div className="flex items-center justify-end gap-2 border-t pt-4">
        <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>
          {t('common.cancel')}
        </Button>
        <Button type="submit" disabled={!canSave} loading={busy} data-testid="group-save">
          {editing ? t('common.save') : t('groups.create.go')}
        </Button>
      </div>
    </form>
  )
}
