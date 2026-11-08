// What an agent says, drawn like an answer of a session: paths of the files root open the in-app viewer (the
// pictures, videos and sounds it names show under the text: MessageMedia of the sessions).
import * as React from 'react'
import type { Components } from 'react-markdown'
import { useSettings, useWorkspace } from '@/lib/queries'
import { ItemContext, useFileLink, type ItemCtx } from '@/pages/sessions/Items'
import { linkifyMarkdown } from '@/pages/sessions/util'

const Markdown = React.lazy(() => import('@/components/ui/markdown').then((m) => ({ default: m.Markdown })))

/** Provides what the answers need (the files root) to a conversation of agents. */
export function AnswerContext({ children }: { children: React.ReactNode }) {
  const { data: settings } = useSettings()
  const { data: ws } = useWorkspace()
  const filesRoot = settings?.files_root || ws?.root || null
  const value = React.useMemo<ItemCtx>(
    () => ({ filesRoot, models: undefined, running: false, tz: settings?.timezone, wsRoot: ws?.root || null }),
    [filesRoot, settings?.timezone, ws?.root],
  )
  return <ItemContext.Provider value={value}>{children}</ItemContext.Provider>
}

/** The text of an answer (markdown, file links open the viewer). `components`: extra Markdown overrides (@name chips). */
export function AnswerText({ text, components }: { text: string; components?: Components }) {
  const { filesRoot } = React.useContext(ItemContext)
  const md = React.useMemo(() => linkifyMarkdown(text, filesRoot), [text, filesRoot])
  const onLink = useFileLink()
  return (
    <React.Suspense fallback={<p className="whitespace-pre-wrap break-words">{text}</p>}>
      <Markdown className="text-sm" onLink={onLink} components={components}>
        {md}
      </Markdown>
    </React.Suspense>
  )
}
