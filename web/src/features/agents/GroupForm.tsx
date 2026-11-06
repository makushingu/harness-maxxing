// Create or edit an agent group.
// New group (/agents/groups/new, ?project= and ?with=<agent path> prefilled) = two ways, like New agent:
//   - by hand, quick: the project, tick 2-6 of its agents, Create. The name is made from the members' names (editable,
//     optional), the folder from the name (-2, -3... when taken), emoji 👥, everything else the defaults. "More options"
//     (folded) holds the rest: starters (Writing, Council, Support: they prefill texts), emoji, folder, goal, roles,
//     lead, shared folder, trust, limits. Then the group opens with the box focused: the first message can say what
//     the group is for.
//   - with Claude: a new session of a topic of the project (else general/inbox) with the request started.
// Edit (the group's "…" -> Edit, a sheet) = the same form with every field shown; project and folder fixed.
import * as React from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { ArrowLeft, ChevronRight, FolderOpen, ShieldCheck, Sparkles } from 'lucide-react'
import { useT, type TFn, type TKey } from '@/i18n'
import { isApiError } from '@/lib/api'
import { groupRoute, useAgentGroups, useAgents, useCreateGroup, usePatchGroup, useWorkspace } from '@/lib/queries'
import type { Agent, AgentGroup, AgentGroupLimits, WorkspaceTree } from '@/lib/types'
import { SLUG_RE, cn, slugify } from '@/lib/utils'
import { Button, Checkbox, FormField, Input, Select, Sensitive, Switch, Textarea, toast, useMask } from '@/components/ui'
import { Callout } from '@/features/common'
import { PageHeader } from '@/components/shell/Page'
import { useCompact } from '@/stores/media'
import { AgentAvatarIcon } from './Avatar'
import { draftUrl } from './EditWithClaude'
import { AgentsOff, useAgentsOn } from './parts'

const MIN_MEMBERS = 2
const MAX_MEMBERS = 6
const DEFAULT_EMOJI = '👥'
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
  /** "" = the name made from the members' names */
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

