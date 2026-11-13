// The "working" block of the sidebar's session preview card (components/shell/SessionPreview.tsx), for a running
// session: the same rows the thread shows at its bottom while Claude works - the last tool cards of the turn (live
// spinner), the sub-agents / background commands still running with what they do now, then the running line with its
// timer. Lazy-loaded with the Sessions page chunk (the shell stays light) and mounted only while the card is open on
// a running session: it opens that one session's stream (the thread's own live log, reused if the session is opened
// next) and closes it when the card goes. Read-only: inert, nothing in it takes focus or a click.
import * as React from 'react'
import { useSettings, useWorkspace } from '@/lib/queries'
import type { Session } from '@/lib/types'
import { ItemContext, ItemRow } from './Items'
import { isShownTask, taskStatus, useSessionLog, type Item } from './log'
import { TaskLine } from './Tasks'
import { RunningRow } from './Thread'
import { absTopicDir } from './util'

/** Tool cards of the turn shown at most (the newest ones, like the bottom of the thread): fewer when sub-agents run,
 *  the card stays short. */
const MAX_TOOLS = 2
const MAX_TASKS = 2

export default function PreviewWorking({ session }: { session: Session }) {
  const log = useSessionLog(session.id, true)
  const { data: ws } = useWorkspace()
  const { data: settings } = useSettings()
  const dir = absTopicDir(ws, session.path)
  const ctx = React.useMemo(
    () => ({ filesRoot: settings?.files_root || null, models: undefined, running: true, tz: settings?.timezone, topicDir: dir, wsRoot: ws?.root || null }),
    [settings?.files_root, settings?.timezone, dir, ws?.root],
  )
  const tasks = React.useMemo(
    () => Object.values(log.tasks).filter((tk) => isShownTask(tk) && taskStatus(tk, true) === 'running').sort((a, b) => a.started - b.started),
    [log.tasks],
  )
  const tools = React.useMemo(() => {
    const out: Extract<Item, { kind: 'tool' }>[] = []
    const max = tasks.length ? 1 : MAX_TOOLS
    for (let i = log.items.length - 1; i >= 0 && out.length < max; i--) {
      const it = log.items[i]
      if (it.kind === 'user' || it.kind === 'result') break
      // a running sub-agent is listed below with its live progress, not twice
      if (it.kind === 'tool' && !(isShownTask(it.task) && taskStatus(it.task, true) === 'running')) out.push(it)
    }
    return out.reverse()
  }, [log.items, tasks.length])
  if (log.status !== 'ready') return null
  return (
    <ItemContext.Provider value={ctx}>
      <div inert className="grid gap-1.5" data-testid="session-preview-working">
        {tools.map((it) => (
          <ItemRow key={it.key} item={it} live={!it.result} />
        ))}
        {tasks.length > 0 && (
          <ul className="grid gap-0.5 rounded-lg border bg-card p-1">
            {tasks.slice(-MAX_TASKS).map((tk) => (
              <li key={tk.id} className="grid grid-cols-[minmax(0,1fr)] content-center gap-0.5 px-2 py-1">
                <TaskLine task={tk} />
              </li>
            ))}
          </ul>
        )}
        <RunningRow session={session} log={log} />
      </div>
    </ItemContext.Provider>
  )
}
