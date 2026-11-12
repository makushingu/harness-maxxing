// The dialogs of Enterprises: New enterprise, Add position, Hire (a vacant position gets a new agent).
import * as React from 'react'
import { useNavigate } from 'react-router'
import { useT } from '@/i18n'
import { errorMessage, isApiError } from '@/lib/api'
import { enterpriseRoute, useAddPosition, useCreateEnterprise, useEnterpriseTemplates, useEnterprises, useHirePosition, useWorkspace } from '@/lib/queries'
import type { Enterprise, Position } from '@/lib/types'
import { SLUG_RE, cn, slugify } from '@/lib/utils'
import { Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, FormField, Input, Select, Sensitive, Textarea, toast } from '@/components/ui'

const NONE = '__none'

/** `base`, else base-2, base-3... (not one of `taken`). */
function freeSlug(base: string, taken: string[]): string {
  const b = (base || 'enterprise').slice(0, 44).replace(/-+$/, '') || 'enterprise'
  if (!taken.includes(b)) return b
  for (let i = 2; ; i++) if (!taken.includes(`${b}-${i}`)) return `${b}-${i}`
}

/** New enterprise: a name (its folder is made from it), an emoji, the projects it links, optionally a ready-made chart. */
export function NewEnterpriseDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const t = useT()
  const navigate = useNavigate()
  const create = useCreateEnterprise()
  const { data: ws } = useWorkspace()
  const { data: list } = useEnterprises()
  const { data: templates } = useEnterpriseTemplates(open)
  const [name, setName] = React.useState('')
  const [emoji, setEmoji] = React.useState('')
  const [projects, setProjects] = React.useState<string[]>([])
  const [template, setTemplate] = React.useState(NONE)
  React.useEffect(() => {
    if (open) {
      setName('')
      setEmoji('')
      setProjects([])
      setTemplate(NONE)
      create.reset()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  // projects already linked to another enterprise cannot be picked again
  const linked = React.useMemo(() => new Set((list || []).flatMap((x) => x.projects)), [list])
  const slug = freeSlug(slugify(name), (list || []).map((x) => x.id))
  const err = create.error
  const nameError = err && isApiError(err) && (err.code === 'invalid_name' || err.code === 'exists') ? err.message : undefined
  const otherError = err && !nameError ? errorMessage(err) : undefined
  const submit = (ev: React.FormEvent) => {
    ev.preventDefault()
    if (!name.trim() || !SLUG_RE.test(slug)) return
    create.mutate(
      { id: slug, name: name.trim(), emoji: emoji.trim() || undefined, projects, template: template === NONE ? undefined : template },
      {
        onSuccess: (e) => {
          onOpenChange(false)
          navigate(enterpriseRoute(e.id))
        },
      },
    )
  }
  const tpl = templates?.find((x) => x.id === template)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="enterprise-new">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{t('ent.new.title')}</DialogTitle>
            <DialogDescription>{t('ent.new.desc')}</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-[minmax(0,1fr)_5rem] gap-3">
            <FormField label={t('ent.new.name')} error={nameError} hint={name.trim() && !nameError ? t('ent.new.folder', { slug }) : undefined}>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('ent.new.namePh')} maxLength={60} autoFocus autoComplete="off" />
            </FormField>
            <FormField label={t('ent.new.emoji')}>
              <Input value={emoji} onChange={(e) => setEmoji(e.target.value)} maxLength={4} className="text-center" autoComplete="off" />
            </FormField>
          </div>
          <fieldset className="grid gap-2">
            <legend className="mb-1 text-sm font-medium">{t('ent.new.projects')}</legend>
            {(ws?.projects || []).length === 0 && <p className="text-[13px] text-muted-foreground">{t('ent.new.noProjects')}</p>}
            <div className="grid max-h-44 gap-1 overflow-y-auto">
              {(ws?.projects || []).map((p) => {
                const taken = linked.has(p.name)
                return (
                  <label key={p.name} className={cn('flex min-h-9 items-center gap-2.5 rounded-md px-2 text-sm hover:bg-accent', taken && 'opacity-50')}>
                    <Checkbox
                      checked={projects.includes(p.name)}
                      disabled={taken}
                      onCheckedChange={(v) => setProjects((x) => (v ? [...x, p.name] : x.filter((n) => n !== p.name)))}
                    />
                    <span className="min-w-0 flex-1 truncate">
                      <Sensitive length={8}>{p.name}</Sensitive>
                    </span>
                    {taken && <span className="text-xs text-muted-foreground">{t('ent.new.taken')}</span>}
                  </label>
                )
              })}
            </div>
          </fieldset>
          {(templates || []).length > 0 && (
            <FormField label={t('ent.new.template')} hint={tpl ? tpl.description : t('ent.new.templateHint')}>
              <Select
                value={template}
                onValueChange={setTemplate}
                options={[{ value: NONE, label: t('ent.new.templateNone') }, ...(templates || []).map((x) => ({ value: x.id, label: x.name }))]}
              />
            </FormField>
          )}
          {otherError && (
            <p role="alert" className="text-[13px] text-destructive">
              {otherError}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={create.isPending} disabled={!name.trim()}>
              {t('ent.new.create')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** Add position: a title (its id is made from it), where it reports, a department and what it is for. */
export function AddPositionDialog({ enterprise: e, open, onOpenChange, reportsTo }: { enterprise: Enterprise; open: boolean; onOpenChange: (v: boolean) => void; reportsTo?: string | null }) {
  const t = useT()
  const add = useAddPosition()
  const [title, setTitle] = React.useState('')
  const [lead, setLead] = React.useState(NONE)
  const [department, setDepartment] = React.useState('')
  const [job, setJob] = React.useState('')
  React.useEffect(() => {
    if (open) {
      setTitle('')
      setLead(reportsTo || NONE)
      setDepartment('')
      setJob('')
      add.reset()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  const id = freeSlug(slugify(title) || 'position', e.positions.map((p) => p.id))
  const err = add.error ? errorMessage(add.error) : undefined
  const submit = (ev: React.FormEvent) => {
    ev.preventDefault()
    if (!title.trim()) return
    add.mutate(
      { enterprise: e.id, id, title: title.trim(), reports_to: lead === NONE ? null : lead, department: department.trim(), job: job.trim() },
      { onSuccess: () => onOpenChange(false) },
    )
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="position-new">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{t('ent.position.add')}</DialogTitle>
            <DialogDescription>{t('ent.position.addDesc')}</DialogDescription>
          </DialogHeader>
          <FormField label={t('ent.position.title')}>
            <Input value={title} onChange={(ev) => setTitle(ev.target.value)} placeholder={t('ent.position.titlePh')} maxLength={80} autoFocus autoComplete="off" />
          </FormField>
          <FormField label={t('ent.position.lead')}>
            <Select value={lead} onValueChange={setLead} options={leadOptions(t('ent.position.leadTop'), e.positions)} />
          </FormField>
          <FormField label={t('ent.position.department')}>
            <Input value={department} onChange={(ev) => setDepartment(ev.target.value)} list="ent-departments" maxLength={48} autoComplete="off" />
          </FormField>
          <datalist id="ent-departments">
            {Object.keys(e.departments).map((d) => (
              <option key={d} value={d} />
            ))}
          </datalist>
          <FormField label={t('ent.position.job')} hint={t('ent.position.jobHint')}>
            <Textarea value={job} onChange={(ev) => setJob(ev.target.value)} minRows={3} maxRows={8} />
          </FormField>
          {err && (
            <p role="alert" className="text-[13px] text-destructive">
              {err}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={add.isPending} disabled={!title.trim()}>
              {t('ent.position.addAction')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** Select options for "reports to": the top, then every position except `skip` ids (itself and its team). */
export function leadOptions(topLabel: string, positions: Position[], skip?: Set<string>) {
  return [{ value: NONE, label: topLabel }, ...positions.filter((p) => !skip?.has(p.id)).map((p) => ({ value: p.id, label: p.title }))]
}
export { NONE }

/** Hire: the topic (of a linked project) where the new agent is created; it then sets itself up in its conversation. */
export function HireDialog({ enterprise: e, position, open, onOpenChange, onHired }: { enterprise: Enterprise; position: Position; open: boolean; onOpenChange: (v: boolean) => void; onHired?: (agent: string) => void }) {
  const t = useT()
  const hire = useHirePosition()
  const { data: ws } = useWorkspace()
  const topics = React.useMemo(
    () => (ws?.projects || []).filter((p) => e.projects.includes(p.name)).flatMap((p) => p.topics.map((x) => ({ value: `projects/${p.name}/topics/${x.name}`, label: `${p.name} / ${x.name}` }))),
    [ws, e.projects],
  )
  const [topic, setTopic] = React.useState('')
  React.useEffect(() => {
    if (open) {
      setTopic((cur) => (topics.some((x) => x.value === cur) ? cur : topics[0]?.value || ''))
      hire.reset()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, topics])
  const submit = (ev: React.FormEvent) => {
    ev.preventDefault()
    if (!topic) return
    hire.mutate(
      { id: e.id, pos: position.id, topic },
      {
        onSuccess: (r) => {
          toast.success(t('ent.hire.done'))
          onOpenChange(false)
          onHired?.(r.agent)
        },
      },
    )
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="position-hire">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{t('ent.hire.title', { title: position.title })}</DialogTitle>
            <DialogDescription>{t('ent.hire.desc')}</DialogDescription>
          </DialogHeader>
          {topics.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('ent.hire.noTopics')}</p>
          ) : (
            <FormField label={t('ent.hire.topic')}>
              <Select value={topic} onValueChange={setTopic} options={topics} />
            </FormField>
          )}
          {hire.error && (
            <p role="alert" className="text-[13px] text-destructive">
              {errorMessage(hire.error)}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={hire.isPending} disabled={!topic}>
              {t('ent.hire.action')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
