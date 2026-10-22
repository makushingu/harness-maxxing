// Import from another agent (Hermes, Claude Code, OpenClaw…): 1. copy the prompt into the old agent,
// 2. drop the zip it made, 3. preview (created / merged / refused), 4. import, then let Claude finish
// (tasks, scheduled jobs, keys). Used by the onboarding and Settings › Import.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Bot, Check, Copy, FileArchive, FolderKanban, FolderPlus, GitMerge, Sparkles, Upload, Wand2 } from 'lucide-react'
import { useCreateSession, useImportApply, useImportDiscard, useImportPrompt, useImportUpload, useWorkspace } from '@/lib/queries'
import { errorMessage } from '@/lib/api'
import { fmtBytes } from '@/lib/format'
import type { ImportAgent, ImportPlan, ImportResult } from '@/lib/types'
import { cn, copyText } from '@/lib/utils'
import { useT } from '@/i18n'
import { Badge, Button, Sensitive, Skeleton } from '@/components/ui'
import { Callout, Steps } from '../common'

const AGENTS: { value: ImportAgent; label: string }[] = [
  { value: 'hermes', label: 'Hermes' },
  { value: 'claude-code', label: 'Claude Code' },
  { value: 'openclaw', label: 'OpenClaw' },
  { value: 'other', label: 'Other' },
]

function PromptBox({ text }: { text: string }) {
  const t = useT()
  const [copied, setCopied] = React.useState(false)
  return (
    <div className="grid gap-2">
      <pre className="max-h-64 overflow-y-auto rounded-lg border bg-muted/40 p-3 font-mono text-[12px] leading-relaxed break-words whitespace-pre-wrap">{text}</pre>
      <div>
        <Button
          size="sm"
          onClick={async () => {
            if (await copyText(text)) {
              setCopied(true)
              setTimeout(() => setCopied(false), 1800)
            }
          }}
        >
          {copied ? <Check /> : <Copy />} {copied ? t('import.copied') : t('import.copy')}
        </Button>
      </div>
    </div>
  )
}

function Num({ n, label }: { n: number; label: string }) {
  return (
    <div className="grid gap-0.5 rounded-lg border bg-muted/30 px-3 py-2">
      <span className="text-xl font-semibold tabular-nums">{n}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  )
}

function Preview({ plan }: { plan: ImportPlan }) {
  const t = useT()
  const topics = plan.projects.reduce((a, p) => a + p.topics.length, 0)
  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Num n={plan.projects.length} label={t('import.projects')} />
        <Num n={topics} label={t('import.topics')} />
        <Num n={plan.skills.length} label={t('import.skillsN')} />
        <Num n={plan.files} label={t('import.files', { size: fmtBytes(plan.size) })} />
      </div>
      <ul className="divide-y rounded-lg border">
        {plan.projects.map((p) => (
          <li key={p.name} className="grid gap-1.5 px-3 py-2.5">
            <span className="flex items-center gap-2 text-sm font-medium">
              <FolderKanban className="size-4 text-muted-foreground" />
              <Sensitive>{p.name}</Sensitive>
              <Badge variant={p.exists ? 'muted' : 'default'}>{p.exists ? t('import.merge') : t('import.new')}</Badge>
            </span>
            {p.topics.length > 0 && (
              <span className="flex flex-wrap gap-1.5 pl-6">
                {p.topics.map((tp) => (
                  <span key={tp.name} className={cn('inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs', tp.exists ? 'text-muted-foreground' : 'border-primary/40 text-foreground')}>
                    {tp.exists ? <GitMerge className="size-3" /> : <FolderPlus className="size-3" />}
                    <Sensitive>{tp.name}</Sensitive>
                    <span className="text-muted-foreground tabular-nums">· {tp.files}</span>
                  </span>
                ))}
              </span>
            )}
          </li>
        ))}
        {plan.root_memory && (
          <li className="flex items-center gap-2 px-3 py-2.5 text-sm">
            <Bot className="size-4 text-muted-foreground" /> {t('import.rootMemory')}
          </li>
        )}
        {plan.skills.length > 0 && (
          <li className="flex flex-wrap items-center gap-2 px-3 py-2.5 text-sm">
            <Sparkles className="size-4 text-muted-foreground" /> {t('import.skills')}
            {plan.skills.map((s) => (
              <Badge key={s} variant="muted">
                {s}
              </Badge>
            ))}
          </li>
        )}
        {plan.aside.length > 0 && (
          <li className="flex flex-wrap items-center gap-2 px-3 py-2.5 text-sm">
            <FileArchive className="size-4 text-muted-foreground" /> {t('import.aside')}
            {plan.aside.slice(0, 8).map((s) => (
              <Badge key={s} variant="muted">
                {s}
              </Badge>
            ))}
            {plan.aside.length > 8 && <span className="text-xs text-muted-foreground">+{plan.aside.length - 8}</span>}
          </li>
        )}
      </ul>
      <p className="text-xs text-muted-foreground">{t('import.neverOverwrite')}</p>
      {plan.secrets.length > 0 && (
        <Callout tone="warning" title={t('import.secrets', { count: plan.secrets.length })}>
          <ul className="mt-1 grid gap-0.5 font-mono text-xs">
            {plan.secrets.slice(0, 6).map((s) => (
              <li key={s.file}>
                {s.file} ({s.kinds.join(', ')})
              </li>
            ))}
          </ul>
          <p className="mt-1.5">{t('import.secretsHint')}</p>
        </Callout>
      )}
      {plan.skipped.length > 0 && <Callout tone="info" title={t('import.skipped', { count: plan.skipped.length })}>{plan.skipped.slice(0, 4).map((s) => `${s.file} (${s.reason})`).join(' · ')}</Callout>}
    </div>
  )
}

