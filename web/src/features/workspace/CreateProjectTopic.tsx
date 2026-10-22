import * as React from 'react'
import { FolderPlus, Hash } from 'lucide-react'
import { useCreateProject, useCreateTopic, useWorkspace } from '@/lib/queries'
import { errorMessage, isApiError } from '@/lib/api'
import { slugify, SLUG_RE } from '@/lib/utils'
import type { Topic } from '@/lib/types'
import { useT } from '@/i18n'
import { Button, FormField, Input, Segmented, Sensitive } from '@/components/ui'
import { Combobox } from '@/components/ui/combobox'

/** Slug preview under a name input: shows exactly what folder name the server will get. */
export function SlugPreview({ label, prefix }: { label: string; prefix?: string }) {
  const t = useT()
  const slug = slugify(label)
  return (
    <span className="flex min-w-0 items-center gap-1.5 font-mono text-xs">
      <span className="text-muted-foreground">{t('workspace.folder')}</span>
      <span className="truncate">
        {prefix && <span className="text-muted-foreground">{prefix}</span>}
        <span className={slug ? 'text-foreground' : 'text-muted-foreground'}>
          <Sensitive length={8}>{slug || '…'}</Sensitive>
        </span>
      </span>
    </span>
  )
}

/**
 * Create a project (or pick an existing one) and a first topic inside it.
 * `onCreated(topic)` fires after both exist.
 */
export function CreateProjectTopic({ onCreated, submitLabel }: { onCreated?: (t: Topic) => void; submitLabel?: string }) {
  const t = useT()
  const { data: ws } = useWorkspace()
  const projects = ws?.projects || []
  const [mode, setMode] = React.useState<'new' | 'existing'>('new')
  const [projectLabel, setProjectLabel] = React.useState('')
  const [existing, setExisting] = React.useState('')
  const [description, setDescription] = React.useState('')
  const [topicLabel, setTopicLabel] = React.useState('')
  const [errors, setErrors] = React.useState<{ project?: string; topic?: string; form?: string }>({})
  const createProject = useCreateProject()
  const createTopic = useCreateTopic()
  const busy = createProject.isPending || createTopic.isPending

  React.useEffect(() => {
    if (projects.length && !existing) setExisting(projects[0].name)
  }, [projects, existing])

  const pSlug = mode === 'new' ? slugify(projectLabel) : existing
  const tSlug = slugify(topicLabel)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const errs: typeof errors = {}
    if (!SLUG_RE.test(pSlug)) errs.project = t('workspace.nameInvalid')
    if (!SLUG_RE.test(tSlug)) errs.topic = t('workspace.nameInvalid')
    setErrors(errs)
    if (Object.keys(errs).length) return
    try {
      if (mode === 'new') {
        try {
          await createProject.mutateAsync({ name: pSlug, description: description.trim() || undefined })
        } catch (err) {
          if (!(isApiError(err) && err.status === 409)) throw Object.assign(err as Error, { field: 'project' })
        }
      }
      try {
        const topic = await createTopic.mutateAsync({ project: pSlug, name: tSlug })
        onCreated?.(topic)
      } catch (err) {
        throw Object.assign(err as Error, { field: 'topic' })
      }
    } catch (err) {
      const field = (err as { field?: 'project' | 'topic' }).field
      const msg = isApiError(err, 'exists') ? t('workspace.exists') : isApiError(err, 'has_running_sessions') ? t('workspace.hasRunningSessions') : errorMessage(err)
      setErrors(field ? { [field]: msg } : { form: msg })
    }
  }

  return (
    <form onSubmit={submit} className="grid gap-5" noValidate>
      {projects.length > 0 && (
        <Segmented
          value={mode}
          onChange={setMode}
          aria-label={t('workspace.project')}
          options={[
            { value: 'new', label: t('workspace.newProject') },
            { value: 'existing', label: t('workspace.existingProject') },
          ]}
        />
      )}
      {mode === 'new' ? (
        <>
          <FormField label={t('workspace.projectName')} error={errors.project} hint={<SlugPreview label={projectLabel} prefix="projects/" />}>
            <Input value={projectLabel} onChange={(e) => setProjectLabel(e.target.value)} placeholder={t('workspace.projectPlaceholder')} autoComplete="off" />
          </FormField>
          <FormField label={t('workspace.description')} hint={t('workspace.descriptionHint')}>
            <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder={t('workspace.descriptionPlaceholder')} autoComplete="off" />
          </FormField>
        </>
      ) : (
        <FormField label={t('workspace.project')} error={errors.project}>
          <Combobox value={existing} onChange={setExisting} options={projects.map((p) => ({ value: p.name, label: p.name, hint: String(p.topics.length) }))} />
        </FormField>
      )}
      <FormField label={t('workspace.topicName')} error={errors.topic} hint={<SlugPreview label={topicLabel} prefix={`projects/${pSlug || '…'}/topics/`} />}>
        <Input value={topicLabel} onChange={(e) => setTopicLabel(e.target.value)} placeholder={t('workspace.topicPlaceholder')} autoComplete="off" />
      </FormField>
      {errors.form && (
        <p role="alert" className="text-[13px] text-destructive">
          {errors.form}
        </p>
      )}
      <div>
        <Button type="submit" loading={busy}>
          {mode === 'new' ? <FolderPlus /> : <Hash />} {submitLabel || t('workspace.create')}
        </Button>
      </div>
    </form>
  )
}
