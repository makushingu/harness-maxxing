// "Edit with Claude" and "Create with Claude": no dialog. The button opens a new-session draft of the right topic in
// Sessions (/sessions?new=1&path=<topic>&prompt=<text>) with the request already started in the composer (not sent,
// the cursor at the end): the owner finishes the sentence and sends. A normal session of the topic has the user's
// rights (an agent's own runs can never change its settings) and does the work with the skill maxxing-agents.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { WandSparkles } from 'lucide-react'
import { useT } from '@/i18n'
import { useWorkspace } from '@/lib/queries'
import type { AgentDetail } from '@/lib/types'
import { Button } from '@/components/ui'

/** A new session of `topic` (projects/<p>/topics/<t>) in Sessions, its composer pre-filled with `prompt`. */
export const draftUrl = (topic: string, prompt: string) => `/sessions?new=1&path=${encodeURIComponent(topic)}&prompt=${encodeURIComponent(prompt)}`

/** Opens a new session that creates an agent: in `topic` when one is in context, otherwise in general/inbox (or the
 *  first topic) with a request that starts by agreeing on the right project and topic. */
export function useCreateWithClaude() {
  const t = useT()
  const navigate = useNavigate()
  const { data: ws } = useWorkspace()
  return React.useCallback(
    (topic?: string) => {
      if (topic) return navigate(draftUrl(topic, t('agents.create.prompt')))
      const all = (ws?.projects || []).filter((p) => p.name !== 'system').flatMap((p) => p.topics.map((x) => `projects/${p.name}/topics/${x.name}`))
      const home = all.includes('projects/general/topics/inbox') ? 'projects/general/topics/inbox' : all[0] || 'projects/general/topics/inbox'
      navigate(draftUrl(home, t('agents.create.promptAnywhere')))
    },
    [navigate, t, ws],
  )
}

/** The button (in the header: an outline button, its label hidden on phones; in the profile: a row like "Advanced
 *  settings"): a new session of the agent's topic with the change request started. */
export function EditWithClaude({ agent: a, variant = 'button' }: { agent: AgentDetail; variant?: 'button' | 'row' }) {
  const t = useT()
  const navigate = useNavigate()
  const go = () => navigate(draftUrl(`projects/${a.project}/topics/${a.topic}`, t('agents.edit.prompt', { name: a.display_name || a.name, path: a.path })))
  return variant === 'row' ? (
    <button type="button" onClick={go} className="flex items-center gap-2 rounded-xl border px-3 py-2.5 text-left hover:bg-accent" data-testid="agent-edit-claude-row">
      <WandSparkles className="size-4 shrink-0 text-muted-foreground" />
      <span className="grid min-w-0 flex-1">
        <span className="text-sm">{t('agents.edit.button')}</span>
        <span className="truncate text-xs text-muted-foreground">{t('agents.edit.rowDesc')}</span>
      </span>
    </button>
  ) : (
    <Button variant="outline" size="sm" onClick={go} aria-label={t('agents.edit.button')} data-testid="agent-edit-claude">
      <WandSparkles /> <span className="max-sm:sr-only">{t('agents.edit.button')}</span>
    </Button>
  )
}
