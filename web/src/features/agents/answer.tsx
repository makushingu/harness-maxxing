// What an agent says, drawn like an answer of a session - but its text may come from outside (mail, Telegram, a
// webhook, another member of a group): only the paths of the agent's own folders (its scope, GET .../media-roots)
// become links to the in-app viewer, thumbnails and players (MessageMedia of the sessions, each file checked by the
// server with `within`); any other path stays plain text, and a picture of this site loads at once only when it is
// a file of the scope.
import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import type { Components } from 'react-markdown'
import { api } from '@/lib/api'
import { useSettings, useWorkspace } from '@/lib/queries'
import { agentUrl } from '@/lib/queries/agents'
import { groupUrl } from '@/lib/queries/agentGroups'
import { fileRawUrl, fileThumbUrl } from '@/lib/queries/files'
import { ItemContext, useFileLink, type ItemCtx } from '@/pages/sessions/Items'
import { linkifyMarkdown, scopeOf } from '@/pages/sessions/util'

const Markdown = React.lazy(() => import('@/components/ui/markdown').then((m) => ({ default: m.Markdown })))

/** Whose answers: an agent (its folder and `writable` folders) or a group (its folder and its members'). */
export type AnswerOwner = { agent: string } | { group: string }

/** The folders whose files the answers may show (server-computed, minus secret and private paths). Until it comes:
 *  the owner's own folder. */
function useScope(owner: AnswerOwner, wsRoot: string | null): string[] {
  const path = 'agent' in owner ? owner.agent : owner.group
  const url = 'agent' in owner ? agentUrl(owner.agent, '/media-roots') : groupUrl(owner.group, '/media-roots')
  const { data } = useQuery({
    // under the agents / agent-groups keys: the bus refreshes them when an agent or a group changes
    queryKey: ['agent' in owner ? 'agents' : 'agent-groups', 'media-roots', path],
    queryFn: () => api.get<{ roots: string[] }>(url).then((r) => r.roots),
    staleTime: 60_000,
  })
  return React.useMemo(() => data ?? (wsRoot ? [`${wsRoot.replace(/\/+$/, '')}/${path}`] : []), [data, wsRoot, path])
}

/** Provides what the answers need (the files root, the scope) to a conversation of agents. */
export function AnswerContext({ owner, children }: { owner: AnswerOwner; children: React.ReactNode }) {
  const { data: settings } = useSettings()
  const { data: ws } = useWorkspace()
  const filesRoot = settings?.files_root || ws?.root || null
  const scope = useScope(owner, ws?.root || null)
  const value = React.useMemo<ItemCtx>(
    () => ({ filesRoot, models: undefined, running: false, tz: settings?.timezone, wsRoot: ws?.root || null, scope }),
    [filesRoot, settings?.timezone, ws?.root, scope],
  )
  return <ItemContext.Provider value={value}>{children}</ItemContext.Provider>
}

/** `/api/files/raw|thumb?path=<a file of the scope>[&w=…]` -> the same URL checked by the server (`within`), else null. */
function scopedImage(src: string, scope: readonly string[]): string | null {
  let u: URL
  try {
    u = new URL(src, location.origin)
  } catch {
    return null
  }
  if (u.origin !== location.origin || !/^\/api\/files\/(raw|thumb)$/.test(u.pathname)) return null
  const path = u.searchParams.get('path')
  const within = path ? scopeOf(path, scope) : null
  if (!path || !within) return null
  if (u.pathname.endsWith('/raw')) return fileRawUrl(path, false, null, within)
  const w = Number(u.searchParams.get('w')) || 320
  return fileThumbUrl(path, Math.min(Math.max(w, 16), 4096), null, false, 0, within)
}

/** The text of an answer (markdown, file links of the scope open the viewer: useFileLink; the others are plain text
 *  titled with their real path: Markdown). `components`: extra Markdown overrides (@name chips). */
export function AnswerText({ text, components }: { text: string; components?: Components }) {
  const { scope, filesRoot } = React.useContext(ItemContext)
  const roots = scope ?? filesRoot
  const md = React.useMemo(() => linkifyMarkdown(text, roots), [text, roots])
  const onLink = useFileLink()
  const localImage = React.useCallback((src: string) => (scope ? scopedImage(src, scope) : src), [scope])
  return (
    <React.Suspense fallback={<p className="whitespace-pre-wrap break-words">{text}</p>}>
      <Markdown className="text-sm" onLink={onLink} components={components} localImage={localImage}>
        {md}
      </Markdown>
    </React.Suspense>
  )
}
