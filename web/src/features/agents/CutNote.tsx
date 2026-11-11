import { Link } from 'react-router'
import { useT } from '@/i18n'
import { agentRunRoute } from '@/lib/queries'
import type { AgentMessage } from '@/lib/types'

/** A message the thread keeps cut (`cut`: its whole length): said, with the run that has it all (path: its agent). */
export function CutNote({ m, path }: { m: AgentMessage; path?: string }) {
  const t = useT()
  if (!m.cut) return null
  return (
    <p className="text-xs text-muted-foreground italic" data-testid="agent-cut">
      {t('agents.thread.cut', { n: m.cut.toLocaleString() })}{' '}
      {path && m.session && (
        <Link to={agentRunRoute(path, m.session)} className="text-primary not-italic hover:underline pointer-coarse:inline-block pointer-coarse:py-3">
          {t('agents.thread.cutOpen')}
        </Link>
      )}
    </p>
  )
}

/** The owner's message waits for the run that holds the day's budget: it starts by itself once that run ends. */
export function WaitingNote({ m }: { m: AgentMessage }) {
  const t = useT()
  return m.waiting ? <span className="shrink-0" data-testid="agent-waiting">{t('agents.conv.waitsForRun')}</span> : null
}
