// Create an agent, in a side sheet (bottom sheet on touch screens): where (project, then topic) and a name, then
// "Create and talk": the agent is made empty (no role, free like a session) and its conversation opens - it asks what
// it should do, writes its role and schedules and asks about its freedoms itself (agents.MANAGER_NEW). The same form
// shows on the empty Agents page (NewAgentForm). "Import a Claude Code agent file": a .claude/agents/<name>.md file
// (picked or pasted) becomes an agent of a topic.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { ArrowLeft, ArrowRight, Dices, FileUp, MessageSquare } from 'lucide-react'
import { useT } from '@/i18n'
import { errorMessage, isApiError } from '@/lib/api'
import { agentRoute, useCreateAgent, useImportAgent, useWorkspace } from '@/lib/queries'
import type { Agent, AgentAvatar, AgentImportResult } from '@/lib/types'
import { SLUG_RE, slugify } from '@/lib/utils'
import { Button, FormField, Input, Select, Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle, Textarea, toast, useMask } from '@/components/ui'
import { Callout } from '@/features/common'
import { AgentAvatarIcon, randomAvatar } from './Avatar'
import { useProjectColorOf } from './layout'

/** How the sheet opens: on the form (default) or on the import; `topic` = the topic to start from. */
export type CreateStart = { importing?: boolean; topic?: string }

export function CreateAgent({ open, onOpenChange, topicPath, start }: { open: boolean; onOpenChange: (o: boolean) => void; topicPath?: string; start?: CreateStart | null }) {
  const t = useT()
  const navigate = useNavigate()
  const [importing, setImporting] = React.useState(false)
  const [where, setWhere] = React.useState(topicPath)
  React.useEffect(() => {
    if (open) {
      setWhere(start?.topic || topicPath)
      setImporting(!!start?.importing)
    }
  }, [open, topicPath, start])
  const openAgent = (a: Agent) => {
    onOpenChange(false)
    navigate(agentRoute(a))
  }
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="md:w-[520px]" data-testid="agent-create">
        <SheetHeader>
          <SheetTitle>{importing ? t('agents.import.title') : t('agents.create.title')}</SheetTitle>
          <SheetDescription>{importing ? t('agents.import.desc') : t('agents.new.desc')}</SheetDescription>
        </SheetHeader>
        <SheetBody className="grid content-start gap-5">
          {importing ? (
            <ImportAgentFile topicPath={where} onBack={() => setImporting(false)} onOpen={openAgent} />
          ) : (
            <NewAgentForm key={where || ''} topicPath={where} onImport={(w) => (setWhere(w), setImporting(true))} onDone={openAgent} />
          )}
        </SheetBody>
      </SheetContent>
    </Sheet>
  )
}

/** Where (project, then topic) and a name, its character drawn at random (dice to draw another), then "Create and
 *  talk": the empty agent is made and `onDone` opens it (its conversation). */