const fresh = (project = '', members: string[] = []): Form => ({
  project, display: '', slug: '', slugEdited: false, emoji: '', goal: '', members: members.map((path) => ({ path, role: '' })), lead: '', shared: true, trust: true,
  limits: { ...DEFAULT_LIMITS }, roles: [],
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

/** "Writer & Reviewer", "Writer, Reviewer & Publisher" (60 characters at most). */
function autoName(names: string[]): string {
  const s = names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} & ${names[names.length - 1]}`
  return s.length > 60 ? `${s.slice(0, 59).trimEnd()}…` : s
}
/** `base`, else base-2, base-3... (not one of `taken`). */
function freeSlug(base: string, taken: string[]): string {
  const b = (base || 'group').slice(0, 44).replace(/-+$/, '') || 'group'
  if (!taken.includes(b)) return b
  for (let i = 2; ; i++) if (!taken.includes(`${b}-${i}`)) return `${b}-${i}`
}

/** The topic a "with Claude" session starts in: the project's first topic, else general/inbox. */
export function claudeTopic(ws: WorkspaceTree | undefined, project: string): string {
  const p = ws?.projects.find((x) => x.name === project)
  if (p?.topics[0]) return `projects/${p.name}/topics/${p.topics[0].name}`
  return 'projects/general/topics/inbox'
}

/** The request that starts a "New group with Claude" session. */
function createPrompt(t: TFn, project: string, agents: Agent[]): string {
  const names = agents.map((a) => a.display_name || a.name).join(', ')
  if (!project) return t('groups.claude.createAny')
  return names ? t('groups.claude.createWith', { project, agents: names }) : t('groups.claude.create', { project })
}

/** The page of /agents/groups/new: the form in the pane on the right (full screen on a phone). */
export function NewGroupPage() {
  const t = useT()
  const on = useAgentsOn()
  const touch = useCompact()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  if (on === false) return <AgentsOff />
  const withAgent = params.get('with') || ''
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
          <GroupForm
            project={params.get('project') || withAgent.split('/')[1] || ''}
            members={withAgent ? [withAgent] : []}
            onDone={(g) => navigate(groupRoute(g), { state: { focus: true } })}
            onCancel={() => navigate('/agents')}
          />
        </div>
      </div>
    </div>
  )
}

/** `group`: edit it (every field shown; project and folder name fixed), else the quick creation (`project` and
 *  `members` prefilled, the rest under "More options"). */
export function GroupForm({
  group, project = '', members = [], onDone, onCancel,
}: { group?: AgentGroup; project?: string; members?: string[]; onDone: (g: AgentGroup) => void; onCancel: () => void }) {
  const t = useT()
  const mask = useMask()
  const navigate = useNavigate()
  const { data: ws } = useWorkspace()
  const { data: agentsData } = useAgents()
  const { data: groups } = useAgentGroups()
  const create = useCreateGroup()
  const patch = usePatchGroup({ errorToast: false })
  const [f, setF] = React.useState<Form>(() => (group ? fromGroup(group) : fresh(project, members)))
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
  const picked = f.members.map((m) => m.path)
  // members whose agent was deleted since: shown apart with Remove (the server drops them on save anyway)
  const gone = editing && agentsData ? group.members.filter((m) => !byPath.has(m.path) && picked.includes(m.path)) : []
  const count = f.members.length - gone.length
  const auto = autoName(f.members.map((m) => byPath.get(m.path)?.display_name || m.path.split('/').pop() || ''))
  const display = f.display.trim() || auto
  const taken = (groups || []).filter((g) => g.project === f.project).map((g) => g.name)
  const slug = f.slugEdited ? f.slug : freeSlug(slugify(display).slice(0, 48), taken)
  const canSave = !!f.project && !!display && SLUG_RE.test(slug) && count >= MIN_MEMBERS && count <= MAX_MEMBERS

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
  const withClaude = () =>
    navigate(draftUrl(claudeTopic(ws, f.project), createPrompt(t, f.project, f.members.map((m) => byPath.get(m.path)).filter((a): a is Agent => !!a))))

  const submit = async () => {
    setErrors({})
    const body = {
      display_name: display,
      emoji: f.emoji.trim() || (editing ? '' : DEFAULT_EMOJI),
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
      else if (code === 'members' || code === 'bad_member' || code === 'unknown_member') setErrors({ members: msg })
      else setErrors({ form: msg })
    }
  }

  const projectField = (
    <FormField label={t('groups.field.project')} hint={editing ? undefined : t('groups.field.projectHint')}>
      <Select
        value={f.project || undefined}
        onValueChange={(v) => setF((x) => ({ ...x, project: v, members: x.members.filter((m) => m.path.startsWith(`projects/${v}/`)), lead: x.lead.startsWith(`projects/${v}/`) ? x.lead : '' }))}
        disabled={editing}
        placeholder={projects.length ? t('agents.create.pickProject') : t('groups.field.noProject')}
        options={projects.map((p) => ({ value: p.name, label: mask(p.emoji ? `${p.emoji} ${p.name}` : p.name, 6) }))}
      />
    </FormField>
  )

  // The members: a tick per agent of the project; their roles show with the other options (or here when editing).
  const membersField = (
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
            const disabled = !on && count >= MAX_MEMBERS
            return (
              <div key={a.path} className={cn('grid gap-2 px-3 py-2', disabled && 'opacity-60')} data-testid="group-member-choice" data-path={a.path}>
                <label className={cn('flex min-w-0 items-center gap-2.5 pointer-coarse:min-h-11', disabled ? 'cursor-default' : 'cursor-pointer')}>
                  <Checkbox checked={on} disabled={disabled} onCheckedChange={(v) => toggle(a, v === true)} />
                  <AgentAvatarIcon avatar={a.avatar} size={32} />
                  <span className="grid min-w-0 flex-1">
                    <span className="truncate text-sm font-medium">
                      <Sensitive length={8}>{a.display_name}</Sensitive>
                    </span>
                    <span className="truncate text-xs text-muted-foreground">
                      <Sensitive length={10}>{f.project ? a.topic : `${a.project} / ${a.topic}`}</Sensitive>
                    </span>
                  </span>
                  {on && <span className="grid size-5 shrink-0 place-items-center rounded-full bg-primary text-[11px] font-medium text-primary-foreground tabular-nums">{i + 1}</span>}
                </label>
                {on && editing && <RoleInput value={f.members[i].role} name={a.display_name} onChange={(v) => setRole(a.path, v)} className="md:ml-[4.25rem] md:w-[calc(100%-4.25rem)]" />}
              </div>
            )
          })}
        </div>
      )}
      {errors.members && <p className="text-sm text-destructive">{errors.members}</p>}
      {gone.length > 0 && (
        <div className="grid gap-1.5" data-testid="group-gone-members">
          <p className="text-xs text-muted-foreground">{t('groups.field.goneMembers')}</p>
          {gone.map((m) => (
            <div key={m.path} className="flex min-w-0 items-center gap-2.5 rounded-lg border border-dashed px-3 py-1.5">
              <AgentAvatarIcon avatar={m.avatar} size={24} />
              <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
                <Sensitive length={8}>{m.display_name}</Sensitive>
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setF((x) => ({ ...x, members: x.members.filter((y) => y.path !== m.path), lead: x.lead === m.path ? '' : x.lead }))}
                data-testid="group-gone-remove"
              >
                {t('groups.field.goneRemove')}
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  )

  const nameField = (
    <FormField label={editing ? t('groups.field.name') : t('groups.field.nameOptional')} error={errors.name}>
      <Input value={f.display} maxLength={60} onChange={(e) => set('display', e.target.value)} placeholder={auto || t('groups.field.namePlaceholder')} data-testid="group-name" />
    </FormField>
  )

  // Everything but the project, the members and the name: shown when editing, folded under "More options" at creation.
  const more = (
    <>
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

      <div className="grid items-start gap-3 sm:grid-cols-[minmax(0,1fr)_5.5rem]">
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
          <Input value={f.emoji} maxLength={8} onChange={(e) => set('emoji', e.target.value)} placeholder={DEFAULT_EMOJI} className="text-center" data-testid="group-emoji" />
        </FormField>
      </div>

      <FormField label={t('groups.field.goal')} hint={t('groups.field.goalHint')}>
        <Textarea minRows={3} maxRows={12} maxLength={4000} value={f.goal} onChange={(e) => set('goal', e.target.value)} placeholder={t('groups.field.goalPlaceholder')} data-testid="group-goal" />
      </FormField>

      {!editing && count > 0 && (
        <div className="grid gap-2">
          <span className="text-sm font-medium">{t('groups.field.roles')}</span>
          {f.members.map((m) => (
            <div key={m.path} className="flex min-w-0 items-center gap-2">
              <AgentAvatarIcon avatar={byPath.get(m.path)?.avatar} size={24} />
              <RoleInput value={m.role} name={byPath.get(m.path)?.display_name || ''} onChange={(v) => setRole(m.path, v)} className="flex-1" />
            </div>
          ))}
        </div>
      )}

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

      <div className="grid gap-2">
        <span className="text-sm font-medium">{t('groups.limits.title')}</span>
        <p className="text-xs text-muted-foreground">{t('groups.limits.desc')}</p>
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
      </div>
    </>
  )

  return (
    <form
      className="grid content-start gap-5"
      onSubmit={(e) => {
        e.preventDefault()
        if (canSave) submit()
      }}
      data-testid="group-form"
    >
      {projectField}
      {membersField}
      {nameField}

      {editing ? (
        more
      ) : (
        <details className="group rounded-lg border" data-testid="group-more">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-sm font-medium pointer-coarse:min-h-11 [&::-webkit-details-marker]:hidden">
            <ChevronRight className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90" />
            {t('groups.create.more')}
          </summary>
          <div className="grid gap-5 border-t p-3">{more}</div>
        </details>
      )}

      {errors.form && <Callout tone="error">{errors.form}</Callout>}

      {editing ? (
        <div className="flex items-center justify-end gap-2 border-t pt-4">
          <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={!canSave} loading={busy} data-testid="group-save">
            {t('common.save')}
          </Button>
        </div>
      ) : (
        <div className="grid gap-3">
          <Button type="submit" size="lg" className="w-full" disabled={!canSave} loading={busy} data-testid="group-save">
            {count < MIN_MEMBERS ? t('groups.create.pick', { count: MIN_MEMBERS - count }) : t('groups.create.go')}
          </Button>
          {/* The other way in: Claude asks what is missing and creates it from a session (skill maxxing-agents). */}
          <button
            type="button"
            onClick={withClaude}
            className="flex items-start gap-3 rounded-xl border bg-card p-3 text-left transition-colors hover:border-primary/40 hover:bg-accent/40"
            data-testid="group-with-claude"
          >
            <Sparkles className="mt-0.5 size-5 shrink-0 text-primary" />
            <span className="grid min-w-0 gap-0.5">
              <span className="text-sm font-medium">{t('groups.claude.title')}</span>
              <span className="text-xs text-muted-foreground">{t('groups.claude.desc')}</span>
            </span>
          </button>
        </div>
      )}
    </form>
  )
}

function RoleInput({ value, name, onChange, className }: { value: string; name: string; onChange: (v: string) => void; className?: string }) {
  const t = useT()
  return (
    <Input
      value={value}
      maxLength={120}
      onChange={(e) => onChange(e.target.value)}
      placeholder={t('groups.field.rolePlaceholder')}
      aria-label={t('groups.field.role', { name })}
      className={cn('h-8 min-w-0 text-[13px]', className)}
      data-testid="group-member-role"
    />
  )
}
