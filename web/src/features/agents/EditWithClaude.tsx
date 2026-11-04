// "Edit with Claude": the owner says in a sentence what should change in an agent (its role, triggers, keys, folders,
// limits...). A normal session of the agent's TOPIC (full rights, not the agent's own sandboxed runs) gets the request
// and configures the agent with the skill maxxing-agents; it opens in place on the Agents page
// (/agents/<project>/<topic>/<name>/setup/<sid>, SetupView). An agent can never change its own settings itself.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { WandSparkles } from 'lucide-react'
import { useT } from '@/i18n'
import { agentRoute, useCreateSession, useWorkspace } from '@/lib/queries'
import type { AgentDetail } from '@/lib/types'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Kbd, MOD, Textarea } from '@/components/ui'
import { absTopicDir } from '@/pages/sessions/util'

/** The button (in the header: an outline button, its label hidden on phones; in the profile: a row like "Advanced
 *  settings") and its dialog. */
export function EditWithClaude({ agent: a, variant = 'button' }: { agent: AgentDetail; variant?: 'button' | 'row' }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  return (
    <>
      {variant === 'row' ? (
        <button type="button" onClick={() => setOpen(true)} className="flex items-center gap-2 rounded-xl border px-3 py-2.5 text-left hover:bg-accent" data-testid="agent-edit-claude-row">
          <WandSparkles className="size-4 shrink-0 text-muted-foreground" />
          <span className="grid min-w-0 flex-1">
            <span className="text-sm">{t('agents.edit.button')}</span>
            <span className="truncate text-xs text-muted-foreground">{t('agents.edit.rowDesc')}</span>
          </span>
        </button>
      ) : (
        <Button variant="outline" size="sm" onClick={() => setOpen(true)} aria-label={t('agents.edit.button')} data-testid="agent-edit-claude">
          <WandSparkles /> <span className="max-sm:sr-only">{t('agents.edit.button')}</span>
        </Button>
      )}
      {open && <EditDialog agent={a} onClose={() => setOpen(false)} />}
    </>
  )
}

function EditDialog({ agent: a, onClose }: { agent: AgentDetail; onClose: () => void }) {
  const t = useT()
  const navigate = useNavigate()
  const { data: ws } = useWorkspace()
  const start = useCreateSession()
  const [text, setText] = React.useState('')
  const go = () => {
    const v = text.trim()
    if (!v || start.isPending) return
    // the agent's topic: a normal session there has full rights (the agent's own runs cannot change it)
    const topic = `projects/${a.project}/topics/${a.topic}`
    const message = t('agents.edit.prompt', { path: absTopicDir(ws, a.path) || a.path, name: a.display_name || a.name, text: v })
    start.mutate({ path: topic, message }, { onSuccess: (s) => (onClose(), navigate(`${agentRoute(a)}/setup/${s.id}`)) })
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="agent-edit-dialog">
        <DialogHeader>
          <DialogTitle>{t('agents.edit.title', { name: a.display_name || a.name })}</DialogTitle>
          <DialogDescription>{t('agents.edit.desc')}</DialogDescription>
        </DialogHeader>
        <Textarea
          autoFocus
          minRows={3}
          maxRows={10}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault()
              go()
            }
          }}
          aria-label={t('agents.edit.label')}
          placeholder={t('agents.edit.placeholder')}
          data-testid="agent-edit-text"
        />
        <DialogFooter className="sm:items-center">
          <span className="mr-auto text-xs text-muted-foreground max-md:hidden">
            <Kbd>{MOD}</Kbd> <Kbd>Enter</Kbd>
          </span>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={go} disabled={!text.trim()} loading={start.isPending} data-testid="agent-edit-go">
            <WandSparkles /> {t('agents.edit.go')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