export function NewAgentForm({ topicPath, onImport, onDone }: { topicPath?: string; onImport: (topic: string) => void; onDone: (a: Agent) => void }) {
  const t = useT()
  const mask = useMask()
  const { data: ws } = useWorkspace()
  const colorOf = useProjectColorOf()
  const create = useCreateAgent()
  const projects = React.useMemo(() => (ws?.projects || []).filter((p) => p.name !== 'system'), [ws])
  const m = topicPath ? /^projects\/([^/]+)\/topics\/([^/]+)$/.exec(topicPath) : null
  const [project, setProject] = React.useState(m?.[1] || '')
  const [topic, setTopic] = React.useState(m?.[2] || '')
  const [display, setDisplay] = React.useState('')
  const [avatar, setAvatar] = React.useState<AgentAvatar>(() => randomAvatar(m?.[1] ? colorOf(m[1]) : undefined))
  const [error, setError] = React.useState('')
  // no project picked yet: the first one (general/inbox on a fresh install)
  React.useEffect(() => {
    if (!project && projects.length) {
      const p = projects.find((x) => x.name === 'general') || projects[0]
      setProject(p.name)
      setTopic(p.topics.find((x) => x.name === 'inbox')?.name || p.topics[0]?.name || '')
      setAvatar((a) => ({ ...a, color: colorOf(p.name) }))
    }
  }, [project, projects, colorOf])
  const topics = projects.find((p) => p.name === project)?.topics || []
  const where = project && topics.some((x) => x.name === topic) ? `projects/${project}/topics/${topic}` : ''
  const slug = slugify(display).slice(0, 48)
  const ok = !!where && !!display.trim() && SLUG_RE.test(slug)
  const go = () => {
    setError('')
    create.mutate(
      { topic_path: where, name: slug, display_name: display.trim(), description: '', avatar },
      {
        onSuccess: (a) => onDone(a),
        onError: (e) => setError(isApiError(e) && e.code === 'exists' ? t('agents.create.exists') : errorMessage(e)),
      },
    )
  }
  return (
    <form
      className="grid gap-5"
      onSubmit={(e) => {
        e.preventDefault()
        if (ok) go()
      }}
      data-testid="agent-quick"
    >
      <div className="flex items-end gap-3">
        <AgentAvatarIcon avatar={avatar} size={48} animate />
        <FormField
          label={t('agents.create.name')}
          className="min-w-0 flex-1"
          error={display.trim() && !SLUG_RE.test(slug) ? t('agents.create.nameLatin') : undefined}
        >
          <Input value={display} onChange={(e) => setDisplay(e.target.value)} maxLength={60} placeholder={t('agents.create.namePlaceholder')} autoFocus data-testid="agent-name" />
        </FormField>
        <Button type="button" variant="outline" size="icon" onClick={() => setAvatar(randomAvatar(project ? colorOf(project) : undefined))} aria-label={t('agents.avatar.random')} title={t('agents.avatar.random')}>
          <Dices />
        </Button>
      </div>
      <div className="grid items-start gap-3 sm:grid-cols-2">
        <FormField label={t('agents.create.project')}>
          <Select
            value={project || undefined}
            onValueChange={(v) => {
              setProject(v)
              setTopic(projects.find((p) => p.name === v)?.topics[0]?.name || '')
              setAvatar((a) => ({ ...a, color: colorOf(v) }))
            }}
            placeholder={t('agents.create.pickProject')}
            options={projects.map((p) => ({ value: p.name, label: mask(p.emoji ? `${p.emoji} ${p.name}` : p.name, 6) }))}
          />
        </FormField>
        <FormField label={t('agents.create.topic')}>
          <Select value={topic || undefined} onValueChange={setTopic} disabled={!project} placeholder={t('agents.create.pickTopic')} options={topics.map((x) => ({ value: x.name, label: mask(x.name, 6) }))} />
        </FormField>
      </div>
      <p className="-mt-3 text-xs text-muted-foreground">{t('agents.create.topicHint')}</p>
      {error && <Callout tone="error">{error}</Callout>}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={!ok} loading={create.isPending} data-testid="agent-quick-go">
          <MessageSquare /> {t('agents.new.go')}
        </Button>
        <Button type="button" variant="link" className="ml-auto h-auto p-0" disabled={!where} onClick={() => onImport(where)} data-testid="agent-import">
          <FileUp /> {t('agents.import.link')}
        </Button>
      </div>
    </form>
  )
}

/** The topics an agent can live in (the system project aside), as select options. */
function useTopicOptions() {
  const { data: ws } = useWorkspace()
  return React.useMemo(
    () => (ws?.projects || []).filter((p) => p.name !== 'system').flatMap((p) => p.topics.map((x) => ({ value: `projects/${p.name}/topics/${x.name}`, label: `${p.name} / ${x.name}` }))),
    [ws],
  )
}

/** A Claude Code agent file (.claude/agents/<name>.md: front matter + prompt), picked or pasted, becomes an agent of a
 *  topic (POST /api/agents/import). Its fields with no equivalent (mcpServers, memory...) are listed after. */