/** `autoFinish`: the session where Claude finishes the import is started right away (onboarding) instead
 *  of on a button that opens it. */
export function ImportWizard({ onDone, compact, autoFinish }: { onDone?: (r: ImportResult) => void; compact?: boolean; autoFinish?: boolean }) {
  const t = useT()
  const navigate = useNavigate()
  const [agent, setAgent] = React.useState<ImportAgent>('hermes')
  const prompt = useImportPrompt(agent)
  const upload = useImportUpload()
  const apply = useImportApply()
  const discard = useImportDiscard()
  const create = useCreateSession()
  const { data: ws } = useWorkspace()
  const [plan, setPlan] = React.useState<ImportPlan | null>(null)
  const [result, setResult] = React.useState<ImportResult | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [drag, setDrag] = React.useState(false)
  const [finishing, setFinishing] = React.useState(false)
  const input = React.useRef<HTMLInputElement>(null)

  const send = (f: File | undefined) => {
    if (!f) return
    setError(null)
    upload.mutate(f, { onSuccess: setPlan, onError: (e) => setError(errorMessage(e)) })
  }
  const finish = (r: ImportResult | null = result, open = true) => {
    if (!r) return
    const inbox = (ws?.projects || []).flatMap((p) => p.topics).find((tp) => tp.path.endsWith('/topics/inbox'))
    create.mutate(
      { path: inbox?.path || '', title: t('import.finishTitle'), message: r.finish_prompt },
      { onSuccess: (s) => (open ? navigate(`/sessions/${s.id}`) : setFinishing(true)) },
    )
  }

  if (result)
    return (
      <div className="grid gap-4">
        <Callout tone="success" title={t('import.done', { projects: result.projects.length, topics: result.topics.length, files: result.files })}>
          {result.merged.length > 0 && <p>{t('import.mergedInto', { count: result.merged.length })}</p>}
          <p className="mt-1 font-mono text-xs">
            <Sensitive>{result.report}</Sensitive>
          </p>
        </Callout>
        {finishing && <Callout tone="info" icon={Wand2} title={t('import.finishing')} />}
        <div className="flex flex-wrap gap-2">
          {!finishing && (
            <Button onClick={() => finish()} loading={create.isPending}>
              <Wand2 /> {t('import.finish')}
            </Button>
          )}
          {onDone && (
            <Button variant="outline" onClick={() => onDone(result)}>
              {t('common.continue')}
            </Button>
          )}
        </div>
        {!finishing && <p className="text-xs text-muted-foreground">{t('import.finishHint')}</p>}
      </div>
    )

  return (
    <div className={cn('grid', compact ? 'gap-5' : 'gap-6')}>
      <Steps
        items={[
          <div key="1" className="grid gap-3">
            <span>{t('import.step1')}</span>
            <div role="radiogroup" aria-label={t('import.agent')} className="grid grid-cols-2 gap-1.5 sm:max-w-xl sm:grid-cols-4">
              {AGENTS.map((a) => (
                <button
                  key={a.value}
                  type="button"
                  role="radio"
                  aria-checked={agent === a.value}
                  onClick={() => setAgent(a.value)}
                  className={cn(
                    'rounded-md border px-3 py-2 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                    agent === a.value ? 'border-primary bg-primary/10 text-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                  )}
                >
                  {a.value === 'other' ? t('import.other') : a.label}
                </button>
              ))}
            </div>
            {prompt.data ? <PromptBox text={prompt.data.prompt} /> : <Skeleton className="h-40" />}
          </div>,
          <div key="2" className="grid gap-3">
            <span>{t('import.step2')}</span>
            {!plan && (
              <button
                type="button"
                onClick={() => input.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault()
                  setDrag(true)
                }}
                onDragLeave={() => setDrag(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setDrag(false)
                  send(e.dataTransfer.files[0])
                }}
                className={cn(
                  'flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-sm text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                  drag && 'border-primary bg-primary/5 text-foreground',
                )}
              >
                <Upload className="size-5" />
                {upload.isPending ? t('import.reading') : t('import.drop')}
                <input ref={input} type="file" accept=".zip,application/zip" className="hidden" onChange={(e) => send(e.target.files?.[0])} />
              </button>
            )}
            {error && <Callout tone="error">{error}</Callout>}
            {plan && <Preview plan={plan} />}
            {plan && (
              <div className="flex flex-wrap gap-2">
                <Button
                  loading={apply.isPending}
                  onClick={() =>
                    apply.mutate(plan.id, {
                      onSuccess: (r) => {
                        setResult(r)
                        setPlan(null)
                        if (autoFinish) finish(r, false)
                      },
                      onError: (e) => setError(errorMessage(e)),
                    })
                  }
                >
                  <FileArchive /> {t('import.apply')}
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => {
                    discard.mutate(plan.id)
                    setPlan(null)
                  }}
                >
                  {t('common.cancel')}
                </Button>
              </div>
            )}
          </div>,
        ]}
      />
    </div>
  )
}