function ImportAgentFile({ topicPath, onBack, onOpen }: { topicPath?: string; onBack: () => void; onOpen: (a: Agent) => void }) {
  const t = useT()
  const mask = useMask()
  const topics = useTopicOptions()
  const imp = useImportAgent()
  const [where, setWhere] = React.useState(topicPath || '')
  const [text, setText] = React.useState('')
  const [file, setFile] = React.useState('')
  const [name, setName] = React.useState('')
  const [done, setDone] = React.useState<AgentImportResult | null>(null)
  const pick = async (f: File | undefined) => {
    if (!f) return
    setFile(f.name)
    setText(await f.text())
    // the file name is the agent's name in Claude Code: offered as the folder
    if (!name) setName(slugify(f.name.replace(/\.md$/i, '')).slice(0, 48))
  }
  const err = imp.error ? (isApiError(imp.error) && imp.error.code === 'bad_file' ? t('agents.import.badFile', { why: errorMessage(imp.error) }) : errorMessage(imp.error)) : null
  const go = () =>
    imp.mutate(
      { topic_path: where, markdown: text, name: name.trim() || undefined },
      {
        onSuccess: (a) => {
          toast.success(t('agents.create.done', { name: a.display_name }))
          if (a.ignored?.length || a.allowed_tools?.length) setDone(a)
          else onOpen(a)
        },
      },
    )
  if (done)
    return (
      <div className="grid gap-4" data-testid="agent-import-done">
        {done.allowed_tools?.length ? (
          <Callout tone="warning">{t('agents.import.allowed', { tools: done.allowed_tools.join(', ') })}</Callout>
        ) : null}
        {done.ignored?.length ? (
          <Callout tone="info">{t('agents.import.ignored', { fields: done.ignored.join(', ') })}</Callout>
        ) : null}
        <div>
          <Button onClick={() => onOpen(done)}>
            {t('agents.create.openAgent')} <ArrowRight />
          </Button>
        </div>
      </div>
    )
  return (
    <div className="grid gap-4" data-testid="agent-import-form">
      <FormField label={t('agents.import.file')} hint={t('agents.import.fileHint')}>
        <div className="flex flex-wrap items-center gap-2">
          <Button asChild variant="outline" size="sm">
            <label className="cursor-pointer">
              <FileUp /> {t('agents.import.pick')}
              <input type="file" accept=".md,text/markdown,text/plain" className="sr-only" onChange={(e) => pick(e.target.files?.[0])} data-testid="agent-import-input" />
            </label>
          </Button>
          {file && <span className="truncate text-xs text-muted-foreground">{mask(file, 8)}</span>}
        </div>
      </FormField>
      <FormField label={t('agents.import.paste')}>
        <Textarea
          minRows={6}
          maxRows={16}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={'---\nname: reviewer\ndescription: Reviews the code after each change\ntools: Read, Grep, Glob\n---\nYou are a careful code reviewer...'}
          className="font-mono text-[13px]"
          data-testid="agent-import-text"
        />
      </FormField>
      <div className="grid items-start gap-3 sm:grid-cols-2">
        <FormField label={t('agents.import.topic')}>
          <Select value={where || undefined} onValueChange={setWhere} placeholder={t('agents.create.pickTopic')} options={topics.map((x) => ({ value: x.value, label: mask(x.label, 8) }))} />
        </FormField>
        <FormField label={t('agents.import.name')} hint={t('agents.import.nameHint')}>
          <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={48} className="font-mono" />
        </FormField>
      </div>
      {err && <Callout tone="error">{err}</Callout>}
      <div className="flex gap-2">
        <Button variant="ghost" onClick={onBack}>
          <ArrowLeft /> {t('common.back')}
        </Button>
        <Button className="ml-auto" onClick={go} disabled={!where || !text.trim()} loading={imp.isPending} data-testid="agent-import-go">
          <FileUp /> {t('agents.import.go')}
        </Button>
      </div>
    </div>
  )
}
